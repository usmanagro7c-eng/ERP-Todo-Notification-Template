from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, get_datetime, getdate, now_datetime, time_diff_in_seconds

from notification_templates import tasks

DOCTYPE = "Custom Notification Templates"
SCHEDULE = "Overdue Notification Schedule"


class TestOverdueScheduleSlots(IntegrationTestCase):
	"""Slot based overdue scheduling.

	The scheduler runs every minute, so a slot must never pre-schedule a future
	Email Queue row: if the row's time is changed afterwards the already queued
	mail still fires. These tests pin down that case as well as the "already sent
	today" bookkeeping.
	"""

	def setUp(self):
		super().setUp()

		self.settings = frappe.get_single(DOCTYPE)
		self.settings.enable_overdue_notification = 1
		# the fixed daily time has its own branch, keep the slots in focus
		self.settings.overdue_send_time = None
		self.settings.overdue_time_last_run = None
		self.settings.overdue_schedules = []
		self.settings.save(ignore_permissions=True)

		# a plain dict is enough, the tests never touch the ToDo table
		self.todo = {
			"name": "test-todo",
			"allocated_to": "Administrator",
			"status": "Open",
			"date": getdate(),
			"description": "an overdue task",
		}

	def _add_slot(self, slot_time, enable=1):
		row = self.settings.append("overdue_schedules", {"time": slot_time, "enable": enable})
		self.settings.save(ignore_permissions=True)
		return row.name

	def _add_due_slot(self, slot_time, enable=1):
		"""Add a slot whose time has passed but that was configured *before* its time.

		       That is the normal case: the row was added in advance and the cron tick
		that should have run it simply has not happened yet. Saving a slot whose time
		is already in the past would instead mark it skipped, see
		       :meth:`_add_slot` and ``test_slot_configured_in_the_past_is_skipped_today``.
		"""
		name = self._add_slot(slot_time, enable)
		self._clear_skipped()
		return name

	def _clear_skipped(self):
		"""Un-mark every slot as skipped for today.

		Saving the form re-evaluates all rows, so a slot that should behave as if
		it had been configured before its time has to be cleared after the last save.
		"""
		for row in frappe.get_all(SCHEDULE, filters={"parent": DOCTYPE}, fields="name"):
			frappe.db.set_value(SCHEDULE, row.name, "skipped_date", None)

	def _get_slot(self, name):
		return frappe.db.get_value(
			SCHEDULE, name, ["name", "time", "last_run", "queued_date", "skipped_date"], as_dict=True
		)

	def _run_scheduler(self, sent=True, ticks=1):
		"""Run the scheduler entry point with the actual mail sending mocked out."""
		with patch.object(tasks, "_send_to_users", return_value=sent) as mock_send:
			for _ in range(ticks):
				tasks._send_overdue_todo_report()
		return mock_send

	def _run_scheduler_for_real(self, ticks=1):
		"""Let the scheduler build the mails for real and only stub ``frappe.sendmail``.

		This is the only way to catch a mail that gets *scheduled* instead of sent,
		because ``_send_to_users`` is where a future Email Queue row would be created.
		"""
		sent = []
		with (
			patch.object(tasks, "_get_overdue_todos", return_value=[self.todo]),
			patch.object(frappe, "sendmail", side_effect=lambda **kwargs: sent.append(kwargs)),
		):
			for _ in range(ticks):
				tasks._send_overdue_todo_report()
		return sent

	def _time_a_minute_ago(self):
		return (now_datetime() - timedelta(minutes=1)).time()

	def test_slot_in_the_future_is_not_sent(self):
		slot = self._add_slot("23:59:00")

		self.assertEqual(self._run_scheduler().call_count, 0)
		self.assertIsNone(self._get_slot(slot).last_run)

	def test_slot_in_the_future_queues_no_email(self):
		"""Regression: a future slot must not leave a future dated Email Queue row.

		Queuing one used to keep sending after the row's time had been changed in
		the settings, because the already scheduled mail was never cancelled.
		"""
		self._add_slot("23:59:00")
		queued_before = frappe.db.count("Email Queue")

		self.assertEqual(self._run_scheduler_for_real(), [])
		self.assertEqual(frappe.db.count("Email Queue"), queued_before)

	def test_reached_slot_sends_immediately_and_is_never_scheduled(self):
		self._add_due_slot("00:01:00")
		queued_before = frappe.db.count("Email Queue")

		sent = self._run_scheduler_for_real()

		self.assertEqual(len(sent), 1)
		self.assertNotIn("send_after", sent[0])
		self.assertFalse(sent[0]["delayed"])
		self.assertEqual(frappe.db.count("Email Queue"), queued_before)

	def test_slot_sends_once_when_its_time_has_passed(self):
		slot = self._add_due_slot(self._time_a_minute_ago())

		self.assertEqual(self._run_scheduler().call_count, 1)

		last_run = self._get_slot(slot).last_run
		self.assertTrue(last_run)
		self.assertEqual(getdate(last_run), getdate())

	def test_slot_does_not_send_twice_on_the_same_day(self):
		self._add_due_slot("00:01:00")

		self.assertEqual(self._run_scheduler(ticks=2).call_count, 1)

	def test_disabled_slot_is_ignored(self):
		self._add_due_slot("00:01:00", enable=0)

		self.assertEqual(self._run_scheduler().call_count, 0)

	def test_last_run_is_not_stamped_when_nothing_was_sent(self):
		slot = self._add_due_slot("00:01:00")

		self.assertEqual(self._run_scheduler(sent=False).call_count, 1)
		self.assertIsNone(self._get_slot(slot).last_run)

	def test_moving_a_slot_time_rearms_it_for_today(self):
		slot = self._add_due_slot("00:02:00")
		self._run_scheduler()
		self.assertTrue(self._get_slot(slot).last_run)

		# move it to a time that has not been reached yet
		future = (now_datetime() + timedelta(minutes=30)).strftime("%H:%M:%S")
		self.settings.get("overdue_schedules")[0].time = future
		self.settings.save(ignore_permissions=True)

		self.assertIsNone(self._get_slot(slot).last_run)
		self.assertIsNone(self._get_slot(slot).skipped_date)
		self.assertEqual(self._run_scheduler().call_count, 0)

	def test_saving_without_a_time_change_keeps_the_stored_last_run(self):
		"""A browser form posts stale hidden values, they must not wipe the stamp."""
		slot = self._add_due_slot("00:01:00")
		self._run_scheduler()
		stamped = self._get_slot(slot).last_run

		self.settings.reload()
		self.settings.get("overdue_schedules")[0].last_run = None
		self.settings.get("overdue_schedules")[0].queued_date = None
		self.settings.save(ignore_permissions=True)

		self.assertEqual(self._get_slot(slot).last_run, stamped)
		self.assertEqual(self._run_scheduler().call_count, 0)

	def test_changing_the_daily_send_time_rearms_it_for_today(self):
		self._set_daily_overdue_time("00:01:00")
		self.assertEqual(self._run_scheduler().call_count, 1)
		self.assertEqual(getdate(frappe.db.get_single_value(DOCTYPE, "overdue_time_last_run")), getdate())

		self.settings.reload()
		self._set_daily_overdue_time("00:02:00")

		# a NULL Datetime reads back as 0001-01-01, so assert on the day instead
		last_run = frappe.db.get_single_value(DOCTYPE, "overdue_time_last_run")
		self.assertNotEqual(getdate(last_run), getdate())
		self.assertEqual(self._run_scheduler(ticks=2).call_count, 1)

	def _set_daily_overdue_time(self, send_time):
		"""Set the fixed overdue time as if it had been configured before it was due."""
		self.settings.overdue_send_time = send_time
		self.settings.save(ignore_permissions=True)
		frappe.db.set_single_value(DOCTYPE, "overdue_time_skipped_date", None)

	def test_each_slot_keeps_its_own_bookkeeping(self):
		"""One slot having run must not suppress the others."""
		self._add_due_slot("00:01:00")
		second = self._add_due_slot(self._time_a_minute_ago())

		self.assertEqual(self._run_scheduler().call_count, 2)
		self.assertTrue(self._get_slot(second).last_run)


class TestOverdueTargetTime(IntegrationTestCase):
	def test_target_time_is_today_at_the_slot_time(self):
		now = now_datetime()
		target = tasks._get_target_time(now, "13:45:00")

		self.assertEqual((target.hour, target.minute, target.second), (13, 45, 0))
		self.assertEqual(getdate(target), getdate(now))

	def test_target_time_accepts_a_timedelta(self):
		"""A Time field comes back from the database as a timedelta."""
		target = tasks._get_target_time(now_datetime(), timedelta(hours=13, minutes=45))

		self.assertEqual((target.hour, target.minute), (13, 45))

	def test_sub_minute_drift_is_within_one_tick(self):
		now = now_datetime()
		target = tasks._get_target_time(now, (now + timedelta(seconds=30)).time())

		self.assertLessEqual(abs(time_diff_in_seconds(target, now)), 60)
		self.assertEqual(get_datetime(target).date(), now.date())


class TestOverdueSlotMailFreshness(IntegrationTestCase):
	"""Every slot must build its mail from the task list as it is at send time.

	Regression: a slot that was not due yet used to be rendered immediately and
	parked in the Email Queue with ``send_after``. Its contents were frozen from
	that moment, so a task completed or unassigned afterwards still showed up in
	the mail that finally went out - a mail queued at 00:00 for a 14:30 slot kept
	listing tasks that were closed at 11:03.

	``test_task_closed_between_two_slots_is_absent_from_the_later_mail`` is the
	end to end guard for that; the rest pin down the surrounding behaviour.

	These tests run the real task query and the real mail building, only
	``frappe.sendmail`` is stubbed (``frappe.in_test`` stops the SMTP send anyway),
	so the site already has ToDos of its own. Everything below is therefore scoped
	to Administrator's mail and to Email Queue rows created by this test.
	"""

	def setUp(self):
		super().setUp()

		self.settings = frappe.get_single(DOCTYPE)
		self.settings.enable_overdue_notification = 1
		self.settings.overdue_send_time = None
		self.settings.overdue_time_last_run = None
		self.settings.overdue_schedules = []
		self.settings.save(ignore_permissions=True)

		self.todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": "Administrator",
				"description": "a task that will be completed mid day",
				"priority": "Medium",
				"status": "Open",
				"date": getdate(),
			}
		).insert(ignore_permissions=True)

	def _add_slot(self, slot_time):
		row = self.settings.append("overdue_schedules", {"time": slot_time, "enable": 1})
		self.settings.save(ignore_permissions=True)
		return row.name

	def _add_due_slot(self, slot_time):
		"""Add a slot whose time has passed but that was configured before its time.

		Saving a slot whose time is already in the past marks it skipped for today,
		which would hide the freshness behaviour these tests are about.
		"""
		name = self._add_slot(slot_time)
		self._clear_skipped()
		return name

	def _clear_skipped(self):
		for row in frappe.get_all(SCHEDULE, filters={"parent": DOCTYPE}, fields="name"):
			frappe.db.set_value(SCHEDULE, row.name, "skipped_date", None)

	def _rendered_mails(self):
		"""Run the scheduler for real and return every mail it handed to sendmail.

		Only ``frappe.sendmail`` is stubbed, so the real task query and the real
		template args are used. The site has ToDos of its own, so callers must pick
		the mail they care about by recipient rather than by position.
		"""
		mails = []
		with patch.object(frappe, "sendmail", side_effect=lambda **kwargs: mails.append(kwargs)):
			tasks._send_overdue_todo_report()
		return mails

	def _my_mails(self):
		"""Only the mails addressed to Administrator, who owns this test's ToDo."""
		return [mail for mail in self._rendered_mails() if "admin@example.com" in mail["recipients"]]

	def _my_todo_names(self, mail):
		return {todo["name"] for todo in mail["args"]["todo_list"]}

	def _mails_carrying(self, todo_name):
		"""Every Administrator mail that still lists this task."""
		return [mail for mail in self._my_mails() if todo_name in self._my_todo_names(mail)]

	def test_completed_task_drops_out_of_the_next_slot_mail(self):
		self._add_due_slot("00:01:00")

		self.assertEqual(len(self._mails_carrying(self.todo.name)), 1)

		# the task is finished / closed after that mail was built
		self.todo.reload()
		self.todo.status = "Closed"
		self.todo.save(ignore_permissions=True)

		self._add_due_slot("00:02:00")

		# no later mail may mention it, whether or not a mail is sent at all
		self.assertEqual(self._mails_carrying(self.todo.name), [])

	def test_unassigned_task_drops_out_of_the_next_slot_mail(self):
		self._add_due_slot("00:01:00")
		self.assertEqual(len(self._mails_carrying(self.todo.name)), 1)

		self.todo.reload()
		self.todo.allocated_to = None
		self.todo.save(ignore_permissions=True)

		self._add_due_slot("00:02:00")
		self.assertEqual(self._mails_carrying(self.todo.name), [])

	def test_task_newly_overdue_appears_in_the_later_slot_mail(self):
		"""The other side of freshness: a task that was not overdue earlier shows up."""
		# keep it out of the first mail by pushing its due date into the future
		self.todo.reload()
		self.todo.date = add_days(getdate(), 5)
		self.todo.save(ignore_permissions=True)

		self._add_due_slot("00:01:00")
		self.assertEqual(self._mails_carrying(self.todo.name), [])

		self.todo.reload()
		self.todo.date = getdate()
		self.todo.save(ignore_permissions=True)

		self._add_due_slot("00:02:00")
		self.assertEqual(len(self._mails_carrying(self.todo.name)), 1)

	def test_slot_mail_is_rendered_not_scheduled(self):
		self._add_due_slot("00:01:00")

		sent_after = now_datetime()
		mail = self._my_mails()[0]

		self.assertNotIn("send_after", mail)
		self.assertFalse(mail["delayed"])
		# no future dated Email Queue row was created by this run
		self.assertEqual(
			frappe.db.count("Email Queue", {"send_after": ["is", "set"], "creation": [">", sent_after]}), 0
		)

	def test_task_closed_between_two_slots_is_absent_from_the_later_mail(self):
		"""The reported bug, end to end.

		One slot is due now and one comes later. Only the due slot may be built on
		this tick; the later one has to wait, because once a mail is built for it
		its contents are frozen and a task closed in the meantime would still be
		listed when that slot finally comes due.
		"""
		first_due = (now_datetime() - timedelta(minutes=2)).time()
		second_due = (now_datetime() + timedelta(minutes=10)).time()
		self._add_due_slot(first_due)
		self._add_slot(second_due)
		self._clear_skipped()

		mails = self._my_mails()
		self.assertEqual(len(mails), 1)
		self.assertIn(self.todo.name, self._my_todo_names(mails[0]))

		# the task is closed while the second slot is still pending
		self.todo.reload()
		self.todo.status = "Closed"
		self.todo.save(ignore_permissions=True)

		# the second slot comes due and is built from the task list as it is now
		later = now_datetime() + timedelta(minutes=11)
		with patch.object(frappe.utils, "now_datetime", return_value=later):
			self.assertEqual(self._mails_carrying(self.todo.name), [])


class TestSkippedForToday(IntegrationTestCase):
	"""A trigger whose time has already passed is skipped for the day.

	Setting times in the past used to fire a burst of catch-up mails the moment
	the form was saved. The settings form now marks such a trigger as skipped so
	it only starts running from tomorrow, while a trigger that was configured
	in advance still fires, including as a catch-up after downtime.
	"""

	def setUp(self):
		super().setUp()

		self.settings = frappe.get_single(DOCTYPE)
		self.settings.enable_overdue_notification = 1
		self.settings.overdue_send_time = None
		self.settings.overdue_time_last_run = None
		self.settings.open_task_send_time = None
		self.settings.open_task_last_run = None
		self.settings.overdue_schedules = []
		self.settings.save(ignore_permissions=True)

	def _run_scheduler(self, sent=True, ticks=1):
		with patch.object(tasks, "_send_to_users", return_value=sent) as mock_send:
			for _ in range(ticks):
				tasks._send_overdue_todo_report()
		return mock_send

	def _run_daily_scheduler(self):
		with patch.object(tasks, "_send_to_users", return_value=True) as mock_send:
			tasks._send_daily_todo_report()
		return mock_send

	def _add_slot(self, slot_time):
		row = self.settings.append("overdue_schedules", {"time": slot_time, "enable": 1})
		self.settings.save(ignore_permissions=True)
		return row.name

	def _get_slot(self, name):
		return frappe.db.get_value(SCHEDULE, name, ["time", "last_run", "skipped_date"], as_dict=True)

	def test_slot_configured_in_the_past_is_skipped_today(self):
		slot = self._add_slot("00:01:00")

		self.assertEqual(getdate(self._get_slot(slot).skipped_date), getdate())
		# and it stays quiet no matter how many ticks pass
		self.assertEqual(self._run_scheduler(ticks=5).call_count, 0)
		self.assertIsNone(self._get_slot(slot).last_run)

	def test_slot_configured_in_the_future_is_not_skipped(self):
		future = (now_datetime() + timedelta(minutes=30)).strftime("%H:%M:%S")

		slot = self._add_slot(future)

		self.assertIsNone(self._get_slot(slot).skipped_date)

	def test_slot_skipped_yesterday_fires_again_today(self):
		"""The skip is only for the day it was configured in."""
		slot = self._add_slot("00:01:00")
		self.assertEqual(getdate(self._get_slot(slot).skipped_date), getdate())

		# pretend it was skipped yesterday, and that nothing has run today
		frappe.db.set_value(SCHEDULE, slot, {"skipped_date": add_days(getdate(), -1), "last_run": None})

		self.assertEqual(self._run_scheduler().call_count, 1)
		self.assertTrue(self._get_slot(slot).last_run)

	def test_slot_configured_in_advance_still_fires_when_its_time_passes(self):
		"""A slot added before its time keeps running when the time arrives."""
		self._add_slot("23:59:00")
		self.assertEqual(self._run_scheduler(ticks=3).call_count, 0)

		tomorrow = get_datetime(now_datetime()).replace(hour=23, minute=59, second=30, microsecond=0)
		with patch.object(frappe.utils, "now_datetime", return_value=tomorrow):
			self.assertEqual(self._run_scheduler().call_count, 1)

	def test_moving_a_slot_to_a_past_time_skips_it_for_today(self):
		slot = self._add_slot((now_datetime() + timedelta(minutes=30)).strftime("%H:%M:%S"))
		self.assertIsNone(self._get_slot(slot).skipped_date)

		self.settings.get("overdue_schedules")[0].time = "00:01:00"
		self.settings.save(ignore_permissions=True)

		self.assertEqual(getdate(self._get_slot(slot).skipped_date), getdate())
		self.assertEqual(self._run_scheduler(ticks=3).call_count, 0)

	def test_daily_send_time_in_the_past_is_skipped_today(self):
		self.settings.overdue_send_time = "00:01:00"
		self.settings.save(ignore_permissions=True)

		self.assertEqual(getdate(frappe.db.get_single_value(DOCTYPE, "overdue_time_skipped_date")), getdate())
		self.assertEqual(self._run_scheduler(ticks=3).call_count, 0)

	def test_daily_open_task_time_in_the_past_is_skipped_today(self):
		self.settings.enable_open_task_notification = 1
		self.settings.open_task_send_time = "00:01:00"
		self.settings.save(ignore_permissions=True)

		self.assertEqual(getdate(frappe.db.get_single_value(DOCTYPE, "open_task_skipped_date")), getdate())
		self.assertEqual(self._run_daily_scheduler().call_count, 0)

	def test_daily_send_time_in_the_future_is_not_skipped(self):
		future = (now_datetime() + timedelta(minutes=30)).strftime("%H:%M:%S")

		self.settings.overdue_send_time = future
		self.settings.save(ignore_permissions=True)

		# a NULL Date reads back as 0001-01-01, so assert on the day instead
		self.assertNotEqual(
			getdate(frappe.db.get_single_value(DOCTYPE, "overdue_time_skipped_date")), getdate()
		)
		self.assertEqual(self._run_scheduler(ticks=3).call_count, 0)

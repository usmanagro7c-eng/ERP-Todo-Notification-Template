import frappe
import json
from datetime import timedelta
from frappe import _

DEFAULT_DAILY_TIME = "09:00:00"


def _get_time_parts(value):
	if not value:
		return 0, 0

	if isinstance(value, timedelta):
		total_seconds = int(value.total_seconds())
		hours, remainder = divmod(total_seconds, 3600)
		minutes, _ = divmod(remainder, 60)
		return hours, minutes

	if hasattr(value, "hour") and hasattr(value, "minute"):
		return value.hour, value.minute

	try:
		parts = str(value).strip().split(":")
		return int(parts[0]), int(parts[1])
	except Exception:
		return 0, 0


def _get_target_time(now, time_value):
	"""Build today's target datetime (naive, system timezone) from a time value."""
	hour, minute = _get_time_parts(time_value)
	return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _time_to_minutes(time_str):
	"""Convert time string HH:MM:SS or HH:MM to total minutes from midnight."""
	hours, minutes = _get_time_parts(time_str)
	return hours * 60 + minutes


def _minutes_to_time(total_minutes):
	"""Convert total minutes from midnight to HH:MM:SS string."""
	hours = int(total_minutes // 60)
	minutes = int(total_minutes % 60)
	return f"{hours:02d}:{minutes:02d}:00"


def _time_to_seconds(value):
	"""Convert time string, timedelta, or time object to total seconds from midnight."""
	if not value:
		return 0

	if isinstance(value, timedelta):
		return int(value.total_seconds())

	if hasattr(value, "hour") and hasattr(value, "minute"):
		return value.hour * 3600 + value.minute * 60 + getattr(value, "second", 0)

	try:
		parts = str(value).strip().split(":")
		hours = int(parts[0])
		minutes = int(parts[1]) if len(parts) > 1 else 0
		seconds = int(float(parts[2])) if len(parts) > 2 else 0
		return hours * 3600 + minutes * 60 + seconds
	except Exception:
		return 0


def _seconds_to_time(total_seconds):
	"""Convert total seconds from midnight to HH:MM:SS string."""
	total_seconds = int(round(total_seconds))
	hours = (total_seconds // 3600) % 24
	remainder = total_seconds % 3600
	minutes = remainder // 60
	seconds = remainder % 60
	return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _get_todo_fields():
	return [
		"name",
		"description",
		"status",
		"priority",
		"date",
		"allocated_to",
		"assigned_by",
		"assigned_by_full_name",
		"assignment_rule",
		"color",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"idx",
		"role",
		"reference_type",
		"reference_name",
		"_liked_by",
	]


def _truncate_description(description, max_words=4):
	if not description:
		return description or ""
	text = frappe.utils.strip_html(description).strip() if ("<" in str(description) and ">" in str(description)) else str(description).strip()
	words = text.split()
	if len(words) > max_words:
		return " ".join(words[:max_words]) + "..."
	return text


def _group_todos_by_user(todos):
	todos_by_user = {}
	for todo in todos:
		user = todo.get("allocated_to")
		if not user:
			continue
		todos_by_user.setdefault(user, []).append(todo)
	return todos_by_user


def _get_open_todos(today):
	return frappe.get_all(
		"ToDo",
		filters={
			"status": "Open",
			"date": [">=", today],
			"allocated_to": ["is", "set"],
		},
		fields=_get_todo_fields(),
		order_by="creation asc",
	)


def _get_daily_todos(today):
	"""Return all open and overdue tasks that are relevant for the daily digest."""
	today = frappe.utils.getdate(today)
	todos = frappe.get_all(
		"ToDo",
		filters={
			"allocated_to": ["is", "set"],
			"status": ["not in", ["Completed", "Cancelled", "Closed"]],
			"date": ["<=", today],
		},
		fields=_get_todo_fields(),
		order_by="date asc, creation asc",
	)

	for todo in todos:
		if todo.get("date") and frappe.utils.getdate(todo.get("date")) < today:
			todo["status"] = "Overdue"

	return todos


def _get_overdue_todos(today):
	"""Return all overdue and open tasks due today or earlier (same as daily digest)."""
	return _get_daily_todos(today)


def _send_to_users(todos_by_user, template, subject, title, color, send_now=False):
	if not todos_by_user:
		return False

	user_info = {
		u.name: u
		for u in frappe.get_all(
			"User",
			filters={"name": ["in", list(todos_by_user.keys())], "enabled": 1},
			fields=["name", "email", "full_name"],
		)
	}

	sent = False
	for user, user_todos in todos_by_user.items():
		u = user_info.get(user)
		if not u:
			# Skip disabled users or users that do not exist
			continue

		email = u.email
		recipient_name = u.full_name or user
		if not email:
			frappe.log_error(f"No email for user {user}", subject)
			continue

		for todo in user_todos:
			if todo.get("description"):
				todo["description"] = _truncate_description(todo["description"])

		has_overdue = any(t.get("status") == "Overdue" for t in user_todos)
		has_open = any(t.get("status") != "Overdue" for t in user_todos)

		user_subject = subject
		if subject in ["Overdue Tasks Alert", "Overdue & Open Tasks Alert"]:
			if has_overdue and has_open:
				user_subject = "Overdue & Open Tasks Alert"
			elif has_overdue:
				user_subject = "Overdue Tasks Alert"
			elif has_open:
				user_subject = "Open Tasks Alert"

		if title == "Daily TODO Report":
			report_intro = _("Your daily todo tasks are given below:")
		elif has_overdue and has_open:
			report_intro = _("Your overdue and open todo tasks are given below:")
		elif has_overdue:
			report_intro = _("Your overdue todo tasks are given below:")
		else:
			report_intro = _("Your daily todo tasks are given below:")

		frappe.sendmail(
			recipients=[email],
			subject=_(user_subject),
			template=template,
			delayed=not send_now,
			raw_html=True,
			args={
				"todo_list": user_todos,
				"report_title": _(title),
				"report_color": color,
				"recipient_name": recipient_name,
				"report_intro": report_intro,
			},
		)
		sent = True
	return sent


def send_daily_todo_report():
	"""Send email to each user for tasks due today, once daily at the configured time."""
	if frappe.flags.in_test:
		return

	if not frappe.db.get_single_value("Custom Notification Templates", "enable_open_task_notification"):
		return

	now = frappe.utils.now_datetime()
	today = frappe.utils.getdate(now)

	send_time = frappe.db.get_single_value("Custom Notification Templates", "open_task_send_time") or DEFAULT_DAILY_TIME
	target = _get_target_time(now, send_time)

	# Already sent today after the target time? Skip.
	raw_last_run = frappe.db.get_single_value("Custom Notification Templates", "open_task_last_run")
	if raw_last_run:
		last_run = frappe.utils.get_datetime(raw_last_run)
		if frappe.utils.getdate(last_run) == today and last_run >= target:
			return

	# Not yet at the configured time? Skip.
	if now < target:
		return

	todos = _get_daily_todos(today)
	_send_to_users(
		_group_todos_by_user(todos),
		"todo",
		"Daily TODO Report",
		"Daily TODO Report",
		"#eef6ff",
	)

	frappe.db.set_single_value("Custom Notification Templates", "open_task_last_run", now, update_modified=False)


def send_overdue_todo_report():
	"""Send overdue alerts across the configured start/end window and fixed daily time."""
	if frappe.flags.in_test:
		return

	if not frappe.db.get_single_value("Custom Notification Templates", "enable_overdue_notification"):
		return

	now = frappe.utils.now_datetime()
	today = frappe.utils.getdate(now)
	just_sent_fixed = False

	send_time = frappe.db.get_single_value("Custom Notification Templates", "overdue_send_time")
	if send_time:
		target = _get_target_time(now, send_time)
		raw_time_last_run = frappe.db.get_single_value("Custom Notification Templates", "overdue_time_last_run")
		if raw_time_last_run:
			time_last_run = frappe.utils.get_datetime(raw_time_last_run)
			already_sent_today = frappe.utils.getdate(time_last_run) == today and time_last_run >= target
		else:
			already_sent_today = False

		if now >= target and not already_sent_today:
			todos = _get_overdue_todos(today)
			_send_to_users(
				_group_todos_by_user(todos),
				"todo",
				"Overdue & Open Tasks Alert",
				"Overdue & Open Tasks Alert",
				"#fff3f3",
			)
			frappe.db.set_single_value("Custom Notification Templates", "overdue_time_last_run", now, update_modified=False)
			just_sent_fixed = True

	# Process scheduled window (intervals) as well if configured
	_process_overdue_schedule(now, just_sent_fixed=just_sent_fixed)


def _process_overdue_schedule(now, just_sent_fixed=False):
	"""Check and send scheduled overdue emails based on time window."""
	today = frappe.utils.getdate(now)
	start_time = frappe.db.get_single_value("Custom Notification Templates", "overdue_start_time")
	end_time = frappe.db.get_single_value("Custom Notification Templates", "overdue_end_time")
	num_mails = frappe.db.get_single_value("Custom Notification Templates", "overdue_num_mails")

	if not start_time or not end_time or not num_mails or int(num_mails) < 2:
		return False

	start_seconds = _time_to_seconds(start_time)
	end_seconds = _time_to_seconds(end_time)
	if start_seconds >= end_seconds:
		return False

	current_time_str = now.strftime("%H:%M:%S")
	current_seconds = _time_to_seconds(current_time_str)

	raw_schedule = frappe.db.get_single_value("Custom Notification Templates", "overdue_schedule")
	schedule = None
	if raw_schedule:
		try:
			schedule = json.loads(raw_schedule)
		except (json.JSONDecodeError, TypeError):
			schedule = None

	if schedule and schedule.get("date") == str(today):
		config_changed = (
			schedule.get("start_time") != str(start_time)
			or schedule.get("end_time") != str(end_time)
			or schedule.get("num_mails") != int(num_mails)
		)
		if not config_changed:
			# Fix 1: Schedule Completion Check.
			# If today's schedule is already completed or all slots were sent, do NOT send any more emails.
			if schedule.get("completed") or all(s.get("sent") for s in schedule.get("slots", [])):
				return False
		else:
			schedule = None
	else:
		schedule = None

	if not schedule:
		# Fix 2: Current Time vs End Time Check.
		# If current time is already at or past end_time, do not generate schedule for today
		# so past slots are not blasted retroactively.
		if current_seconds >= end_seconds:
			return False

		interval = (end_seconds - start_seconds) / (int(num_mails) - 1)
		schedule = {
			"date": str(today),
			"start_time": str(start_time),
			"end_time": str(end_time),
			"num_mails": int(num_mails),
			"completed": False,
			"slots": [
				{"time": _seconds_to_time(start_seconds + (index * interval)), "sent": False}
				for index in range(int(num_mails))
			],
		}
		frappe.db.set_single_value(
			"Custom Notification Templates", "overdue_schedule", json.dumps(schedule), update_modified=False
		)
		frappe.db.set_single_value("Custom Notification Templates", "overdue_schedule_active", 1, update_modified=False)

	slots = schedule.get("slots", [])
	updated = False
	for slot in slots:
		if slot.get("sent"):
			continue
		slot_seconds = _time_to_seconds(slot.get("time", ""))
		if slot_seconds <= current_seconds:
			if just_sent_fixed:
				# Fixed overdue alert was already sent in this exact execution,
				# mark this slot as sent so a duplicate email is not sent in the same minute.
				slot["sent"] = True
				updated = True
				break

			todos = _get_overdue_todos(today)
			_send_to_users(
				_group_todos_by_user(todos),
				"todo",
				"Overdue & Open Tasks Alert",
				"Overdue & Open Tasks Alert",
				"#fff3f3",
			)
			slot["sent"] = True
			updated = True
			break

	if updated:
		all_sent = all(s.get("sent") for s in slots)
		if all_sent:
			# Fix 1: Mark schedule as completed for today, keep record, do NOT deactivate/delete
			schedule["completed"] = True
			frappe.db.set_single_value(
				"Custom Notification Templates",
				"overdue_last_run",
				now,
				update_modified=False,
			)
		frappe.db.set_single_value(
			"Custom Notification Templates",
			"overdue_schedule",
			json.dumps(schedule),
			update_modified=False,
		)
		return True

	return True


@frappe.whitelist()
def create_overdue_schedule(start_time, end_time, num_mails):
	"""Create a schedule to send overdue emails at equal intervals."""
	frappe.only_for("System Manager")
	num_mails = int(num_mails)
	if num_mails < 2:
		frappe.throw(_("Number of mails must be at least 2"))

	start_seconds = _time_to_seconds(start_time)
	end_seconds = _time_to_seconds(end_time)

	if start_seconds >= end_seconds:
		frappe.throw(_("Start time must be before end time"))

	interval = (end_seconds - start_seconds) / (num_mails - 1)

	slots = []
	for i in range(num_mails):
		slot_seconds = start_seconds + (i * interval)
		slot_time = _seconds_to_time(slot_seconds)
		slots.append({"time": slot_time, "sent": False})

	today = frappe.utils.getdate(frappe.utils.now_datetime())
	schedule = {
		"date": str(today),
		"start_time": str(start_time),
		"end_time": str(end_time),
		"num_mails": num_mails,
		"completed": False,
		"slots": slots,
	}
	frappe.db.set_single_value(
		"Custom Notification Templates", "overdue_schedule", json.dumps(schedule), update_modified=False
	)
	frappe.db.set_single_value("Custom Notification Templates", "overdue_schedule_active", 1, update_modified=False)

	return _("Schedule created! {0} emails will be sent at equal intervals from {1} to {2}").format(
		num_mails, start_time, end_time
	)



@frappe.whitelist()
def send_now_daily_report():
	"""Send the daily open task report immediately."""
	frappe.only_for("System Manager")
	today = frappe.utils.getdate(frappe.utils.nowdate())
	todos = _get_daily_todos(today)
	sent = _send_to_users(
		_group_todos_by_user(todos),
		"todo",
		"Daily TODO Report",
		"Daily TODO Report",
		"#eef6ff",
		send_now=True,
	)
	if sent:
		return _("Daily report sent successfully!")
	return _("No open tasks found to send.")


@frappe.whitelist()
def send_now_overdue_report():
	"""Send the overdue task report immediately, regardless of schedule settings."""
	frappe.only_for("System Manager")
	today = frappe.utils.getdate(frappe.utils.nowdate())
	todos = _get_overdue_todos(today)
	sent = _send_to_users(
		_group_todos_by_user(todos),
		"todo",
		"Overdue & Open Tasks Alert",
		"Overdue & Open Tasks Alert",
		"#fff3f3",
		send_now=True,
	)
	if sent:
		return _("Overdue & Open tasks report sent successfully!")
	return _("No overdue or open tasks found to send.")

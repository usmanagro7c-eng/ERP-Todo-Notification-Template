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


def _get_overdue_todos(today):
	todos = frappe.get_all(
		"ToDo",
		filters={
			"allocated_to": ["is", "set"],
			"status": ["not in", ["Completed", "Cancelled", "Closed"]],
			"date": ["<", today],
		},
		fields=_get_todo_fields(),
		order_by="creation asc",
	)

	for todo in todos:
		if todo.get("date") and todo.get("date") < today:
			todo["status"] = "Overdue"

	return todos


def _send_to_users(todos_by_user, template, subject, title, color, send_now=False):
	sent = False
	for user, user_todos in todos_by_user.items():
		email = frappe.db.get_value("User", user, "email")
		recipient_name = frappe.db.get_value("User", user, "full_name") or user
		if not email:
			frappe.log_error(f"No email for user {user}", subject)
			continue

		for todo in user_todos:
			if todo.get("description"):
				todo["description"] = _truncate_description(todo["description"])

		frappe.sendmail(
			recipients=[email],
			subject=_(subject),
			template=template,
			delayed=not send_now,
			raw_html=True,
			args={
				"todo_list": user_todos,
				"report_title": _(title),
				"report_color": color,
				"recipient_name": recipient_name,
				"report_intro": _(
					"Your daily todo tasks are given below:"
					if title == "Daily TODO Report"
					else "Your overdue todo tasks are given below:"
				),
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

	todos = _get_open_todos(today)
	_send_to_users(
		_group_todos_by_user(todos),
		"todo",
		"Daily TODO Report",
		"Daily TODO Report",
		"#eef6ff",
	)

	frappe.db.set_single_value("Custom Notification Templates", "open_task_last_run", now, update_modified=False)


def send_overdue_todo_report():
	"""Send overdue alert on configured fixed daily time (optional) and/or repeat interval (optional)."""
	if frappe.flags.in_test:
		return

	if not frappe.db.get_single_value("Custom Notification Templates", "enable_overdue_notification"):
		return

	now = frappe.utils.now_datetime()
	today = frappe.utils.getdate(now)

	# Process scheduled time-window emails
	if _process_overdue_schedule(now):
		return

	should_send = False

	# Trigger 1: fixed daily send time (overdue_send_time)
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
			should_send = True

	# Trigger 2: repeat interval (overdue_interval)
	interval = frappe.db.get_single_value("Custom Notification Templates", "overdue_interval")
	if interval:
		interval_hours, interval_minutes = _get_time_parts(interval)
		interval_delta = timedelta(hours=interval_hours, minutes=interval_minutes)
		raw_last_run = frappe.db.get_single_value("Custom Notification Templates", "overdue_last_run")
		if not raw_last_run or (now - frappe.utils.get_datetime(raw_last_run)) >= interval_delta:
			should_send = True

	if not should_send:
		return

	todos = _get_overdue_todos(today)
	_send_to_users(
		_group_todos_by_user(todos),
		"todo",
		"Overdue Tasks Alert",
		"Overdue Tasks Alert",
		"#fff3f3",
	)

	# Update both last-run markers so neither trigger re-fires immediately.
	if send_time:
		frappe.db.set_single_value("Custom Notification Templates", "overdue_time_last_run", now, update_modified=False)
	if interval:
		frappe.db.set_single_value("Custom Notification Templates", "overdue_last_run", now, update_modified=False)


def _process_overdue_schedule(now):
	"""Check and send scheduled overdue emails based on time window."""
	schedule_active = frappe.db.get_single_value("Custom Notification Templates", "overdue_schedule_active")
	if not schedule_active:
		return False

	raw_schedule = frappe.db.get_single_value("Custom Notification Templates", "overdue_schedule")
	if not raw_schedule:
		return False

	try:
		schedule = json.loads(raw_schedule)
	except (json.JSONDecodeError, TypeError):
		return False

	slots = schedule.get("slots", [])
	today = frappe.utils.getdate(now)
	current_time_str = now.strftime("%H:%M:%S")
	current_minutes = _time_to_minutes(current_time_str)

	updated = False
	for slot in slots:
		if slot.get("sent"):
			continue
		slot_minutes = _time_to_minutes(slot.get("time", ""))
		if slot_minutes <= current_minutes:
			todos = _get_overdue_todos(today)
			_send_to_users(
				_group_todos_by_user(todos),
				"todo",
				"Overdue Tasks Alert",
				"Overdue Tasks Alert",
				"#fff3f3",
			)
			slot["sent"] = True
			updated = True
			break

	if updated:
		all_sent = all(s.get("sent") for s in slots)
		frappe.db.set_single_value(
			"Custom Notification Templates",
			"overdue_schedule",
			json.dumps(schedule),
			update_modified=False,
		)
		if all_sent:
			frappe.db.set_single_value(
				"Custom Notification Templates",
				"overdue_schedule_active",
				0,
				update_modified=False,
			)
		return True

	return False


@frappe.whitelist()
def create_overdue_schedule(start_time, end_time, num_mails):
	"""Create a schedule to send overdue emails at equal intervals."""
	frappe.only_for("System Manager")
	num_mails = int(num_mails)
	if num_mails < 2:
		frappe.throw(_("Number of mails must be at least 2"))

	start_minutes = _time_to_minutes(start_time)
	end_minutes = _time_to_minutes(end_time)

	if start_minutes >= end_minutes:
		frappe.throw(_("Start time must be before end time"))

	interval = (end_minutes - start_minutes) / (num_mails - 1)

	slots = []
	for i in range(num_mails):
		slot_minutes = start_minutes + (i * interval)
		slot_time = _minutes_to_time(slot_minutes)
		slots.append({"time": slot_time, "sent": False})

	schedule = json.dumps({"slots": slots})
	frappe.db.set_single_value("Custom Notification Templates", "overdue_schedule", schedule, update_modified=False)
	frappe.db.set_single_value("Custom Notification Templates", "overdue_schedule_active", 1, update_modified=False)

	return _("Schedule created! {0} emails will be sent at equal intervals from {1} to {2}").format(
		num_mails, start_time, end_time
	)


@frappe.whitelist()
def send_now_daily_report():
	"""Send the daily open task report immediately."""
	frappe.only_for("System Manager")
	today = frappe.utils.getdate(frappe.utils.nowdate())
	todos = _get_open_todos(today)
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
		"Overdue Tasks Alert",
		"Overdue Tasks Alert",
		"#fff3f3",
		send_now=True,
	)
	if sent:
		return _("Overdue report sent successfully!")
	return _("No overdue tasks found to send.")

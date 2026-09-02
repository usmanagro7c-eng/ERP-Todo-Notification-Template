import frappe
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


def _send_to_users(todos_by_user, template, subject, title, color):
	sent = False
	for user, user_todos in todos_by_user.items():
		email = frappe.db.get_value("User", user, "email")
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
			args={
				"todo_list": user_todos,
				"report_title": _(title),
				"report_color": color,
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

import frappe
from datetime import timedelta
from frappe import _


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

	if isinstance(value, str):
		return int(value[:2]), int(value[3:5])

	return 0, 0


def _normalize_template_name(template_name):
	if not template_name:
		return "todo"
	return str(template_name).strip().lower()


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
		"_user_tags",
		"_liked_by",
	]


def _group_todos_by_user(todos):
	todos_by_user = {}
	for todo in todos:
		user = todo.get("allocated_to")
		if not user:
			continue
		todos_by_user.setdefault(user, []).append(todo)
	return todos_by_user


def send_daily_todo_report():
	"""Send email to each user for tasks due today, once daily at the configured time."""
	if frappe.flags.in_test:
		return

	if not frappe.db.get_single_value("Todo Notification Setting", "enabled"):
		return

	send_time = frappe.db.get_single_value("Todo Notification Setting", "send_time") or "00:00:00"
	template = _normalize_template_name(frappe.db.get_single_value("Todo Notification Setting", "template") or "Todo")

	now = frappe.utils.now_datetime()
	hour, minute = _get_time_parts(send_time)
	target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

	last_run = frappe.db.get_single_value("Todo Notification Setting", "last_run")
	if last_run and last_run.date() == now.date() and last_run >= target:
		return
	if now < target:
		return

	today = frappe.utils.getdate(now)
	todos = frappe.get_all(
		"ToDo",
		filters={
			"status": "Open",
			"date": [">=", today],
			"allocated_to": ["is", "set"],
		},
		fields=_get_todo_fields(),
		order_by="creation asc",
	)

	for user, user_todos in _group_todos_by_user(todos).items():
		email = frappe.db.get_value("User", user, "email")
		if not email:
			frappe.log_error(f"No email configured for user {user}", "Daily TODO Report")
			continue

		frappe.sendmail(
			recipients=[email],
			subject=_("Daily TODO Report"),
			template=template,
			args={
				"todo_list": user_todos,
				"report_title": _("Daily TODO Report"),
				"report_color": "#eef6ff",
			},
		)

	frappe.db.set_single_value("Todo Notification Setting", "last_run", now, update_modified=False)


def send_overdue_todo_report():
	"""Send overdue alert every 2 hours to each user for overdue tasks only."""
	if frappe.flags.in_test:
		return

	if not frappe.db.get_single_value("Todo Notification Setting", "enabled"):
		return

	today = frappe.utils.getdate(frappe.utils.nowdate())
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

	for user, user_todos in _group_todos_by_user(todos).items():
		email = frappe.db.get_value("User", user, "email")
		if not email:
			frappe.log_error(f"No email for user {user}", "Overdue TODO Report")
			continue

		frappe.sendmail(
			recipients=[email],
			subject=_("Overdue Tasks Alert"),
			template="todo",
			args={
				"todo_list": user_todos,
				"report_title": _("Overdue Tasks Alert"),
				"report_color": "#fff3f3",
			},
		)

import frappe
from datetime import timedelta
from frappe import _

DEFAULT_DAILY_TIME = "09:00:00"


def _get_time_parts(value):
	if not value:
		return 0, 0, 0

	if isinstance(value, timedelta):
		total_seconds = int(value.total_seconds())
		hours, remainder = divmod(total_seconds, 3600)
		minutes, seconds = divmod(remainder, 60)
		return hours, minutes, seconds

	if hasattr(value, "hour") and hasattr(value, "minute"):
		return value.hour, value.minute, getattr(value, "second", 0)

	try:
		parts = str(value).strip().split(":")
		hours = int(parts[0])
		minutes = int(parts[1]) if len(parts) > 1 else 0
		seconds = int(float(parts[2])) if len(parts) > 2 else 0
		return hours, minutes, seconds
	except Exception:
		return 0, 0, 0


def _get_target_time(now, time_value):
	"""Build today's target datetime (naive, system timezone) from a time value."""
	hour, minute, second = _get_time_parts(time_value)
	return now.replace(hour=hour, minute=minute, second=second, microsecond=0)


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


def _get_status_badge(status):
	"""Return (background, foreground) colors for a status/workflow_state badge."""
	status = (status or "").strip()
	colors = {
		# Green
		"Paid": ("#e8f5e9", "#2e7d32"),
		"Completed": ("#e8f5e9", "#2e7d32"),
		"Approved": ("#e8f5e9", "#2e7d32"),
		# Blue
		"Submitted": ("#e3f2fd", "#1565c0"),
		"Open": ("#e3f2fd", "#1565c0"),
		"Active": ("#e3f2fd", "#1565c0"),
		# Orange / Yellow
		"Draft": ("#fff8e1", "#ff6f00"),
		"Pending": ("#fff8e1", "#ff6f00"),
		"In Review": ("#fff8e1", "#ff6f00"),
		"Working": ("#fff8e1", "#ff6f00"),
		# Red
		"Overdue": ("#ffebee", "#c62828"),
		"Rejected": ("#ffebee", "#c62828"),
		"Failed": ("#ffebee", "#c62828"),
		# Grey
		"Closed": ("#f3f4f6", "#374151"),
		"Cancelled": ("#f3f4f6", "#374151"),
		"Template": ("#f3f4f6", "#374151"),
	}
	return colors.get(status, ("#f3f4f6", "#374151"))


def _enrich_reference_status(todos):
	"""Attach each todo's reference document's real status as 'reference_status'."""
	from collections import defaultdict

	refs_by_type = defaultdict(list)
	for todo in todos:
		rt = todo.get("reference_type")
		rn = todo.get("reference_name")
		if rt and rn:
			refs_by_type[rt].append((rn, todo))

	STATUS_COLORS = _get_status_badge  # local alias

	for ref_type, items in refs_by_type.items():
		ref_names = list({rn for rn, _ in items})
		fields = ["name", "status"]
		try:
			if frappe.get_meta(ref_type).has_field("workflow_state"):
				fields.append("workflow_state")
			statuses = frappe.get_all(ref_type, filters={"name": ["in", ref_names]}, fields=fields)
			rows = {s.name: s for s in statuses}
			for rn, todo in items:
				row = rows.get(rn)
				ref_status = ""
				if row:
					ref_status = row.get("workflow_state") or row.get("status") or ""
				todo["reference_status"] = ref_status
				bg, fg = STATUS_COLORS(ref_status)
				todo["reference_badge_bg"] = bg
				todo["reference_badge_fg"] = fg
		except Exception:
			for _, todo in items:
				todo["reference_status"] = ""


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
	return todos


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
			todo["is_overdue"] = True

	return todos


def _get_overdue_todos(today):
	"""Return all overdue and open tasks due today or earlier (same as daily digest)."""
	return _get_daily_todos(today)


def _send_to_users(todos_by_user, template, subject, title, color, send_now=False, send_after=None):
	if not todos_by_user:
		return False

	all_todos = [t for todos in todos_by_user.values() for t in todos]
	_enrich_reference_status(all_todos)

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

		has_overdue = any(t.get("is_overdue") for t in user_todos)
		has_open = any(not t.get("is_overdue") for t in user_todos)

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
			delayed=True if send_after else not send_now,
			send_after=send_after,
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
		send_now=True,
	)

	frappe.db.set_single_value("Custom Notification Templates", "open_task_last_run", now, update_modified=False)


def send_overdue_todo_report():
	"""Send overdue alerts at the configured daily time and at every enabled child table slot."""
	if frappe.flags.in_test:
		return

	if not frappe.db.get_single_value("Custom Notification Templates", "enable_overdue_notification"):
		return

	now = frappe.utils.now_datetime()
	today = frappe.utils.getdate(now)

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
				send_now=True,
			)
			frappe.db.set_single_value("Custom Notification Templates", "overdue_time_last_run", now, update_modified=False)

	# Child table based scheduling
	overdue_schedules = frappe.get_all(
		"Overdue Notification Schedule",
		filters={"parent": "Custom Notification Templates", "enable": 1},
		fields=["name", "time", "last_run", "queued_date"],
	)

	for schedule in overdue_schedules:
		if not schedule.get("time"):
			continue

		target = _get_target_time(now, schedule.time)

		# Already sent today? Skip
		if schedule.get("last_run"):
			last_run = frappe.utils.get_datetime(schedule.last_run)
			if frappe.utils.getdate(last_run) == today and last_run >= target:
				continue

		# Not yet at scheduled time? Queue delayed email if not already queued
		if now < target:
			if schedule.get("queued_date") != str(today):
				todos = _get_overdue_todos(today)
				_send_to_users(
					_group_todos_by_user(todos),
					"todo",
					"Overdue & Open Tasks Alert",
					"Overdue & Open Tasks Alert",
					"#fff3f3",
					send_after=target,
				)
				frappe.db.set_value(
					"Overdue Notification Schedule",
					schedule.name,
					{"queued_date": today, "last_run": target},
				)
			continue

		# Time has passed and not yet sent - send immediately
		todos = _get_overdue_todos(today)
		_send_to_users(
			_group_todos_by_user(todos),
			"todo",
			"Overdue & Open Tasks Alert",
			"Overdue & Open Tasks Alert",
			"#fff3f3",
			send_now=True,
		)

		# Update last_run
		frappe.db.set_value("Overdue Notification Schedule", schedule.name, "last_run", now)





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

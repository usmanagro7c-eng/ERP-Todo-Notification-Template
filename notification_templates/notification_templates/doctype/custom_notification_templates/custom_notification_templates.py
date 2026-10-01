from frappe.model.document import Document

from notification_templates.tasks import _get_time_parts


class CustomNotificationTemplates(Document):
	def validate(self):
		self._reconcile_execution_state()

	def _reconcile_execution_state(self):
		"""Keep the scheduler's bookkeeping in sync with the configured times.

		The scheduler decides whether a slot still has to run from the hidden
		``last_run`` / ``queued_date`` columns. Those columns are hidden and
		read-only, so the browser form keeps posting whatever stale values it
		loaded, and editing a time leaves the previous day's stamp behind. Either
		case silently drops or duplicates a send, so the stored values are made
		authoritative here: a row whose time is unchanged keeps its stored stamp,
		and a row whose time changed is re-armed for today.
		"""
		previous = self.get_doc_before_save()
		if not previous:
			return

		stored_rows = {row.name: row for row in (previous.get("overdue_schedules") or [])}

		for row in self.get("overdue_schedules") or []:
			stored_row = stored_rows.get(row.name)

			if stored_row and _get_time_parts(stored_row.time) == _get_time_parts(row.time):
				row.last_run = stored_row.last_run
				row.queued_date = stored_row.queued_date
			else:
				row.last_run = None
				row.queued_date = None

		if _get_time_parts(previous.overdue_send_time) != _get_time_parts(self.overdue_send_time):
			self.overdue_time_last_run = None

		if _get_time_parts(previous.open_task_send_time) != _get_time_parts(self.open_task_send_time):
			self.open_task_last_run = None

# Notification Templates

A Frappe / ERPNext application for sending scheduled email notifications, including daily ToDo reports and overdue task alerts.

---

## Features

- **Daily ToDo Digest**: Aggregates all open ToDo items assigned to each user and dispatches a formatted email summary once a day at a configured exact time.
- **Overdue Tasks Alert**: Two independent triggers for overdue notifications:
  - **Fixed Send Time**: Send once daily at an exact time (e.g. `10:00`).
  - **Repeat Interval**: Send repeatedly every X hours (e.g. `01:00` = every 1 hour, `06:00` = every 6 hours).
  - Both can be enabled together; each runs independently.
- **Configurable Settings DocType (`Custom Notification Templates`)**:
  - Enable / disable notifications for daily and overdue separately.
  - Exact send time for daily report.
  - Exact send time and repeat interval for overdue alerts.
  - **Dynamic Template Selection**: dropdown reads all templates available in `templates/emails/` automatically - drop a new `.html` file in that folder and it appears in the dropdown without any schema change.
  - **Duplicate Prevention**: tracks execution timestamps so emails are never sent twice for the same trigger window.
- **Rich HTML Email Template**:
  - Direct clickable links to Frappe ToDo records and reference documents.
  - Color-coded badges for task **Status** (Overdue, Open, Completed) and **Priority** (Urgent, High, Medium, Low).
  - Clean table layout with task descriptions, assigners, due dates, and references.

---

## Installation

Install this app into your Frappe Bench:

```bash
cd /path/to/frappe-bench

# Fetch app from repository
bench get-app https://github.com/Tariquaf/notification_templates.git --branch version-16

# Install app on your site
bench --site [your-site-name] install-app notification_templates

# Run migrations
bench --site [your-site-name] migrate
```

---

## Configuration & Usage

1. Open your Frappe / ERPNext Desk.
2. Search for **Custom Notification Templates** in the awesome bar.
3. Configure the **Overdue Task Notification** section:
   - Check **Enable Overdue Notification** to activate.
   - **Overdue Send Time (Daily)**: set an exact time (e.g. `10:00`) to get one overdue email per day. Leave empty to disable this trigger.
   - **Repeat Interval (HH:MM)**: set how often to repeat (e.g. `01:00` = every 1 hour). Leave empty to disable this trigger.
   - **Overdue Email Template**: select which custom template to use (options are populated automatically from `templates/emails/`).
4. Configure the **Open Task Notification (Daily)** section:
   - Check **Enable Open Task Notification** to activate.
   - **Send Time**: set the exact time for the daily report (e.g. `09:00:00` for 9:00 AM).
   - **Daily Todo Email Template**: select which custom template to use.
5. Click **Save**.

### Adding a custom template

Drop a new HTML template into `notification_templates/templates/emails/`, e.g. `custom_template_1.html`. After a browser refresh it will automatically appear as an option in the **Overdue Email Template** and **Daily Todo Email Template** dropdowns. The template name shown is the file name without the `.html` extension.

Your custom template receives these variables from the scheduler:

| Variable | Description |
| :--- | :--- |
| `todo_list` | List of ToDo dicts (`name`, `description`, `status`, `priority`, `allocated_to`, `assigned_by`, `date`, `reference_type`, `reference_name`, ...) |
| `report_title` | Heading text (e.g. "Daily TODO Report") |
| `report_color` | Banner background color (`#eef6ff` daily / `#fff3f3` overdue) |

---

## Scheduler Events

The app hooks into the Frappe background scheduler. Both functions run every minute and internally decide whether a send is due, so configured times are never missed:

| Event / Cron | Function | Description |
| :--- | :--- | :--- |
| `* * * * *` (Every minute) | `send_daily_todo_report` | Checks if the configured daily send time has arrived; sends once per day. |
| `* * * * *` (Every minute) | `send_overdue_todo_report` | Checks fixed send time and repeat interval; sends when either is due. |

---

## Development & Contributing

This app uses `pre-commit` for formatting and code quality checks.

```bash
cd apps/notification_templates
pre-commit install
```

Configured linters & tools:
- `ruff`
- `eslint`
- `prettier`
- `pyupgrade`

---

## Contributors

- [MaAn-41](https://github.com/MaAn-41)

---

## License

[MIT](LICENSE)
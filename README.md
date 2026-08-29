# Notification Templates

A Frappe / ERPNext application for sending scheduled and custom email notifications and task summaries, including daily ToDo reports and overdue task alerts.

---

## 🚀 Features

- 📬 **Daily ToDo Digest**: Automatically aggregates all open ToDo items assigned to each user and dispatches a clean, formatted email summary once a day.
- ⏰ **Overdue Tasks Alert**: Periodically checks for overdue tasks and sends alert notifications to assignees.
- ⚙️ **Configurable Settings DocType (`Todo Notification Setting`)**:
  - **Enable / Disable**: Easily turn automated notifications on or off.
  - **Send Time**: Configure the exact time of day for the daily report to be sent.
  - **Template Selection**: Choose and customize email templates.
  - **Duplicate Prevention**: Tracks execution timestamps to ensure users receive reports on time without duplicates.
- 🎨 **Rich HTML Email Template**:
  - Direct clickable links to Frappe ToDo records and reference documents.
  - Color-coded badges for task **Status** (Overdue, Open, Completed) and **Priority** (Urgent, High, Medium, Low).
  - Clean table layout with task descriptions, assigners, due dates, and tags.

---

## 📦 Installation

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

## 🛠️ Configuration & Usage

1. Open your Frappe / ERPNext Desk.
2. Search for **Todo Notification Setting** in the awesome bar.
3. Configure the settings:
   - Check **Enabled** to activate notifications.
   - Set your preferred **Send Time** (e.g. `09:00:00` for 9:00 AM).
   - Select the **Email Template** (default: `Todo`).
4. Click **Save**.

---

## ⏱️ Scheduler Events

The app hooks into the Frappe background scheduler:

| Event / Cron | Function | Description |
| :--- | :--- | :--- |
| `*/5 * * * *` (Every 5 mins) | `send_daily_todo_report` | Checks if the configured daily send time has arrived and dispatches daily reports. |
| `0 */2 * * *` (Every 2 hours) | `send_overdue_todo_report` | Scans for overdue tasks and dispatches overdue email alerts. |

---

## 👩‍💻 Development & Contributing

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

## 📄 License

[MIT](LICENSE)

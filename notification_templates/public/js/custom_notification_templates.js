frappe.ui.form.on("Custom Notification Templates", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Overdue Report"), sendNowOverdueReport, __("Send Now"));
		frm.add_custom_button(__("Open Task Report"), sendOpenTaskReport, __("Send Now"));
	},
});

function sendNowOverdueReport() {
	frappe.confirm(__("Send overdue task report now?"), () => {
		frappe.call({
			method: "notification_templates.tasks.send_now_overdue_report",
			freeze: true,
			freeze_message: __("Sending overdue report..."),
			callback(response) {
				if (response.message) {
					frappe.msgprint({
						title: __("Success"),
						indicator: "green",
						message: response.message,
					});
				}
			},
		});
	});
}

function sendOpenTaskReport() {
	frappe.confirm(__("Send daily open task report now?"), () => {
		frappe.call({
			method: "notification_templates.tasks.send_now_daily_report",
			freeze: true,
			freeze_message: __("Sending report..."),
			callback(response) {
				if (response.message) {
					frappe.msgprint({
						title: __("Success"),
						indicator: "green",
						message: response.message,
					});
				}
			},
		});
	});
}

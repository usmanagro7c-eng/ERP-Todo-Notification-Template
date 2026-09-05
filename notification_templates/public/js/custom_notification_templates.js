frappe.ui.form.on("Custom Notification Templates", {
	refresh(frm) {
		setupSectionToggles(frm);

		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Overdue Report"), sendNowOverdueReport, __("Send Now"));
		frm.add_custom_button(__("Open Task Report"), sendOpenTaskReport, __("Send Now"));
	},
});

function setupSectionToggles(frm) {
	const formWrapper = $(frm.wrapper);

	["section_overdue", "section_open_task"].forEach((fieldname) => {
		const section = formWrapper.find(`[data-fieldname="${fieldname}"]`);
		const header = section.find(".section-head");
		if (!header.find(".notification-section-arrow").length) {
			header.append(
				$('<span class="notification-section-arrow">&gt;</span>').css({
					display: "inline-block",
					"font-size": "18px",
					"font-weight": "700",
					"margin-left": "8px",
				})
			);
		}

		header.off("click.notificationTemplates").on("click.notificationTemplates", function (event) {
			event.preventDefault();
			section.find(".section-body").stop(true, true).slideToggle(150);
			section.toggleClass("collapsed");
		});
	});

	const startField = formWrapper.find('.frappe-control[data-fieldname="overdue_start_time"]');
	const endField = formWrapper.find('.frappe-control[data-fieldname="overdue_end_time"]');
	if (startField.length && endField.length) {
		const verticalOffset = startField.offset().top - endField.offset().top;
		endField.css("margin-top", `${verticalOffset}px`);
	}
}

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

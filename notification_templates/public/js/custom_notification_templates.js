frappe.ui.form.on("Custom Notification Templates", {
	refresh: function (frm) {
		frappe.call({
			method: "notification_templates.api.get_available_templates",
			callback: function (r) {
				if (r.message && r.message.length) {
					let options = r.message.join("\n");
					for (let field of ["overdue_template", "daily_todo_template"]) {
						let df = frm.get_field(field);
						if (df) {
							df.df.options = options;
							df.refresh_input();
						}
					}
				}
			},
		});
	},
});

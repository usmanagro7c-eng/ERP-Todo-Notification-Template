import os

import frappe


@frappe.whitelist()
def get_available_templates():
	templates_dir = os.path.join(
		os.path.dirname(os.path.abspath(__file__)), "templates", "emails"
	)
	templates = []
	if os.path.isdir(templates_dir):
		for file in sorted(os.listdir(templates_dir)):
			if file.endswith(".html"):
				templates.append(file[:-5])
	return templates

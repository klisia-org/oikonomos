// Copyright (c) 2026, Klisia / SeminaryERP and contributors
// For license information, please see license.txt

// Customer is an ERPNext doctype, so this form customization lives in oikonomos.
// Restrict the Gender link to the seminary's enabled genders (custom_enabled).
frappe.ui.form.on("Customer", {
	onload(frm) {
		frm.set_query("gender", () => ({
			filters: { custom_enabled: 1 },
		}));
	},
});

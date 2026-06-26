// Copyright (c) 2026, Klisia / SeminaryERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Program Fees", {
	refresh(frm) {
		// Only fee categories whose trigger event is not "On Use" are billable
		// against a program up front; mirror the server-side link_filters.
		frm.set_query("pgm_feecategory", function () {
			return { filters: { docstatus: 1 } };
		});
	},
});

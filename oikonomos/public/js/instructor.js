// Copyright (c) 2026, Klisia / SeminaryERP and contributors
// For license information, please see license.txt

// The oikonomos-owned Supplier link on Instructor: honoraria for volunteers are
// billed through Purchase Invoice, so offer to create the Supplier.
frappe.ui.form.on("Instructor", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.instructor_type === "Volunteer" && !frm.doc.supplier) {
			frm.add_custom_button(__("Create Supplier"), function() {
				frappe.call({
					method: "oikonomos.financial.instructor.create_supplier",
					args: { instructor: frm.doc.name },
				}).then(() => frm.reload_doc());
			}, __("Actions"));
		}
	},
});

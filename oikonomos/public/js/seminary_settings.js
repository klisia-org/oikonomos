// Copyright (c) 2026, Klisia / SeminaryERP and contributors
// For license information, please see license.txt

// Constrain the oikonomos-owned account/cost-center link fields on Seminary
// Settings to valid, postable targets — so billing can't be pointed at a group
// node or the wrong account type (e.g. a non-Receivable "Debit To" account).
frappe.ui.form.on("Seminary Settings", {
	setup(frm) {
		frm.set_query("cost_center", () => ({
			filters: { is_group: 0 },
		}));
		frm.set_query("scholarship_cc", () => ({
			filters: { is_group: 0 },
		}));
		frm.set_query("receivable_account", () => ({
			filters: { is_group: 0, account_type: "Receivable", disabled: 0 },
		}));
		frm.set_query("income_account", () => ({
			filters: { is_group: 0, root_type: "Income", disabled: 0 },
		}));
	},
});

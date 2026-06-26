// Copyright (c) 2026, Klisia / SeminaryERP and contributors
// For license information, please see license.txt

// "Event to charge" (pgm_feeevent) is derived read-only from the selected Fee
// Category (fetch_from pgm_feecategory.fc_event). Trigger Fee Events records are
// referenced by hard-coded name throughout the billing code, so the event is
// never hand-picked here — pick the Fee Category and the event follows.
frappe.ui.form.on("Program Fees", {});

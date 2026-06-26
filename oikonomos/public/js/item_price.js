// Copyright (c) 2026, Klisia / SeminaryERP and contributors
// For license information, please see license.txt

// Item Price is an ERPNext doctype, so this form customization lives in
// oikonomos. Default the UOM to the item's stock UOM when an item is chosen.
frappe.ui.form.on("Item Price", {
	item_code(frm) {
		if (!frm.doc.item_code) return;
		frappe.db.get_value("Item", frm.doc.item_code, "stock_uom").then((r) => {
			const stock_uom = r && r.message && r.message.stock_uom;
			if (stock_uom) frm.set_value("uom", stock_uom);
		});
	},
});

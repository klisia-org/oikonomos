# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Re-own the financial reports relocated from seminary to oikonomos.

Frappe preserves an existing Report record's `module` on re-import, so on sites
that already had these reports under the Seminary module the records keep
pointing there — and Script Reports then fail to find their .py (now under
oikonomos). This patch updates the module so the code resolves to the bridge.
Fresh installs import them correctly and this is a harmless no-op there.
"""

import frappe

RELOCATED_REPORTS = [
    "CEI Marked Paid Without Payment",
    "Scholarship Budget vs Given",
    "Scholarship Sales Invoices",
    "Students At Scholarship Risk",
    "Unpaid Instructor Log",
    "Active Scholarships",
    "Active Scholarships (All Types)",
    "All Active Scholarships",
    "Count of All Active Scholarships",
    "Student PE Total Balance",
]


def execute():
    for name in RELOCATED_REPORTS:
        if frappe.db.exists("Report", name):
            frappe.db.set_value("Report", name, "module", "Oikonomos", update_modified=False)
    frappe.db.commit()

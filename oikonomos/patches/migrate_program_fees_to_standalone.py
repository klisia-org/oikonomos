# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Program Fees became a standalone oikonomos doctype (was a child table on the
seminary Program doctype, `Program.pgm_pgmfees`). This backfills the new
`program` Link from the legacy child `parent` so existing fee configurations
survive the inversion. Idempotent."""

import frappe


def execute():
    if not frappe.db.has_column("Program Fees", "program"):
        return
    frappe.db.sql(
        """
        UPDATE `tabProgram Fees`
        SET program = parent
        WHERE (program IS NULL OR program = '')
          AND parent IS NOT NULL AND parent != ''
        """
    )
    frappe.db.commit()

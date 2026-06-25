# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Culminating Project Extension billing (oikonomos side effects).

Relocated from the seminary Culminating Project Extension controller. Oikonomos
subscribes to the doctype's on_submit / on_cancel via doc_events, so when
oikonomos is absent the extension simply submits with no charge (free).

Billing only: no Program Enrollment Course row is created, so the extension never
affects credits / grade / GPA / transcript (ADR 024). Idempotent via `invoiced`.
"""

import frappe
from frappe import _

from seminary.seminary.billing import create_extension_invoices


def on_submit(doc, method=None):
    """Charge the extension fee to the enrollment's payers. The fee is whatever
    Fee Category carries the 'Culminating Project Extension' trigger."""
    if doc.invoiced:
        return
    program_enrollment = doc.program_enrollment or frappe.db.get_value(
        "Culminating Project", doc.culminating_project, "program_enrollment"
    )
    if not doc.program_enrollment and program_enrollment:
        doc.db_set("program_enrollment", program_enrollment)
    summary = _("Culminating Project Extension: {0} ({1})").format(
        doc.culminating_project, doc.academic_term
    )
    invoices = create_extension_invoices(program_enrollment, doc.student, summary)
    doc.db_set("sales_invoices", "\n".join(invoices))
    doc.db_set("invoiced", 1)


def on_cancel(doc, method=None):
    """Cancel the Sales Invoices this extension created."""
    for name in (doc.sales_invoices or "").splitlines():
        name = name.strip()
        if not name:
            continue
        if frappe.db.get_value("Sales Invoice", name, "docstatus") != 1:
            continue
        invoice = frappe.get_doc("Sales Invoice", name)
        invoice.flags.ignore_permissions = True
        invoice.cancel()

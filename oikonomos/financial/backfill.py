# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Billing-identity backfill for the Frappe-only → integrated transition.

A seminary can run Frappe-only (no oikonomos) and adopt billing later. When that
happens, the academic records that already exist were created without the
oikonomos seams firing, so they lack the billing scaffolding that a fresh
integrated install would have:

- Students have no Customer (normally created on Student.on_update).
- Program Enrollments have no payer rows / Payers Fee Category PE (normally built
  on PE before_submit by prepare_enrollment_payers → get_payers).

Without those, the billing engine reads an empty payer snapshot and produces no
invoice even though Program Fees are configured. This backfill creates the
missing Customers and payer rows. It is idempotent (skips records that already
have them) and creates NO invoices — invoicing stays an explicit action
(CEI submit / the Generate Sales Invoice button). Runs on oikonomos install; for
a fresh install with no academic data it is a no-op.
"""

import frappe


def backfill_billing_identities():
    _backfill_student_customers()
    _backfill_enrollment_payers()
    frappe.db.commit()


def _backfill_student_customers():
    """Create the billing Customer for every Student that lacks one, reusing the
    same path as Student.on_update so the Customer/Contact/Person links match a
    natively-created student."""
    from oikonomos.financial.customer_person import on_student_update

    names = frappe.get_all(
        "Student", filters={"customer": ("is", "not set")}, pluck="name"
    )
    for name in names:
        try:
            on_student_update(frappe.get_doc("Student", name))
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), f"oikonomos backfill customer {name}"
            )


def _backfill_enrollment_payers():
    """Build the payer snapshot (Payers Fee Category PE + rows) for every active
    submitted Program Enrollment that has none, from the program's current
    Program Fees — the same builder used at enrollment time. Runs after customer
    backfill so the payer (the student's Customer) resolves."""
    from oikonomos.financial.payers import get_payers

    pes = frappe.get_all(
        "Program Enrollment",
        filters={"docstatus": 1, "pgmenrol_active": 1},
        pluck="name",
    )
    for pe_name in pes:
        if frappe.db.exists("Payers Fee Category PE", {"pf_pe": pe_name}):
            continue
        try:
            get_payers(frappe.get_doc("Program Enrollment", pe_name), None)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(), f"oikonomos backfill payers {pe_name}"
            )

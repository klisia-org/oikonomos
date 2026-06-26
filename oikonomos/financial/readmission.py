# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Readmission fee policy + charging (oikonomos side).

A readmission fee is billed when a student returns from a Leave of Absence. The
fee is a Fee Category — an ERPNext-backed billing doctype — so both the policy
(whether to charge, and which Fee Category) and the charging live in the bridge.

Owns:
- Custom fields on seminary's Program Level: charges_readmission_fee +
  readmission_fee_category (the policy), created on install/migrate.
- charge_readmission(): read the policy off the enrollment's Program Level and
  raise the readmission invoice via the shared billing pipeline.

Seminary's status spine calls this through the FinancialBackend seam
(`charge_readmission`) on return from leave; with oikonomos absent the null
backend no-ops and readmission is free.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Program Level": [
        {
            "fieldname": "column_break_readmission",
            "fieldtype": "Column Break",
            "insert_after": "suspend_nay",
        },
        {
            "fieldname": "charges_readmission_fee",
            "fieldtype": "Check",
            "label": "Charges Readmission Fee",
            "insert_after": "column_break_readmission",
            "default": "0",
            "allow_on_submit": 1,
            "description": "Charge a readmission fee when a student returns from "
            "leave. The fee is the linked Fee Category, billed through the normal "
            "pipeline. It is NOT affected by the date threshold for billing "
            "suspension.",
        },
        {
            "fieldname": "readmission_fee_category",
            "fieldtype": "Link",
            "label": "Readmission Fee Category",
            "options": "Fee Category",
            "insert_after": "charges_readmission_fee",
            "allow_on_submit": 1,
            "depends_on": "eval:doc.charges_readmission_fee",
        },
    ],
}


def setup_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)


def charge_readmission(pe_name, effective_date):
    """Bill the readmission fee for an enrollment returning from leave, when its
    Program Level is configured to charge one. Idempotency is owned by
    generate_readmission_invoice (per PE/date/payer tag)."""
    program = frappe.db.get_value("Program Enrollment", pe_name, "program")
    if not program:
        return
    program_level = frappe.db.get_value("Program", program, "program_level")
    if not program_level:
        return
    policy = frappe.db.get_value(
        "Program Level",
        program_level,
        ["charges_readmission_fee", "readmission_fee_category"],
        as_dict=True,
    )
    if not policy or not policy.charges_readmission_fee:
        return
    if not policy.readmission_fee_category:
        return

    from oikonomos.financial.invoicing import generate_readmission_invoice

    generate_readmission_invoice(
        pe_name, policy.readmission_fee_category, effective_date
    )

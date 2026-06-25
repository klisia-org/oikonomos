# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Oikonomos install / migrate setup.

Oikonomos owns every customization on ERPNext doctypes (Sales Invoice, ...).
The cosmetic property setters and the export-shaped custom fields (custom_student,
exempt_from_sales_tax) sync from oikonomos/oikonomos/custom/ automatically on
migrate. The link/marker fields below are created here via create_custom_fields
(idempotent, runs every migrate) so they always exist when oikonomos is installed
— and never get created by seminary, which has no Sales Invoice on a Frappe-only
install.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    ensure_custom_fields()


def after_migrate():
    ensure_custom_fields()


# Seminary's link/marker fields on Sales Invoice. custom_student is created by
# the custom/ sync and is the insert_after anchor for custom_cei, so it exists
# before this runs on migrate.
SALES_INVOICE_CUSTOM_FIELDS = {
    "Sales Invoice": [
        {
            "fieldname": "custom_cei",
            "fieldtype": "Link",
            "label": "Course Enrollment Individual",
            "options": "Course Enrollment Individual",
            "insert_after": "custom_student",
            "read_only": 1,
        },
        {
            "fieldname": "custom_graduation_request",
            "fieldtype": "Link",
            "label": "Graduation Request",
            "options": "Graduation Request",
            "insert_after": "custom_cei",
            "read_only": 1,
        },
        {
            "fieldname": "seminary_trigger",
            "fieldtype": "Data",
            "label": "Seminary Trigger",
            "insert_after": "posting_date",
            "read_only": 1,
            "hidden": 1,
        },
        {
            "fieldname": "seminary_summary",
            "fieldtype": "Data",
            "label": "Summary",
            "insert_after": "seminary_trigger",
            "read_only": 1,
        },
    ],
}


def ensure_custom_fields():
    create_custom_fields(SALES_INVOICE_CUSTOM_FIELDS, ignore_validate=True)
    # Instructor payroll fields/components — only when HRMS is on (no-op otherwise).
    from oikonomos.financial.salary_slip import provision_payroll_if_enabled

    provision_payroll_if_enabled()
    frappe.db.commit()

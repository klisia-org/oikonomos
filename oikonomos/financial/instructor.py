# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""How an Instructor is paid (oikonomos side).

Seminary's Instructor carries ``instructor_type`` (Volunteer / Salaried /
Per-Course). The ERPNext records behind it — an Employee for payroll, a Supplier
for honoraria via Purchase Invoice — are ERPNext doctypes, so their links, the
check that a paid instructor has an Employee, and the "Create Supplier" action
live in the bridge.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
    "Instructor": [
        {
            "fieldname": "employee",
            "fieldtype": "Link",
            "label": "Employee",
            "options": "Employee",
            "insert_after": "instructor_type",
            "depends_on": 'eval:doc.instructor_type && doc.instructor_type != "Volunteer"',
        },
        {
            "fieldname": "column_break_hr",
            "fieldtype": "Column Break",
            "insert_after": "employee",
        },
        {
            "fieldname": "supplier",
            "fieldtype": "Link",
            "label": "Supplier",
            "options": "Supplier",
            "insert_after": "column_break_hr",
            "depends_on": 'eval:doc.instructor_type == "Volunteer"',
            "description": "Used to bill honoraria or love offerings via Purchase "
            'Invoice. Click "Create Supplier" in the form menu to auto-create.',
        },
    ],
}


def setup_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)


def validate(doc, method=None):
    """Instructor validate hook: a paid instructor needs an Employee for payroll."""
    if not doc.instructor_type or doc.instructor_type == "Volunteer":
        return
    if not doc.get("employee"):
        frappe.throw(
            _("Instructor Type {0} requires an Employee link for payroll.").format(
                doc.instructor_type
            )
        )


@frappe.whitelist()
def create_supplier(instructor, supplier_group=None):
    """Create a Supplier from this Instructor and link it back.

    Used for Volunteer / honorarium billing via Purchase Invoice.
    """
    # Students read instructor profiles, and this inserts a Supplier with
    # ignore_permissions -- accounting master data. Write on the Instructor is
    # not the bar either: an instructor holds if_owner write on their own
    # record, and creating one's own payee is not a self-service action.
    frappe.only_for(
        (
            "Seminary Manager",
            "Program Chair",
            "System Manager",
            "Accounts Manager",
            "Accounts User",
        )
    )
    doc = frappe.get_doc("Instructor", instructor)
    if doc.supplier:
        frappe.msgprint(
            _("Supplier {0} is already linked to this Instructor.").format(doc.supplier)
        )
        return doc.supplier

    group = supplier_group or (
        "Instructor"
        if frappe.db.exists("Supplier Group", "Instructor")
        else frappe.db.get_single_value("Buying Settings", "supplier_group")
    )

    supplier = frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": doc.instructor_name,
            "supplier_group": group,
            "supplier_type": "Individual",
            "email_id": doc.prof_email,
            "mobile_no": doc.phone_message,
        }
    ).insert(ignore_permissions=True)

    doc.db_set("supplier", supplier.name)
    frappe.msgprint(
        _("Supplier {0} created and linked.").format(supplier.name), alert=True
    )
    return supplier.name

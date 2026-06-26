# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Customer billing identity + Customer<->Person link (oikonomos side).

Customer is an ERPNext doctype, so its links into seminary's academic/Person
spine belong in the bridge. This mirrors seminary's own Donor<->Person soft
integration (seminary.seminary.integrations.giving) — but inverted: oikonomos is
the optional app, so IT owns the Customer integration and reaches into seminary's
Student/Person via custom fields + doc_events. Seminary never references Customer.

Owns:
- Custom fields: Customer.person, Person.customer (the link), Student.customer +
  Student.customer_group (billing identity), created on install/migrate.
- Customer lifecycle: create/update the Student's Customer + Contact on
  Student.on_update (relocated from the Student controller).
- link_customer(): first-link-wins mirror between Person.customer and
  Customer.person.

With oikonomos absent, none of this exists and Students are purely academic.
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Customer": [
        {
            "fieldname": "person",
            "fieldtype": "Link",
            "label": "Person",
            "options": "Person",
            "insert_after": "customer_group",
            "read_only": 1,
            "search_index": 1,
        }
    ],
    "Person": [
        {
            "fieldname": "customer",
            "fieldtype": "Link",
            "label": "Customer",
            "options": "Customer",
            "insert_after": "column_break_links",
            "read_only": 1,
            "search_index": 1,
        }
    ],
    "Student": [
        {
            "fieldname": "customer",
            "fieldtype": "Link",
            "label": "Customer",
            "options": "Customer",
            "insert_after": "customer_details_section",
            "read_only": 1,
        },
        {
            "fieldname": "customer_group",
            "fieldtype": "Link",
            "label": "Customer Group",
            "options": "Customer Group",
            "insert_after": "column_break_rgpi",
        },
    ],
    "Student Applicant": [
        {
            "fieldname": "customer",
            "fieldtype": "Link",
            "label": "Customer",
            "options": "Customer",
            "insert_after": "term_admission",
            "read_only": 1,
            "description": "The Customer record used to bill the Application fee. "
            "Auto-created on submit if blank, using the applicant's name and "
            "Customer Group.",
        },
        {
            "fieldname": "customer_group",
            "fieldtype": "Link",
            "label": "Customer Group",
            "options": "Customer Group",
            "insert_after": "customer",
            "default": "Individual",
            "description": "Customer Group used to bill the Application fee. "
            "Drives which Price List is applied.",
        },
    ],
    # Student Contacts is a pure-academic references/emergency-contacts child
    # table; seminary keeps it textual (a typed Connection Name). When ERPNext is
    # present, restore the original behaviour: each reference links to a Customer
    # and the name auto-fetches read-only from it (see PROPERTY_SETTERS).
    "Student Contacts": [
        {
            "fieldname": "contact",
            "fieldtype": "Link",
            "label": "Connected to",
            "options": "Customer",
            "insert_after": "",
            "in_list_view": 1,
            "reqd": 1,
        },
    ],
}


# Property setters restoring the integrated Student Contacts behaviour: with the
# Customer link present, the Connection Name is fetched from it and locked.
PROPERTY_SETTERS = [
    {
        "doctype_or_field": "DocField",
        "doctype": "Student Contacts",
        "fieldname": "contact_name",
        "property": "fetch_from",
        "property_type": "Small Text",
        "value": "contact.customer_name",
    },
    {
        "doctype_or_field": "DocField",
        "doctype": "Student Contacts",
        "fieldname": "contact_name",
        "property": "read_only",
        "property_type": "Check",
        "value": "1",
    },
]


def setup_custom_fields():
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
    # Idempotent: Property Setter autoname is "{doc_type}-{field_name}-{property}",
    # so skip re-creating on every migrate.
    for ps in PROPERTY_SETTERS:
        name = "{0}-{1}-{2}".format(ps["doctype"], ps["fieldname"], ps["property"])
        if not frappe.db.exists("Property Setter", name):
            frappe.make_property_setter(ps, is_system_generated=True)


# ---------------------------------------------------------------------------
# Person <-> Customer link
# ---------------------------------------------------------------------------


def link_customer(person_name, customer):
    """Mirror Person.customer <-> Customer.person, first-link-wins on each side
    (never overwrites an existing link). Guarded so it is inert before the custom
    fields are synced."""
    if not customer or not person_name:
        return
    if frappe.db.has_column("Person", "customer") and not frappe.db.get_value(
        "Person", person_name, "customer"
    ):
        frappe.db.set_value(
            "Person", person_name, "customer", customer, update_modified=False
        )
    if frappe.db.has_column("Customer", "person") and not frappe.db.get_value(
        "Customer", customer, "person"
    ):
        frappe.db.set_value(
            "Customer", customer, "person", person_name, update_modified=False
        )


# ---------------------------------------------------------------------------
# Student -> Customer lifecycle (relocated from the Student controller)
# ---------------------------------------------------------------------------


def on_student_update(doc, method=None):
    """Student on_update: ensure the Student's Customer billing identity and the
    Person<->Customer link."""
    _set_customer_group(doc)
    if doc.get("customer"):
        _update_linked_customer(doc)
    else:
        _create_customer(doc)
    customer = doc.get("customer") or frappe.db.get_value(
        "Student", doc.name, "customer"
    )
    if doc.get("person"):
        link_customer(doc.person, customer)


def _set_customer_group(doc):
    if frappe.flags.in_demo_install:
        return
    if not doc.get("customer_group"):
        doc.customer_group = _("Student")
        frappe.db.set_value("Student", doc.name, "customer_group", _("Student"))


def _create_customer(doc):
    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": doc.student_name,
            "customer_group": doc.get("customer_group")
            or frappe.db.get_single_value("Selling Settings", "customer_group"),
            "customer_type": "Individual",
            "image": doc.image,
        }
    ).insert()

    frappe.db.set_value("Student", doc.name, "customer", customer.name)
    doc.customer = customer.name
    frappe.msgprint(
        _("Customer {0} created and linked to Student").format(customer.name),
        alert=True,
    )
    _create_contact(doc, customer.name)


def _update_linked_customer(doc):
    customer = frappe.get_doc("Customer", doc.customer)
    if doc.get("customer_group"):
        customer.customer_group = doc.customer_group
    customer.customer_name = doc.student_name
    customer.image = doc.image
    customer.save()
    frappe.msgprint(_("Customer {0} updated").format(customer.name), alert=True)


def _create_contact(doc, customer_name):
    contact = frappe.get_doc(
        {
            "doctype": "Contact",
            "first_name": doc.first_name,
            "last_name": doc.last_name,
            "is_primary_contact": 1,
            "email_ids": [{"email_id": doc.student_email_id, "is_primary": 1}],
            "links": [{"link_doctype": "Customer", "link_name": customer_name}],
        }
    )
    contact.insert(ignore_permissions=True)
    frappe.msgprint(
        _("Contact {0} created and linked to Customer").format(contact.name),
        alert=True,
    )

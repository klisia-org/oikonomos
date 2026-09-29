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
  Customer.person, and the on_trash handlers that drop the opposite half so
  either side can actually be deleted (ADR 042 addendum, 2026-09-22).

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
    # A record name, not a label: install seeds the untranslated "Student", and
    # _() here resolved to e.g. "Estudante" on a pt site -> LinkValidationError.
    if not doc.get("customer_group") and frappe.db.exists("Customer Group", "Student"):
        doc.customer_group = "Student"
        frappe.db.set_value("Student", doc.name, "customer_group", "Student")


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


def on_customer_update(doc, method=None):
    """Clear a stale Person.customer when a Customer is re-pointed to a different
    Person. Mirrors seminary's on_donor_update guard; cheap no-op on every other
    Customer save."""
    if not frappe.db.has_column("Person", "customer"):
        return
    before = doc.get_doc_before_save()
    old_person = before.get("person") if before else None
    if not old_person or old_person == doc.get("person"):
        return
    if frappe.db.get_value("Person", old_person, "customer") == doc.name:
        frappe.db.set_value(
            "Person", old_person, "customer", None, update_modified=False
        )
    if doc.get("person"):
        link_customer(doc.person, doc.name)


def on_customer_trash(doc, method=None):
    """Drop the Person.customer half of the mirror when its Customer is deleted.

    Frappe runs on_trash before check_if_doc_is_linked, so clearing here is what
    lets the delete through at all -- the field is read-only, leaving no manual
    escape. Reverse lookup rather than doc.person: first-link-wins applies to each
    half independently, so a Person may point here while this Customer points
    elsewhere or nowhere. Student.customer / Student Applicant.customer are
    billing identity, not a mirror, and deliberately stay put -- a Customer owned
    by a Student remains undeletable (ADR 042 addendum, 2026-09-22)."""
    if not frappe.db.has_column("Person", "customer"):
        return
    stale = frappe.get_all("Person", filters={"customer": doc.name}, pluck="name")
    for person in stale:
        frappe.db.set_value("Person", person, "customer", None, update_modified=False)


def on_person_trash(doc, method=None):
    """Drop the Customer.person half of the mirror when its Person is deleted.
    The Customer itself survives: it is a billing identity ERPNext owns, and
    seminary's academic spine going away is no reason to lose the ledger."""
    if not frappe.db.has_column("Customer", "person"):
        return
    stale = frappe.get_all("Customer", filters={"person": doc.name}, pluck="name")
    for customer in stale:
        frappe.db.set_value("Customer", customer, "person", None, update_modified=False)

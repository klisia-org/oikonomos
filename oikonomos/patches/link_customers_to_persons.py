"""Backfill the Customer.person reverse link (ADR 042 addendum).

Creates the custom field if missing, then walks Persons with a customer and
person-linked Students/Applicants with a customer, mirroring the link both
ways. Idempotent (first link wins, never overwrites).

Owned by oikonomos: Customer and the Person<->Customer linker live in the bridge,
so this runs only where oikonomos is installed.
"""

import frappe

from oikonomos.financial.customer_person import link_customer, setup_custom_fields


def execute():
    setup_custom_fields()

    linked = 0
    for p in frappe.get_all(
        "Person", filters={"customer": ("is", "set")}, fields=["name", "customer"]
    ):
        if not frappe.db.get_value("Customer", p.customer, "person"):
            frappe.db.set_value(
                "Customer", p.customer, "person", p.name, update_modified=False
            )
            linked += 1

    for doctype in ("Student", "Student Applicant"):
        rows = frappe.get_all(
            doctype,
            filters={"person": ("is", "set"), "customer": ("is", "set")},
            fields=["person", "customer"],
        )
        for row in rows:
            link_customer(row.person, row.customer)

    frappe.db.commit()
    print(f"Customer.person backfilled ({linked} direct Person links).")

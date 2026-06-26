# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Create-if-missing seed of billing config relocated from seminary fixtures.

These (fee Items, Payment Terms) are deliberately SEEDED, not fixtured: a
fixture re-import on every migrate would clobber a seminary's customizations
(fee item names/rates, payment terms). This matches seminary's own seed-once
pattern for Fee Category / Grading Scale. Runs on oikonomos install + migrate.
"""

import json
import os

import frappe

_SEED_DIR = os.path.join(os.path.dirname(__file__), "seed_data")

# Order matters: payment terms before items (items may reference them).
_SEEDS = [
    ("Payment Term", "payment_term.json"),
    ("Payment Terms Template", "payment_terms_template.json"),
    ("Item", "item.json"),
]


def seed_billing_config():
    company, income_account, price_list = _resolve_company_context()
    for doctype, fname in _SEEDS:
        path = os.path.join(_SEED_DIR, fname)
        if not os.path.exists(path):
            continue
        for rec in json.load(open(path)):
            name = rec.get("name") or rec.get("item_code")
            if name and frappe.db.exists(doctype, name):
                continue  # never overwrite a seminary's edits
            if doctype == "Item":
                # The seed file carries placeholder company/account links
                # ("ToBeReplaced"). ERPNext validates these links *during*
                # insert, so they must be resolved to the site's real company
                # BEFORE inserting — otherwise the Item never gets created and
                # the post-insert fixup has nothing to fix.
                _resolve_item_placeholders(rec, company, income_account, price_list)
            try:
                doc = frappe.get_doc(rec)
                doc.flags.ignore_permissions = True
                doc.insert()
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(), f"oikonomos seed {doctype} {name}"
                )
    _update_item_company_defaults()
    _seed_fee_categories()
    frappe.db.commit()


def _seed_fee_categories():
    """Seed the starter Fee Categories (create-only-if-missing). Relocated from
    seminary install.py — Fee Category is an oikonomos doctype.

    NOT fixtures: Fee Category.validate_audit() cross-checks is_credit against
    Seminary Settings (auditcredit / allow_audit), so a fixture re-import on
    migrate would re-validate shipped rows and throw once a seminary flips the
    setting or edits a category. The Audit Fee is seeded flat (is_credit=0) to
    match the default auditcredit=0. Each row needs its Item + Payment Terms
    Template (seeded just above); rows whose deps aren't present yet are skipped
    and filled in on the next migrate.
    """
    # category_name, fc_event, item, is_audit, is_credit
    defaults = [
        ("Program Admission Fee", "Program Enrollment", "Admission Fee", 0, 0),
        ("Registration fee (new term)", "New Academic Term", "Admission Fee", 0, 0),
        ("Credit hour", "Course Enrollment", "Credit hour", 0, 1),
        ("Audit Fee", "Course Enrollment", "Audit Flat Fee", 1, 0),
    ]
    payment_term_template = "For immediate payment"
    has_payment_term = frappe.db.exists(
        "Payment Terms Template", payment_term_template
    )
    for category_name, fc_event, item, is_audit, is_credit in defaults:
        if frappe.db.exists("Fee Category", category_name):
            continue
        if not frappe.db.exists("Item", item):
            continue
        frappe.get_doc(
            {
                "doctype": "Fee Category",
                "category_name": category_name,
                "feecategory_type": "Tuition",
                "fc_event": fc_event,
                "item": item,
                "is_audit": is_audit,
                "is_credit": is_credit,
                "payment_term_template": (
                    payment_term_template if has_payment_term else None
                ),
            }
        ).insert(ignore_permissions=True)


def _resolve_company_context():
    """Site's default company + its income account + an active selling price
    list. Oikonomos install requires a configured ERPNext company, so these
    exist by the time the seed runs."""
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    income_account = price_list = None
    if company:
        income_account = frappe.db.get_value("Company", company, "default_income_account")
        price_list = frappe.db.get_value(
            "Price List", {"selling": 1, "enabled": 1}, "name", order_by="creation asc"
        )
    return company, income_account, price_list


def _resolve_item_placeholders(rec, company, income_account, price_list):
    """Swap the seed file's placeholder links for the site's real company /
    income account / price list, and drop customer_items whose Customer does not
    yet exist — all so the Item passes ERPNext's link validation on insert."""
    for d in rec.get("item_defaults", []):
        if d.get("company") == "ToBeReplaced":
            d["company"] = company
        if d.get("income_account") == "Sales - ToBeReplaced":
            d["income_account"] = income_account
        if not d.get("default_price_list") and price_list:
            d["default_price_list"] = price_list
    if rec.get("customer_items"):
        rec["customer_items"] = [
            c
            for c in rec["customer_items"]
            if c.get("customer_name") and frappe.db.exists("Customer", c["customer_name"])
        ]


def _update_item_company_defaults():
    """Replace the placeholder 'ToBeReplaced' company on seeded Item Defaults
    with the site's default company (relocated from seminary install)."""
    default_company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not default_company:
        return
    if not frappe.db.sql(
        "SELECT name FROM `tabItem Default` WHERE company = 'ToBeReplaced'"
    ):
        return
    default_price_list = frappe.db.get_value(
        "Price List", {"selling": 1, "enabled": 1}, "name", order_by="creation asc"
    )
    default_income_account = frappe.db.get_value(
        "Company", {"company_name": default_company}, "default_income_account"
    )
    frappe.db.sql(
        """UPDATE `tabItem Default`
           SET company = %s, default_price_list = %s, income_account = %s
           WHERE company = 'ToBeReplaced'""",
        (default_company, default_price_list, default_income_account),
    )

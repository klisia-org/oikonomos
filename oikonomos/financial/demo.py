# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Integrated (billing-inclusive) demo data.

Seminary owns an academic-only demo (seminary.demo.demo_data). On a site with
oikonomos installed, seminary.demo.install_demo dispatches here instead (via the
`seminary_demo_installer` hook) so the demo also gets a billing catalog and the
enrollments/CEIs actually invoice.

We reuse seminary's academic step functions rather than copy them, and inject the
billing catalog (Fee Categories, Item Prices, Program Fees) right after the
programs are created — before enrollments, so their payer snapshots build, and
before CEIs, so they invoice. The fee schedule itself (which Fee Categories a
demo program charges, and the prices) is owned here, since Program Fees / Fee
Category / Item Price are oikonomos doctypes.
"""

import frappe

# The fee schedule every demo program charges. rate is the per-unit Item Price.
_DEMO_FEES = [
    {
        "fee_category": "Credit hour",
        "item": "Credit hour",
        "is_credit": 1,
        "event": "Course Enrollment",
        "rate": 250.0,
    },
    {
        "fee_category": "Program Admission Fee",
        "item": "Admission Fee",
        "is_credit": 0,
        "event": "Program Enrollment",
        "rate": 100.0,
    },
]


def install_demo_data():
    """Full demo: seminary's academic data + the oikonomos billing catalog,
    sequenced so enrollments build payer snapshots and CEIs invoice."""
    from seminary.demo import demo_data as d

    if frappe.db.exists("Academic Year", f"{d.DEMO_PREFIX}2024-25"):
        frappe.msgprint("Demo data already installed, skipping.", alert=True)
        return

    frappe.flags.in_demo_install = True
    try:
        d.create_academic_years()
        d.create_academic_terms()
        d.create_courses()
        d.create_programs()
        # Billing catalog must exist before enrollments (payers build from it)
        # and before CEIs (they invoice against it).
        seed_billing_catalog()
        d.create_users()
        d.create_students()
        d.create_instructor_categories()
        d.create_instructors()
        frappe.db.commit()
        d.create_program_enrollments()
        d.create_course_schedules()
        d.create_course_enrollments()
        frappe.db.set_single_value("Seminary Settings", "demo_data_installed", 1)
        frappe.db.commit()
        frappe.msgprint(
            "✅ Seminary demo data (with billing) installed successfully!", alert=True
        )
    except Exception:
        frappe.db.rollback()
        frappe.log_error("Oikonomos demo data installation failed")
        raise
    finally:
        frappe.flags.in_demo_install = False


def seed_billing_catalog():
    """Create the demo Fee Categories, their Item Prices, and a Program Fees row
    per demo program. Idempotent."""
    from seminary.demo.demo_data import DEMO_PREFIX

    price_list = frappe.db.get_value(
        "Price List", {"selling": 1, "enabled": 1}, "name", order_by="creation asc"
    )
    _ensure_student_price_list(price_list)

    for spec in _DEMO_FEES:
        _ensure_fee_category(spec)
        _ensure_item_price(spec["item"], price_list, spec["rate"])

    demo_programs = frappe.get_all(
        "Program", filters={"name": ("like", f"{DEMO_PREFIX}%")}, pluck="name"
    )
    for program in demo_programs:
        for spec in _DEMO_FEES:
            _ensure_program_fee(program, spec)


def _ensure_student_price_list(price_list):
    if not price_list:
        return
    if frappe.db.exists("Customer Group", "Student") and not frappe.db.get_value(
        "Customer Group", "Student", "default_price_list"
    ):
        frappe.db.set_value(
            "Customer Group", "Student", "default_price_list", price_list
        )


def _ensure_fee_category(spec):
    if frappe.db.exists("Fee Category", spec["fee_category"]):
        return
    fc = frappe.get_doc(
        {
            "doctype": "Fee Category",
            "category_name": spec["fee_category"],
            "item": spec["item"],
            "is_credit": spec["is_credit"],
            "feecategory_type": "Tuition",
            "payment_term_template": "For immediate payment",
            "fc_event": spec["event"],
        }
    )
    fc.flags.ignore_permissions = True
    fc.insert()
    if fc.meta.is_submittable:
        fc.submit()


def _ensure_item_price(item, price_list, rate):
    if not price_list or frappe.db.exists(
        "Item Price", {"item_code": item, "price_list": price_list}
    ):
        return
    ip = frappe.get_doc(
        {
            "doctype": "Item Price",
            "item_code": item,
            "price_list": price_list,
            "price_list_rate": rate,
            "selling": 1,
        }
    )
    ip.flags.ignore_permissions = True
    ip.insert()


def _ensure_program_fee(program, spec):
    if frappe.db.exists(
        "Program Fees", {"program": program, "pgm_feecategory": spec["fee_category"]}
    ):
        return
    pf = frappe.get_doc(
        {
            "doctype": "Program Fees",
            "program": program,
            "pgm_feecategory": spec["fee_category"],
            "pgm_feeevent": spec["event"],
        }
    )
    pf.flags.ignore_permissions = True
    pf.insert()

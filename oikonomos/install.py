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


def before_install():
    # Oikonomos requires ERPNext (required_apps) and its billing flows need a set
    # up ERPNext (Company, Fiscal Year, Price Lists). Verify before installing.
    check_erpnext()


def after_install():
    setup_erpnext_groups()
    ensure_custom_fields()
    _seed()


def after_migrate():
    setup_erpnext_groups()
    ensure_custom_fields()
    _seed()


def _seed():
    from oikonomos.financial.seed import seed_billing_config

    seed_billing_config()


def check_erpnext():
    """Block install unless ERPNext is installed and its Setup Wizard is complete
    (relocated from seminary — seminary itself is now Frappe-only)."""
    from frappe import _

    if "erpnext" not in frappe.get_installed_apps():
        frappe.throw(
            _("ERPNext must be installed before installing Oikonomos"),
            title=_("Missing Dependency"),
        )
    errors = []
    if not frappe.get_all("Company", limit=1, pluck="name"):
        errors.append(_("No Company found. Complete the ERPNext Setup Wizard first."))
    if not frappe.db.count("Fiscal Year"):
        errors.append(_("No Fiscal Year found."))
    if not frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name"):
        errors.append(_("No active Selling Price List found."))
    if errors:
        frappe.throw(
            _("ERPNext setup is incomplete: {0}").format(" ".join(errors)),
            title=_("Setup Incomplete"),
        )


def setup_erpnext_groups():
    """Create the ERPNext groups seminary billing relies on (relocated from
    seminary.install.setup_fixtures). Idempotent via make_records."""
    from frappe import _
    from frappe.desk.page.setup_wizard.setup_wizard import make_records

    default_price_list = frappe.db.get_value(
        "Price List", {"selling": 1, "enabled": 1}, "name", order_by="creation asc"
    )
    customer_groups = [
        "Student",
        "Donor",
        "Church",
        "Denomination",
        "Seminary",
        "Para-church Organization",
        "Alumni",
        "Board Member",
        "Volunteer",
    ]
    records = [{"doctype": "Item Group", "item_group_name": "Tuition"}]
    records += [
        {
            "doctype": "Customer Group",
            "customer_group_name": g,
            "default_price_list": default_price_list,
        }
        for g in customer_groups
    ]
    records += [
        {"doctype": "UOM", "uom_name": _("Academic Event"), "must_be_whole_number": 0},
        {"doctype": "UOM", "uom_name": _("Credit hour"), "must_be_whole_number": 0},
        {"doctype": "Supplier Group", "supplier_group_name": _("Instructor")},
    ]
    make_records(records)


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


# Seminary Settings financial/asset config. These Link ERPNext doctypes
# (Company/Account/Cost Center/Customer/Location/Payment Gateway), so they live in
# the bridge and are absent on a Frappe-only install. Intentionally NOT mandatory
# (reqd omitted) — billing config is validated by oikonomos where needed, not by a
# hard doctype requirement that would block a seminary that hasn't set up billing.
SEMINARY_SETTINGS_CUSTOM_FIELDS = {
    "Seminary Settings": [
        {
            "fieldname": "root_asset_location",
            "fieldtype": "Link",
            "label": "Root Asset Location",
            "options": "Location",
            "insert_after": "sync_rooms_to_asset_locations",
            "description": (
                "Optional. Root of the Location subtree the seminary's campuses/"
                'rooms hang under. Leave blank to auto-create and use a "Seminary '
                'Locations" root.'
            ),
        },
        {
            "fieldname": "accounts_section",
            "fieldtype": "Section Break",
            "label": "Accounts",
            "insert_after": "grade_close_offset_days",
        },
        {
            "fieldname": "receivable_account",
            "fieldtype": "Link",
            "label": "Receivable Account",
            "options": "Account",
            "insert_after": "accounts_section",
        },
        {
            "fieldname": "column_break_wmyg",
            "fieldtype": "Column Break",
            "insert_after": "receivable_account",
        },
        {
            "fieldname": "company",
            "fieldtype": "Link",
            "label": "Company",
            "options": "Company",
            "insert_after": "column_break_wmyg",
        },
        {
            "fieldname": "income_account",
            "fieldtype": "Link",
            "label": "Income Account",
            "options": "Account",
            "insert_after": "company",
        },
        {
            "fieldname": "cost_center",
            "fieldtype": "Link",
            "label": "Cost Center",
            "options": "Cost Center",
            "insert_after": "income_account",
        },
        {
            "fieldname": "scholarship_cc",
            "fieldtype": "Link",
            "label": "Scholarship - Cost Center",
            "options": "Cost Center",
            "insert_after": "scholarships_section",
        },
        {
            "fieldname": "scholarship_cust",
            "fieldtype": "Link",
            "label": "Scholarship - Customer",
            "options": "Customer",
            "insert_after": "scholarship_cc",
            "description": "This customer will be used in all Sales Invoices of Scholarships.",
        },
        {
            "fieldname": "payment_gateway",
            "fieldtype": "Link",
            "label": "Payment Gateway",
            "options": "Payment Gateway",
            "insert_after": "section_break_fxlm",
        },
    ],
}


def setup_sales_invoice_permissions():
    """Grant the Student and Alumni roles read + print access to Sales Invoice.

    Row-level access is scoped to the user's own linked Student record by
    oikonomos.financial.sales_invoice_permissions. Idempotent."""
    from frappe import _
    from frappe.permissions import add_permission, update_permission_property

    if not frappe.db.exists("DocType", "Sales Invoice"):
        return
    for role in (_("Student"), _("Alumni")):
        if not frappe.db.exists("Role", role):
            continue
        add_permission("Sales Invoice", role, 0)
        update_permission_property("Sales Invoice", role, 0, "read", 1)
        update_permission_property("Sales Invoice", role, 0, "print", 1)
    frappe.db.commit()


def before_uninstall():
    # Hide the billing UI again when the bridge is removed.
    if frappe.db.exists("DocType", "Seminary Settings"):
        frappe.db.set_single_value("Seminary Settings", "has_oikonomos", 0)


def ensure_custom_fields():
    # Flag the billing bridge as present so seminary's gated billing fields/UI show.
    frappe.db.set_single_value("Seminary Settings", "has_oikonomos", 1)
    create_custom_fields(SALES_INVOICE_CUSTOM_FIELDS, ignore_validate=True)
    create_custom_fields(SEMINARY_SETTINGS_CUSTOM_FIELDS, ignore_validate=True)
    # Customer<->Person link + Student billing-identity fields.
    from oikonomos.financial.customer_person import setup_custom_fields as setup_cp

    setup_cp()
    # Instructor payroll fields/components — only when HRMS is on (no-op otherwise).
    from oikonomos.financial.salary_slip import provision_payroll_if_enabled

    provision_payroll_if_enabled()
    setup_sales_invoice_permissions()
    frappe.db.commit()

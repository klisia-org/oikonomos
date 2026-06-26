# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Trigger-invoice generation (oikonomos billing automation).

Relocated wholesale from `seminary.seminary.api` (the billing block that used
`import erpnext` and raw SQL against Sales Invoice / Customer Group / Item Price).
Seminary owns no part of this any more: it neither imports these generators nor
schedules them. The daily billing run is driven from `run_billing_automation`,
registered under oikonomos's own `scheduler_events`, so a Frappe-only seminary
generates no invoices.

The generators bill from the payer snapshot (`Payers Fee Category PE` +
`pgm_enroll_payers`) built by `oikonomos.financial.payers.get_payers`.
"""

import frappe
from frappe import _
from frappe.utils import getdate


def _billing_context():
    import erpnext

    company = frappe.db.get_single_value("Seminary Settings", "company")
    return {
        "today": frappe.utils.today(),
        "company": company,
        "currency": erpnext.get_company_currency(company),
        "receivable_account": frappe.db.get_single_value(
            "Seminary Settings", "receivable_account"
        ),
        "income_account": frappe.db.get_value(
            "Company", company, "default_income_account"
        ),
        "cost_center": frappe.db.get_single_value("Seminary Settings", "cost_center")
        or None,
        "auto_submit": bool(
            frappe.db.get_single_value("Seminary Settings", "auto_submit_sales_invoice")
        ),
    }


def _empty_invoice_result(reason=""):
    return {"created": 0, "skipped": 0, "failed": 0, "reason": reason}


def _create_trigger_invoice(row, tag, ctx, counts, summary=""):
    # Safety net: an SI with this tag already exists — partial prior run or flag cleared.
    if frappe.db.exists(
        "Sales Invoice", {"seminary_trigger": tag, "docstatus": ["<", 2]}
    ):
        counts["skipped"] += 1
        return
    try:
        items = [
            {
                "doctype": "Sales Invoice Item",
                "item_code": row.item,
                "qty": (row.pay_percent or 0) / 100,
                "rate": 0,
                "description": summary or f"Fee for {row.fee_category}",
                "income_account": ctx["income_account"],
                "cost_center": ctx["cost_center"],
                "base_rate": 0,
                "price_list_rate": row.price_list_rate,
            }
        ]
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "naming_series": "ACC-SINV-.YYYY.-",
                "posting_date": ctx["today"],
                "company": ctx["company"],
                "currency": ctx["currency"],
                "debit_to": ctx["receivable_account"],
                "income_account": ctx["income_account"],
                "conversion_rate": 1,
                "custom_student": row.student,
                "customer": row.customer,
                "selling_price_list": row.default_price_list,
                "base_grand_total": row.price_list_rate,
                "payment_terms_template": row.payterm_payer,
                "seminary_trigger": tag,
                "seminary_summary": summary,
                "items": items,
            }
        )
        si.run_method("set_missing_values")
        si.insert(ignore_permissions=True)
        if ctx["auto_submit"]:
            si.submit()
        counts["created"] += 1
    except Exception:
        counts["failed"] += 1
        frappe.log_error(frappe.get_traceback(), f"seminary billing tag {tag}")


@frappe.whitelist()
def generate_nat_invoices(academic_term):
    """Generate 'New Academic Term' Sales Invoices for the given term.

    Idempotent: fast-path exits if the term's invoiced_nat_on flag is set;
    per-row safety net checks seminary_trigger before each insert."""
    if not academic_term:
        return _empty_invoice_result("no term")
    if frappe.db.get_value("Academic Term", academic_term, "invoiced_nat_on"):
        return _empty_invoice_result("already invoiced")

    rows = frappe.db.sql(
        """
        SELECT pep.name AS pep_name, pfc.stu_link AS student,
               pep.fee_category, pep.payer AS customer,
               pep.pay_percent, pep.payterm_payer,
               fc.item,
               cg.default_price_list, ip.price_list_rate
        FROM `tabpgm_enroll_payers` pep
        INNER JOIN `tabPayers Fee Category PE` pfc ON pep.parent = pfc.name
        INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
        INNER JOIN `tabCustomer Group` cg ON pfc.pf_custgroup = cg.customer_group_name
        INNER JOIN `tabItem Price` ip
                ON cg.default_price_list = ip.price_list AND ip.item_code = fc.item
        INNER JOIN `tabProgram Enrollment` pe ON pe.name = pfc.pf_pe
        INNER JOIN `tabProgram` pgm ON pgm.name = pe.program
        LEFT JOIN `tabProgram Level` pl ON pl.name = pgm.program_level
        WHERE pfc.pf_active = 1
          AND fc.docstatus = 1
          AND pep.pep_event = 'New Academic Term'
          AND pe.status NOT IN ('Withdrawn', 'Dismissed', 'Graduated', 'Transferred')
          AND NOT (COALESCE(pe.billing_suspended, 0) = 1 AND COALESCE(pl.suspend_nat, 0) = 1)
          AND COALESCE(pgm.is_free, 0) = 0
        """,
        as_dict=True,
    )
    ctx = _billing_context()
    counts = {"created": 0, "skipped": 0, "failed": 0}
    term_label = (
        frappe.db.get_value("Academic Term", academic_term, "term_name")
        or academic_term
    )
    for r in rows:
        summary = _("New Academic Term — {0} ({1})").format(
            term_label, r.fee_category
        )
        _create_trigger_invoice(
            r, f"NAT:{academic_term}:{r.pep_name}", ctx, counts, summary=summary
        )
    frappe.db.set_value("Academic Term", academic_term, "invoiced_nat_on", getdate())
    frappe.logger().info(f"generate_nat_invoices({academic_term}): {counts}")
    return counts


@frappe.whitelist()
def generate_nay_invoices(academic_year):
    """Generate 'New Academic Year' Sales Invoices for the given year.

    Idempotent via invoiced_nay_on flag + seminary_trigger safety net."""
    if not academic_year:
        return _empty_invoice_result("no year")
    if frappe.db.get_value("Academic Year", academic_year, "invoiced_nay_on"):
        return _empty_invoice_result("already invoiced")

    rows = frappe.db.sql(
        """
        SELECT pep.name AS pep_name, pfc.stu_link AS student,
               pep.fee_category, pep.payer AS customer,
               pep.pay_percent, pep.payterm_payer,
               fc.item,
               cg.default_price_list, ip.price_list_rate
        FROM `tabpgm_enroll_payers` pep
        INNER JOIN `tabPayers Fee Category PE` pfc ON pep.parent = pfc.name
        INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
        INNER JOIN `tabCustomer Group` cg ON pfc.pf_custgroup = cg.customer_group_name
        INNER JOIN `tabItem Price` ip
                ON cg.default_price_list = ip.price_list AND ip.item_code = fc.item
        INNER JOIN `tabProgram Enrollment` pe ON pe.name = pfc.pf_pe
        INNER JOIN `tabProgram` pgm ON pgm.name = pe.program
        LEFT JOIN `tabProgram Level` pl ON pl.name = pgm.program_level
        WHERE pfc.pf_active = 1
          AND fc.docstatus = 1
          AND pep.pep_event = 'New Academic Year'
          AND pe.status NOT IN ('Withdrawn', 'Dismissed', 'Graduated', 'Transferred')
          AND NOT (COALESCE(pe.billing_suspended, 0) = 1 AND COALESCE(pl.suspend_nay, 0) = 1)
          AND COALESCE(pgm.is_free, 0) = 0
        """,
        as_dict=True,
    )
    ctx = _billing_context()
    counts = {"created": 0, "skipped": 0, "failed": 0}
    for r in rows:
        summary = _("New Academic Year — {0} ({1})").format(
            academic_year, r.fee_category
        )
        _create_trigger_invoice(
            r, f"NAY:{academic_year}:{r.pep_name}", ctx, counts, summary=summary
        )
    frappe.db.set_value("Academic Year", academic_year, "invoiced_nay_on", getdate())
    frappe.logger().info(f"generate_nay_invoices({academic_year}): {counts}")
    return counts


@frappe.whitelist()
def generate_readmission_invoice(program_enrollment, fee_category, as_of=None):
    """Bill a one-off readmission fee for a Program Enrollment returning from
    leave, reusing the standard trigger-invoice pipeline. Idempotent per
    (PE, date, payer) via the seminary_trigger tag."""
    if not program_enrollment or not fee_category:
        return _empty_invoice_result("missing args")

    as_of = getdate(as_of) if as_of else getdate()
    rows = frappe.db.sql(
        """
        SELECT pep.name AS pep_name, pfc.stu_link AS student,
               pep.fee_category, pep.payer AS customer,
               pep.pay_percent, pep.payterm_payer,
               fc.item,
               cg.default_price_list, ip.price_list_rate
        FROM `tabpgm_enroll_payers` pep
        INNER JOIN `tabPayers Fee Category PE` pfc ON pep.parent = pfc.name
        INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
        INNER JOIN `tabCustomer Group` cg ON pfc.pf_custgroup = cg.customer_group_name
        INNER JOIN `tabItem Price` ip
                ON cg.default_price_list = ip.price_list AND ip.item_code = fc.item
        WHERE pfc.pf_active = 1
          AND fc.docstatus = 1
          AND pfc.pf_pe = %s
          AND pep.fee_category = %s
        """,
        (program_enrollment, fee_category),
        as_dict=True,
    )
    ctx = _billing_context()
    counts = {"created": 0, "skipped": 0, "failed": 0}
    tag_date = as_of.strftime("%Y-%m-%d")
    for r in rows:
        summary = _("Readmission Fee — {0}").format(r.fee_category)
        _create_trigger_invoice(
            r,
            f"READMIT:{program_enrollment}:{tag_date}:{r.pep_name}",
            ctx,
            counts,
            summary=summary,
        )
    frappe.logger().info(
        f"generate_readmission_invoice({program_enrollment}): {counts}"
    )
    return counts


def _ensure_applicant_customer(applicant):
    """Return the Customer for a Student Applicant, creating one if missing.

    Strategy: prefer the link already on the applicant, then a Customer
    matching the applicant's email, then create a fresh Customer using the
    applicant's title and customer_group (defaulting to "Individual").
    """
    if applicant.customer and frappe.db.exists("Customer", applicant.customer):
        return applicant.customer

    if applicant.student_email_id:
        existing = frappe.db.get_value(
            "Customer",
            {"email_id": applicant.student_email_id},
            "name",
        )
        if existing:
            applicant.db_set("customer", existing, update_modified=False)
            return existing

    customer_group = applicant.customer_group or "Individual"
    if not frappe.db.exists("Customer Group", customer_group):
        frappe.throw(
            _(
                "Customer Group {0} does not exist; set a valid Customer Group on the applicant before submitting."
            ).format(customer_group)
        )

    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": applicant.title or applicant.name,
            "customer_type": "Individual",
            "customer_group": customer_group,
            "email_id": applicant.student_email_id,
        }
    )
    customer.flags.ignore_permissions = True
    customer.insert(ignore_permissions=True)
    applicant.db_set("customer", customer.name, update_modified=False)
    return customer.name


@frappe.whitelist()
def generate_monthly_invoices(as_of=None):
    """Generate 'Monthly' Sales Invoices on the 1st of the month for every
    active Program Enrollment whose linked Fee Categories use fc_event='Monthly'.

    Idempotent: skips PEs whose last_monthly_invoiced_on is already >= the
    first of the current month; safety-net tag check prevents duplicates."""
    from frappe.utils import get_first_day

    as_of = getdate(as_of) if as_of else getdate()
    first_of_month = get_first_day(as_of)
    month_tag = as_of.strftime("%Y-%m")

    active_pes = frappe.db.sql(
        """
        SELECT DISTINCT pfc.pf_pe AS pe_name
        FROM `tabPayers Fee Category PE` pfc
        INNER JOIN `tabpgm_enroll_payers` pep ON pep.parent = pfc.name
        INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
        INNER JOIN `tabProgram Enrollment` pe ON pe.name = pfc.pf_pe
        INNER JOIN `tabProgram` pgm ON pgm.name = pe.program
        LEFT JOIN `tabProgram Level` pl ON pl.name = pgm.program_level
        WHERE pfc.pf_active = 1
          AND fc.docstatus = 1
          AND pep.pep_event = 'Monthly'
          AND pe.status NOT IN ('Withdrawn', 'Dismissed', 'Graduated', 'Transferred')
          AND NOT (COALESCE(pe.billing_suspended, 0) = 1 AND COALESCE(pl.suspend_monthly, 0) = 1)
          AND COALESCE(pgm.is_free, 0) = 0
          AND (pe.last_monthly_invoiced_on IS NULL OR pe.last_monthly_invoiced_on < %s)
          AND (fc.effective_from IS NULL OR pe.enrollment_date > fc.effective_from)
        """,
        (first_of_month,),
        as_dict=True,
    )

    ctx = _billing_context()
    counts = {"created": 0, "skipped": 0, "failed": 0}
    month_label = as_of.strftime("%B %Y")
    for pe_row in active_pes:
        pe_name = pe_row.pe_name
        rows = frappe.db.sql(
            """
            SELECT pep.name AS pep_name, pfc.stu_link AS student,
                   pep.fee_category, pep.payer AS customer,
                   pep.pay_percent, pep.payterm_payer,
                   fc.item,
                   cg.default_price_list, ip.price_list_rate
            FROM `tabpgm_enroll_payers` pep
            INNER JOIN `tabPayers Fee Category PE` pfc ON pep.parent = pfc.name
            INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
            INNER JOIN `tabCustomer Group` cg ON pfc.pf_custgroup = cg.customer_group_name
            INNER JOIN `tabItem Price` ip
                    ON cg.default_price_list = ip.price_list AND ip.item_code = fc.item
            INNER JOIN `tabProgram Enrollment` pe ON pe.name = pfc.pf_pe
            WHERE pfc.pf_active = 1
              AND fc.docstatus = 1
              AND pep.pep_event = 'Monthly'
              AND pfc.pf_pe = %s
              AND (fc.effective_from IS NULL OR pe.enrollment_date > fc.effective_from)
            """,
            (pe_name,),
            as_dict=True,
        )
        for r in rows:
            summary = _("Monthly — {0} ({1})").format(month_label, r.fee_category)
            _create_trigger_invoice(
                r,
                f"MONTHLY:{month_tag}:{r.pep_name}",
                ctx,
                counts,
                summary=summary,
            )
        frappe.db.set_value(
            "Program Enrollment", pe_name, "last_monthly_invoiced_on", first_of_month
        )
    frappe.logger().info(f"generate_monthly_invoices({as_of}): {counts}")
    return counts


@frappe.whitelist()
def regenerate_current_term_invoices():
    """Manual recovery: clear invoiced_nat_on on the current Academic Term and
    re-run the NAT generator. Safety-net seminary_trigger check still prevents
    duplicates for invoices that already exist."""
    frappe.only_for(["Registrar", "Seminary Manager", "System Manager"])
    current = frappe.db.get_value("Academic Term", {"iscurrent_acterm": 1}, "name")
    if not current:
        frappe.throw(_("No current Academic Term set."))
    frappe.db.set_value("Academic Term", current, "invoiced_nat_on", None)
    return generate_nat_invoices(current)


# Daily billing automation
# ------------------------
# Driven from oikonomos's own scheduler_events (not seminary's): a Frappe-only
# seminary never reaches this. Gated on the seminary `billing_automation_enabled`
# flag so a school can keep automatic billing off.


def _run_nat_for_due_terms(today):
    due = frappe.db.get_all(
        "Academic Term",
        filters={
            "term_start_date": ["<=", today],
            "invoiced_nat_on": ["is", "not set"],
        },
        pluck="name",
    )
    for term in due:
        generate_nat_invoices(term)


def _run_nay_for_due_years(today):
    due = frappe.db.get_all(
        "Academic Year",
        filters={
            "year_start_date": ["<=", today],
            "invoiced_nay_on": ["is", "not set"],
        },
        pluck="name",
    )
    for year in due:
        generate_nay_invoices(year)


def run_billing_automation(today=None):
    """Daily scheduler entry (oikonomos): generate any due NAT / NAY invoices and,
    on the 1st of the month, the monthly invoices. Relocated from seminary's
    tasks.daily() — billing is the bridge's responsibility now."""
    if not frappe.db.get_single_value(
        "Seminary Settings", "billing_automation_enabled"
    ):
        return
    today = getdate(today) if today else getdate()
    _run_nat_for_due_terms(today)
    _run_nay_for_due_years(today)
    if today.day == 1:
        generate_monthly_invoices(today)

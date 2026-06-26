# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""The ERPNext-backed implementation of seminary's FinancialBackend.

This is the real billing backend. It implements the contract seminary defines
(`seminary.seminary.financial.backend.FinancialBackend`) and is registered from
oikonomos's hooks.py under `seminary_financial_backend`. Seminary never imports
this module; the dependency runs oikonomos -> seminary only.

The billing *engine* (payer resolution, scholarship math, invoice construction)
lives here. The leaf invoice-builder helpers still live in
`seminary.seminary.billing` and are imported across the boundary; they relocate
into oikonomos together with the financial doctypes in a later phase.
"""

import erpnext
import frappe
from frappe import _
from frappe.utils import flt

from seminary.seminary.financial.backend import FinancialBackend, PaymentAggregate


class OikonomosFinancialBackend(FinancialBackend):
    def has_financials(self) -> bool:
        return True

    def payment_status_for_cei(self, cei_name: str) -> PaymentAggregate:
        return _aggregate_invoices("custom_cei", cei_name)

    def payment_status_for_graduation(self, gr_name: str) -> PaymentAggregate:
        return _aggregate_invoices("custom_graduation_request", gr_name)

    def generate_enrollment_invoice(self, cei_doc) -> int:
        return _generate_enrollment_invoice(cei_doc)

    def generate_program_enrollment_invoices(self, pfc_doc) -> dict:
        return _generate_program_enrollment_invoices(pfc_doc)

    def process_withdrawal_refunds(self, withdrawal_doc) -> None:
        from oikonomos.financial.withdrawal import process_refunds

        process_refunds(withdrawal_doc)

    def charge_readmission(self, pe_name: str, effective_date) -> None:
        from oikonomos.financial.readmission import charge_readmission

        charge_readmission(pe_name, effective_date)

    def sync_enrollment_payers(self, pe_name: str) -> None:
        from oikonomos.financial.payers import get_payers

        get_payers(frappe.get_doc("Program Enrollment", pe_name), None)

    def student_scholarships(self, student: str) -> list:
        from oikonomos.financial.scholarship import get_student_scholarship

        return get_student_scholarship(student)

    def available_scholarships(self, student: str) -> list:
        from oikonomos.financial.scholarship import get_available_scholarships

        return get_available_scholarships(student)

    def apply_for_scholarship(
        self, program_enrollment: str, scholarship: str, comment: str | None = None
    ) -> str | None:
        from oikonomos.financial.scholarship import apply_for_scholarship

        return apply_for_scholarship(program_enrollment, scholarship, comment)

    def student_invoices(self, student: str | None = None) -> list:
        from oikonomos.financial.invoice_queries import student_invoices

        return student_invoices(student)

    def pe_unpaid_invoices(self, program_enrollment: str) -> list:
        from oikonomos.financial.invoice_queries import pe_unpaid_invoices

        return pe_unpaid_invoices(program_enrollment)

    def unpaid_invoice_for_cei(self, cei_name: str) -> dict | None:
        from oikonomos.financial.invoice_queries import unpaid_invoice_for_cei

        return unpaid_invoice_for_cei(cei_name)

    def graduation_request_invoices(self, gr_name: str) -> list:
        from oikonomos.financial.invoice_queries import graduation_request_invoices

        return graduation_request_invoices(gr_name)

    def application_payment_url(self, applicant_name: str) -> dict | None:
        from oikonomos.financial.payment_urls import application_payment_url

        return application_payment_url(applicant_name)

    def invoice_payment_url(self, invoice_name: str) -> dict | None:
        from oikonomos.financial.payment_urls import invoice_payment_url

        return invoice_payment_url(invoice_name)

    def student_balance_payment_url(self) -> dict | None:
        from oikonomos.financial.payment_urls import student_balance_payment_url

        return student_balance_payment_url()

    def student_partial_balance_payment_url(
        self, amount=None, invoices=None
    ) -> dict | None:
        from oikonomos.financial.payment_urls import (
            student_partial_balance_payment_url,
        )

        return student_partial_balance_payment_url(amount, invoices)

    def cei_invoices(self, cei_name: str, include_cancelled: bool = False) -> list:
        filters = {"custom_cei": cei_name}
        if not include_cancelled:
            filters["docstatus"] = ("<", 2)
        return frappe.get_all("Sales Invoice", filters=filters, pluck="name")


# ---------------------------------------------------------------------------
# Course-enrollment billing engine (relocated from the seminary CEI controller's
# get_inv_data_ce). Reads the CEI's payer split for the 'Course Enrollment'
# event, resolves the student's scholarship at invoice time, and creates one
# Sales Invoice per payer (plus a forgiveness invoice when an award applies).
# ---------------------------------------------------------------------------


def on_cei_cancel(doc, method=None):
    """Course Enrollment Individual on_cancel (subscribed from oikonomos): cancel
    the enrollment's submitted Sales Invoices. Relocated from the seminary CEI
    controller — Sales Invoice is ERPNext's, so a Frappe-only seminary cancels a
    CEI without touching billing."""
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"custom_cei": doc.name, "docstatus": 1, "is_return": 0},
        pluck="name",
    )
    for inv_name in invoices:
        si = frappe.get_doc("Sales Invoice", inv_name)
        si.flags.ignore_permissions = True
        si.cancel()


def prepare_enrollment_payers(doc, method=None):
    """Program Enrollment before_submit (subscribed from oikonomos): build the
    payer rows (Payers Fee Category PE) for the enrollment. Relocated from
    seminary's PE on_submit hook — the builder lives in seminary.api (a financial
    helper) but only oikonomos triggers it, so a Frappe-only seminary submits a
    Program Enrollment without billing.

    Bound to before_submit (not on_submit) so it runs ahead of seminary's
    on_submit fulfiller, whose auto-created CEIs invoice against this fee
    structure — preserving the original single-app hook order now that the two
    handlers live in different apps (seminary installs before oikonomos)."""
    from oikonomos.financial.payers import get_payers

    get_payers(doc, method)


def _generate_enrollment_invoice(cei_doc) -> int:
    """Raise the Course-Enrollment Sales Invoice(s) for a CEI and return how many
    payer lines were billed. A return of 0 means nothing matched — no Course
    Enrollment fee is wired into the program's payers, or the Item Price is
    missing — so the caller must NOT mark the enrollment as invoiced."""
    from oikonomos.financial.billing import (
        build_and_create_invoice,
        create_scholarship_invoice,
        resolve_scholarship,
    )

    audithours = frappe.db.get_single_value("Seminary Settings", "auditcredit")
    is_audit = cei_doc.audit
    stulink = cei_doc.student_ce
    # Only the student's own payer line carries a scholarship; resolve it at
    # invoice time and book the forgiveness to a separate invoice.
    student_customer = frappe.db.get_value("Student", stulink, "customer") or stulink
    academic_term = cei_doc.academic_term or frappe.db.get_value(
        "Course Schedule", cei_doc.coursesc_ce, "academic_term"
    )
    inv_data = frappe.db.sql(
        """select cei.student_ce, cei.audit, cei.credits, cei.program_data,  pep.fee_category, pep.payer as Customer, pfc.pf_custgroup, pep.pay_percent, pep.payterm_payer, pep.pep_event, fc.feecategory_type, fc.is_credit, fc.item, cg.default_price_list, ip.price_list_rate
		from `tabCourse Enrollment Individual` cei,  `tabFee Category` fc, `tabpgm_enroll_payers` pep, `tabPayers Fee Category PE` pfc, `tabCustomer Group` cg, `tabItem Price` ip
		where cei.name = %s and
		cei.program_ce = pfc.pf_pe and
		pep.parent = pfc.name and
		pep.fee_category = fc.category_name and
		pep.fee_category = fc.name and
		cg.default_price_list = ip.price_list and
		ip.item_code = fc.item and
		pfc.pf_custgroup = cg.customer_group_name and
		cei.cei_si =0 and
		fc.is_audit = %s and
		pep.pep_event = 'Course Enrollment'""",
        (cei_doc.name, is_audit),
        as_list=1,
    )
    rows = frappe.db.sql(
        """select count(pep.payer)
		from `tabCourse Enrollment Individual` cei,  `tabFee Category` fc, `tabpgm_enroll_payers` pep, `tabPayers Fee Category PE` pfc, `tabCustomer Group` cg, `tabItem Price` ip
		where cei.name = %s and
		cei.program_ce = pfc.pf_pe and
		pep.parent = pfc.name and
		pep.fee_category = fc.category_name and
		pep.fee_category = fc.name and
		cg.default_price_list = ip.price_list and
		ip.item_code = fc.item and
		pfc.pf_custgroup = cg.customer_group_name and
		cei.cei_si =0 and
		fc.is_audit = %s and
		pep.pep_event = 'Course Enrollment'""",
        (cei_doc.name, is_audit),
    )[0][0]

    audit_suffix = _(" (Audit)") if is_audit == 1 else ""
    summary = _("Course: {0}{1}").format(cei_doc.course_data, audit_suffix)

    i = 0
    while i < rows:
        row = inv_data[i]
        if row[11] == 1:
            qty = row[2] * row[7] / 100
        elif is_audit == 1 and audithours == 1:
            qty = row[2] * row[7] / 100
        else:
            qty = row[7] / 100

        fee_category = row[4]
        price_list_rate = row[14]
        forgiven, award = 0, None
        if row[5] == student_customer:
            student_gross = round(qty * (price_list_rate or 0), 2)
            forgiven, award = resolve_scholarship(
                program_enrollment=cei_doc.program_ce,
                fee_category=fee_category,
                student_gross=student_gross,
                academic_term=academic_term,
            )

        build_and_create_invoice(
            customer=row[5],
            item_code=row[12],
            qty=qty,
            price_list_rate=price_list_rate,
            selling_price_list=row[13],
            payment_terms_template=row[8],
            summary=summary,
            student=stulink,
            link_field="custom_cei",
            link_value=cei_doc.name,
            discount_amount=(forgiven if (forgiven and award) else 0),
        )

        if forgiven and award:
            create_scholarship_invoice(
                award=award,
                fee_category=fee_category,
                academic_term=academic_term,
                scope=cei_doc.name,
                forgiven=forgiven,
                item_code=row[12],
                selling_price_list=row[13],
                payment_terms_template=row[8],
                summary=summary,
                student=stulink,
                link_field="custom_cei",
                link_value=cei_doc.name,
            )
        i += 1

    return rows


# ---------------------------------------------------------------------------
# Program-enrollment billing engine (relocated from the seminary Payers Fee
# Category PE controller's get_inv_data_pe). Bills the 'Program Enrollment' event
# payer split, applying the student's scholarship at invoice time.
# ---------------------------------------------------------------------------


def _generate_program_enrollment_invoices(pfc_doc) -> dict:
    from oikonomos.financial.billing import (
        create_scholarship_invoice,
        resolve_scholarship,
    )

    today = frappe.utils.today()
    company = frappe.db.get_single_value("Seminary Settings", "company")
    currency = erpnext.get_company_currency(company)
    receivable_account = frappe.db.get_single_value(
        "Seminary Settings", "receivable_account"
    )
    submittable = frappe.db.get_single_value(
        "Seminary Settings", "auto_submit_sales_invoice"
    )
    income_account = frappe.db.get_value("Company", company, "default_income_account")
    base_cost_center = (
        frappe.db.get_single_value("Seminary Settings", "cost_center") or None
    )
    stulink = pfc_doc.stu_link
    pe_meta = (
        frappe.db.get_value(
            "Program Enrollment",
            pfc_doc.pf_pe,
            ["program", "academic_term"],
            as_dict=True,
        )
        or frappe._dict()
    )
    program_label = pe_meta.program or ""
    academic_term = pe_meta.academic_term
    # The student's payer rows are billed against this customer; only those rows
    # get a scholarship applied (never church/other payers).
    student_customer = frappe.db.get_value("Student", stulink, "customer") or stulink

    rows = frappe.db.sql(
        """
        SELECT pep.name AS pep_name, pep.fee_category,
               pep.payer AS customer, pep.pay_percent,
               pep.payterm_payer, fc.item,
               cg.default_price_list, ip.price_list_rate
        FROM `tabpgm_enroll_payers` pep
        INNER JOIN `tabPayers Fee Category PE` pfc ON pep.parent = pfc.name
        INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
        INNER JOIN `tabCustomer Group` cg ON pfc.pf_custgroup = cg.customer_group_name
        INNER JOIN `tabItem Price` ip
                ON cg.default_price_list = ip.price_list AND ip.item_code = fc.item
        WHERE pfc.name = %s
          AND fc.docstatus = 1
          AND pep.pep_event = 'Program Enrollment'
        """,
        (pfc_doc.name,),
        as_dict=True,
    )

    if not rows:
        # Nothing to bill. Distinguish "no PE rows at all" from "PE rows exist but
        # their Fee Categories aren't submitted" so the registrar knows which to fix.
        unsubmitted = frappe.db.sql(
            """
            SELECT DISTINCT pep.fee_category, fc.docstatus
            FROM `tabpgm_enroll_payers` pep
            INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
            WHERE pep.parent = %s
              AND pep.pep_event = 'Program Enrollment'
              AND fc.docstatus != 1
            """,
            (pfc_doc.name,),
            as_dict=True,
        )
        if unsubmitted:
            names = ", ".join(
                f"{r.fee_category} (docstatus={r.docstatus})" for r in unsubmitted
            )
            frappe.throw(
                _(
                    "No Sales Invoices were created. The following Fee Categories are not submitted: {0}. Submit them from the Fee Category list and try again."
                ).format(names)
            )
        frappe.throw(
            _(
                "No Sales Invoices were created. There are no active Program-Enrollment payer rows for this Payers Fee Category PE, or the matching Item Prices / Customer Groups are not configured."
            )
        )

    counts = {"created": 0, "skipped": 0, "failed": 0}
    for r in rows:
        tag = f"PE:{r.pep_name}"
        if frappe.db.exists(
            "Sales Invoice", {"seminary_trigger": tag, "docstatus": ["<", 2]}
        ):
            counts["skipped"] += 1
            continue

        # Scholarships are computed at invoice time and only ever reduce the
        # student's own line; the forgiveness is booked to a separate invoice.
        forgiven, award = 0, None
        if r.customer == student_customer:
            student_gross = round(
                (r.pay_percent or 0) / 100 * (r.price_list_rate or 0), 2
            )
            forgiven, award = resolve_scholarship(
                program_enrollment=pfc_doc.pf_pe,
                fee_category=r.fee_category,
                student_gross=student_gross,
                academic_term=academic_term,
            )

        summary = (
            _("Program Enrollment — {0} ({1})").format(r.fee_category, program_label)
            if program_label
            else _("Program Enrollment — {0}").format(r.fee_category)
        )

        try:
            items = [
                {
                    "doctype": "Sales Invoice Item",
                    "item_code": r.item,
                    "qty": (r.pay_percent or 0) / 100,
                    "rate": 0,
                    "description": summary,
                    "income_account": income_account,
                    "cost_center": base_cost_center,
                    "base_rate": 0,
                    "price_list_rate": r.price_list_rate,
                }
            ]

            invoice_data = {
                "doctype": "Sales Invoice",
                "naming_series": "ACC-SINV-.YYYY.-",
                "posting_date": today,
                "company": company,
                "currency": currency,
                "debit_to": receivable_account,
                "income_account": income_account,
                "conversion_rate": 1,
                "customer": r.customer,
                "selling_price_list": r.default_price_list,
                "base_grand_total": r.price_list_rate,
                "payment_terms_template": r.payterm_payer,
                "items": items,
                "custom_student": stulink,
                "seminary_trigger": tag,
                "seminary_summary": summary,
            }
            if forgiven and award:
                invoice_data["apply_discount_on"] = "Grand Total"
                invoice_data["discount_amount"] = forgiven

            si = frappe.get_doc(invoice_data)
            si.run_method("set_missing_values")
            si.insert()
            if submittable == 1:
                si.submit()
            counts["created"] += 1

            if forgiven and award:
                create_scholarship_invoice(
                    award=award,
                    fee_category=r.fee_category,
                    academic_term=academic_term,
                    scope="PE",
                    forgiven=forgiven,
                    item_code=r.item,
                    selling_price_list=r.default_price_list,
                    payment_terms_template=r.payterm_payer,
                    summary=summary,
                    student=stulink,
                )
        except Exception:
            counts["failed"] += 1
            frappe.log_error(frappe.get_traceback(), f"get_inv_data_pe tag {tag}")

    if counts["created"] == 0 and counts["failed"] > 0:
        frappe.throw(
            _(
                "No Sales Invoices were created. {0} row(s) failed — see Error Log for details."
            ).format(counts["failed"])
        )
    return counts


def _aggregate_invoices(link_field: str, link_value: str) -> PaymentAggregate:
    """Sum submitted, non-return Sales Invoices linked via `link_field`.

    `link_field` is a fixed identifier chosen by the caller (never user input),
    so interpolating it into the query is safe.
    """
    rows = frappe.db.sql(
        """SELECT COALESCE(SUM(grand_total), 0) AS invoiced,
                  COALESCE(SUM(grand_total - outstanding_amount), 0) AS paid,
                  COUNT(*) AS si_count
           FROM `tabSales Invoice`
           WHERE {field} = %s
             AND docstatus = 1
             AND is_return = 0""".format(
            field=link_field
        ),
        (link_value,),
        as_dict=True,
    )
    invoiced = flt(rows[0].invoiced) if rows else 0.0
    paid = flt(rows[0].paid) if rows else 0.0
    si_count = int(rows[0].si_count) if rows else 0

    if invoiced > 0:
        paid_percent = paid / invoiced * 100.0
    elif si_count > 0:
        # All linked invoices are $0 (e.g. full scholarship) — vacuously paid.
        paid_percent = 100.0
    else:
        paid_percent = 0.0

    return PaymentAggregate(
        invoiced=invoiced, paid=paid, si_count=si_count, paid_percent=paid_percent
    )

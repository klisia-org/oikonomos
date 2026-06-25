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

    def generate_enrollment_invoice(self, cei_doc) -> None:
        _generate_enrollment_invoice(cei_doc)


# ---------------------------------------------------------------------------
# Course-enrollment billing engine (relocated from the seminary CEI controller's
# get_inv_data_ce). Reads the CEI's payer split for the 'Course Enrollment'
# event, resolves the student's scholarship at invoice time, and creates one
# Sales Invoice per payer (plus a forgiveness invoice when an award applies).
# ---------------------------------------------------------------------------


def _generate_enrollment_invoice(cei_doc) -> None:
    from seminary.seminary.billing import (
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

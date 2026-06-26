# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Graduation Request billing (oikonomos side effects).

Relocated from the seminary Graduation Request controller, whose on_submit /
on_cancel interleaved academic and financial work. Oikonomos subscribes to those
events via doc_events and runs only the financial half:

- on_submit: generate one Sales Invoice per 'Graduation Request' payer (unless
  the request is free), then stamp gr_si.
- on_cancel: cancel the linked, fully-unpaid Sales Invoices (skipped when the
  cancel cascades from a PE withdrawal — the fee is non-refundable then).

Seminary keeps the academic half (workflow stamp, diploma issue/revoke). With no
bridge installed these handlers never register and graduation is free.
"""

import erpnext
import frappe
from frappe import _
from frappe.utils import flt, today


def on_submit(doc, method=None):
    if doc.gr_si:
        return
    if doc.is_free:
        doc.db_set("gr_si", 1, update_modified=False)
        return
    _generate_sales_invoices(doc)
    doc.db_set("gr_si", 1, update_modified=False)


def on_cancel(doc, method=None):
    """Cancel any unpaid linked Sales Invoices. When the cancellation cascades
    from a PE withdrawal the fee is non-refundable per the per-program policy, so
    `flags.cascade_from_pe_withdrawal` skips SI cancellation in that path."""
    if getattr(doc.flags, "cascade_from_pe_withdrawal", False):
        return

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "custom_graduation_request": doc.name,
            "docstatus": 1,
            "is_return": 0,
        },
        fields=["name", "outstanding_amount", "grand_total"],
    )
    for inv in invoices:
        # Only cancel if fully unpaid; partial payments leave the SI alone so the
        # registrar can decide on refund handling explicitly.
        if flt(inv.outstanding_amount) == flt(inv.grand_total):
            si = frappe.get_doc("Sales Invoice", inv.name)
            si.flags.ignore_permissions = True
            si.cancel()


def _generate_sales_invoices(doc):
    """Generate one Sales Invoice per payer configured for this PE with
    `pep_event = 'Graduation Request'`. Mirrors the CEI pattern.

    Resolved progressively so the error message points at the actual missing
    piece (payer row, fee category, item, item price, customer group price list)
    instead of a blanket "not configured".
    """
    payer_rows = frappe.db.sql(
        """SELECT pep.name AS pep_name,
                  pep.fee_category,
                  pep.payer AS customer,
                  pfc.pf_custgroup,
                  pep.pay_percent,
                  pep.payterm_payer
           FROM `tabPayers Fee Category PE` pfc
           INNER JOIN `tabpgm_enroll_payers` pep ON pep.parent = pfc.name
           WHERE pfc.pf_pe = %s
             AND pep.pep_event = 'Graduation Request'""",
        (doc.program_enrollment,),
        as_dict=True,
    )

    if not payer_rows:
        frappe.throw(
            _(
                "No 'Graduation Request' payer is configured on Program Enrollment {0}. "
                "Open the enrollment's Payers Fee Category section and add a payer row "
                "with Event = 'Graduation Request' before submitting."
            ).format(doc.program_enrollment)
        )

    company = frappe.defaults.get_defaults().company
    currency = erpnext.get_company_currency(company)
    receivable_account = frappe.db.get_single_value(
        "Seminary Settings", "receivable_account"
    )
    submit_invoice = frappe.db.get_single_value(
        "Seminary Settings", "auto_submit_sales_invoice"
    )
    cost_center = frappe.db.get_single_value("Seminary Settings", "cost_center")
    sch_cost_center = frappe.db.get_single_value("Seminary Settings", "scholarship_cc")
    sch_customer = frappe.db.get_single_value("Seminary Settings", "scholarship_cust")

    income_account_row = frappe.db.sql(
        "SELECT default_income_account FROM `tabCompany` WHERE name=%s", company
    )
    income_account = income_account_row[0][0] if income_account_row else None

    for payer in payer_rows:
        item, price_list, price_list_rate = _resolve_pricing(payer)
        qty = flt(payer.pay_percent) / 100.0
        grand_total = qty * flt(price_list_rate)
        row_cost_center = (
            sch_cost_center if payer.customer == sch_customer else cost_center
        )
        discount = 100 if payer.customer == sch_customer else 0
        summary = _("Graduation Request: {0}").format(doc.name)

        sales_invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "naming_series": "ACC-SINV-.YYYY.-",
                "posting_date": today(),
                "company": company,
                "currency": currency,
                "debit_to": receivable_account,
                "income_account": income_account,
                "conversion_rate": 1,
                "customer": payer.customer,
                "selling_price_list": price_list,
                "base_grand_total": grand_total,
                "payment_terms_template": payer.payterm_payer,
                "remarks": summary,
                "items": [
                    {
                        "doctype": "Sales Invoice Item",
                        "item_code": item,
                        "qty": qty,
                        "rate": 0,
                        "description": summary,
                        "income_account": income_account,
                        "cost_center": row_cost_center,
                        "base_rate": 0,
                        "price_list_rate": price_list_rate,
                    }
                ],
                "cost_center": row_cost_center,
                "custom_student": doc.student,
                "custom_graduation_request": doc.name,
                "additional_discount_percentage": discount,
                "seminary_summary": summary,
            }
        )
        # Authorization was already enforced at the endpoint and in
        # before_submit; the SI is a trusted side effect (the Student role
        # doesn't hold Sales Invoice permissions).
        sales_invoice.flags.ignore_permissions = True
        sales_invoice.insert(ignore_permissions=True)
        if submit_invoice == 1:
            sales_invoice.submit()


def _resolve_pricing(payer):
    """Look up item + price list rate for one payer row. Each lookup throws a
    specific error if the supporting data is missing."""
    item = frappe.db.get_value("Fee Category", payer.fee_category, "item")
    if not item:
        frappe.throw(
            _("Fee Category {0} has no Item set; cannot generate an invoice.").format(
                payer.fee_category
            )
        )

    price_list = frappe.db.get_value(
        "Customer Group", payer.pf_custgroup, "default_price_list"
    )
    if not price_list:
        frappe.throw(
            _(
                "Customer Group {0} has no default Price List; cannot price the "
                "Graduation Request fee."
            ).format(payer.pf_custgroup)
        )

    price_list_rate = frappe.db.get_value(
        "Item Price",
        {"item_code": item, "price_list": price_list},
        "price_list_rate",
    )
    if price_list_rate is None:
        frappe.throw(
            _(
                "No Item Price found for Item {0} on Price List {1}. "
                "Add an Item Price before submitting the Graduation Request."
            ).format(item, price_list)
        )

    return item, price_list, price_list_rate


# ---------------------------------------------------------------------------
# Payment-reactive advancement (relocated from seminary's
# graduation_request_lifecycle). Oikonomos traces a Sales Invoice / Payment Entry
# back to its Graduation Request and calls seminary's academic entry point.
# ---------------------------------------------------------------------------


def on_si_submit(doc, method=None):
    """Sales Invoice on_submit — recompute paid_percent for any linked GR.
    Covers SIs created already-submitted (auto-submit in Seminary Settings)."""
    gr = getattr(doc, "custom_graduation_request", None)
    if gr:
        _react(gr)


def on_si_update_after_submit(doc, method=None):
    """Sales Invoice on_update_after_submit — fires on outstanding_amount changes
    via the form. Idempotent recompute either way."""
    gr = getattr(doc, "custom_graduation_request", None)
    if gr:
        _react(gr)


def on_payment_entry_submit(doc, method=None):
    """Payment Entry on_submit — advance every linked GR that crosses threshold."""
    for gr_name in _grs_from_payment_entry(doc):
        _react(gr_name)


def on_payment_entry_cancel(doc, method=None):
    """Payment Entry on_cancel — recompute on refund/reversal. We do NOT
    auto-rollback an Approved GR; the registrar handles refunds explicitly."""
    from seminary.seminary.graduation_request_lifecycle import (
        recompute_gr_paid_percent,
    )

    for gr_name in _grs_from_payment_entry(doc):
        recompute_gr_paid_percent(gr_name)


def _react(gr_name):
    from seminary.seminary.graduation_request_lifecycle import react_to_gr_payment

    react_to_gr_payment(gr_name)


def _grs_from_payment_entry(pe_doc):
    """Distinct GR names traced from this Payment Entry's references via
    Sales Invoice.custom_graduation_request."""
    gr_names = set()
    for ref in pe_doc.references or []:
        if ref.reference_doctype != "Sales Invoice" or not ref.reference_name:
            continue
        gr = frappe.db.get_value(
            "Sales Invoice", ref.reference_name, "custom_graduation_request"
        )
        if gr:
            gr_names.add(gr)
    return gr_names

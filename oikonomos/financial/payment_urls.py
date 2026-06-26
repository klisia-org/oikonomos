# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Payment-gateway URL builders (oikonomos).

Relocated from seminary.api. These create ERPNext Payment Requests against a
Sales Invoice or a Student Balance and return the gateway URL. Seminary exposes
the student-facing whitelisted method names as thin shims that delegate here
through the financial backend; a Frappe-only seminary returns None (no gateway,
no invoices).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt


def application_payment_url(applicant_name):
    """Payment URL for a Student Applicant's outstanding Application Sales Invoice,
    plus any alternative payment instructions configured on Seminary Settings.
    Used by the public Student Applicant web form. Returns None if the applicant
    doesn't exist."""
    if not applicant_name or not frappe.db.exists("Student Applicant", applicant_name):
        return None

    settings = frappe.get_single("Seminary Settings")
    alternative_instructions = settings.get("alternative_payment_instructions") or None

    invoice = frappe.db.sql(
        """
        SELECT name, currency, outstanding_amount
        FROM `tabSales Invoice`
        WHERE seminary_trigger LIKE %(prefix)s
          AND docstatus < 2
          AND outstanding_amount > 0
        ORDER BY creation DESC
        LIMIT 1
        """,
        {"prefix": f"APP:{applicant_name}:%"},
        as_dict=True,
    )

    if not invoice:
        return {
            "payment_url": None,
            "amount": None,
            "currency": None,
            "alternative_instructions": alternative_instructions,
        }

    inv = invoice[0]
    payment_url = None
    if settings.portal_payment_enable and settings.payment_gateway:
        try:
            payment_url = _create_application_payment_url(inv.name, settings)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"application_payment_url({applicant_name})",
            )

    return {
        "payment_url": payment_url,
        "amount": inv.outstanding_amount,
        "currency": inv.currency,
        "alternative_instructions": alternative_instructions,
    }


def _create_application_payment_url(invoice_name, settings):
    """Create a Payment Request for an Application SI and return the URL.
    Mirrors invoice_payment_url but skips the student-permission gate
    (applicant payments come from the guest web form context — they need
    to pay before they have a Student record)."""
    gateway_account = frappe.db.get_value(
        "Payment Gateway Account",
        {"payment_gateway": settings.payment_gateway},
        "name",
    )
    if not gateway_account:
        return None

    from erpnext.accounts.doctype.payment_request.payment_request import (
        cancel_old_payment_requests,
        get_amount,
        get_gateway_details,
    )

    ref_doc = frappe.get_doc("Sales Invoice", invoice_name)
    gateway = (
        get_gateway_details(
            frappe._dict(
                {
                    "payment_gateway_account": gateway_account,
                    "company": ref_doc.company,
                }
            )
        )
        or frappe._dict()
    )

    grand_total = get_amount(ref_doc, gateway.get("payment_account"))
    if not grand_total:
        return None

    cancel_old_payment_requests("Sales Invoice", invoice_name)

    pr = frappe.new_doc("Payment Request")
    pr.update(
        {
            "payment_gateway_account": gateway.get("name"),
            "payment_gateway": gateway.get("payment_gateway"),
            "payment_account": gateway.get("payment_account"),
            "payment_channel": gateway.get("payment_channel"),
            "payment_request_type": "Inward",
            "currency": ref_doc.currency,
            "grand_total": grand_total,
            "email_to": ref_doc.owner,
            "subject": _("Application Payment for {0}").format(ref_doc.customer),
            "message": gateway.get("message") or "",
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice_name,
            "company": ref_doc.company,
            "party_type": "Customer",
            "party": ref_doc.customer,
            "mute_email": 1,
        }
    )
    pr.flags.ignore_permissions = True
    pr.insert(ignore_permissions=True)
    pr.submit()
    return pr.get_payment_url()


def invoice_payment_url(invoice_name):
    """Create a Payment Request for a Sales Invoice and return the payment URL.
    Students can only request payment for their own invoices (validated via
    custom_student on the Sales Invoice)."""
    from oikonomos.financial.sales_invoice_permissions import (
        _current_student,
        _should_restrict,
    )

    if _should_restrict(frappe.session.user):
        student = _current_student(frappe.session.user)
        invoice_student = frappe.db.get_value(
            "Sales Invoice", invoice_name, "custom_student"
        )
        if not student or invoice_student != student:
            frappe.throw(_("You do not have permission to pay this invoice."))

    settings = frappe.get_single("Seminary Settings")
    if not settings.portal_payment_enable or not settings.payment_gateway:
        frappe.throw(
            _("Online payments are not enabled. Please contact the administration.")
        )

    gateway_account = frappe.db.get_value(
        "Payment Gateway Account",
        {"payment_gateway": settings.payment_gateway},
        "name",
    )
    if not gateway_account:
        frappe.throw(
            _("No Payment Gateway Account configured for {0}.").format(
                settings.payment_gateway
            )
        )

    from erpnext.accounts.doctype.payment_request.payment_request import (
        cancel_old_payment_requests,
        get_amount,
        get_gateway_details,
    )

    ref_doc = frappe.get_doc("Sales Invoice", invoice_name)
    gateway = (
        get_gateway_details(
            frappe._dict(
                {
                    "payment_gateway_account": gateway_account,
                    "company": ref_doc.company,
                }
            )
        )
        or frappe._dict()
    )

    grand_total = get_amount(ref_doc, gateway.get("payment_account"))
    if not grand_total:
        frappe.throw(_("This invoice has already been paid."))

    # Cancel any incomplete Payment Requests (submitted but not paid),
    # following the webshop pattern for re-payment attempts.
    cancel_old_payment_requests("Sales Invoice", invoice_name)

    pr = frappe.new_doc("Payment Request")
    pr.update(
        {
            "payment_gateway_account": gateway.get("name"),
            "payment_gateway": gateway.get("payment_gateway"),
            "payment_account": gateway.get("payment_account"),
            "payment_channel": gateway.get("payment_channel"),
            "payment_request_type": "Inward",
            "currency": ref_doc.currency,
            "grand_total": grand_total,
            "email_to": ref_doc.owner,
            "subject": _("Payment Request for {0}").format(invoice_name),
            "message": gateway.get("message") or "",
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice_name,
            "company": ref_doc.company,
            "party_type": "Customer",
            "party": ref_doc.customer,
            "mute_email": 1,
        }
    )
    pr.insert(ignore_permissions=True)
    pr.submit()

    return {"payment_url": pr.get_payment_url()}


def student_balance_payment_url():
    """Pay the full outstanding on the current student's open Student Balance."""
    from oikonomos.financial.sales_invoice_permissions import (
        _current_student,
        _should_restrict,
    )

    if not _should_restrict(frappe.session.user):
        frappe.throw(_("This action is only available for students."))

    student = _current_student(frappe.session.user)
    if not student:
        frappe.throw(_("Student record not found."))

    settings = frappe.get_single("Seminary Settings")
    if not settings.portal_payment_enable or not settings.payment_gateway:
        frappe.throw(_("Online payments are not enabled."))

    sb = _get_open_student_balance(student)

    if flt(sb.net_outstanding) <= 0:
        frappe.throw(_("No outstanding balance to pay."))

    # Set allocated_amount = outstanding_amount on each non-return row
    for row in sb.invoices:
        if not row.is_return and flt(row.outstanding_amount) > 0:
            row.allocated_amount = row.outstanding_amount
        else:
            row.allocated_amount = 0
    sb.save(ignore_permissions=True)

    pr = _create_balance_payment_request(sb, sb.net_outstanding, settings)
    return {"payment_url": pr.get_payment_url(), "student_balance": sb.name}


def student_partial_balance_payment_url(amount=None, invoices=None):
    """Pay a partial amount against the current student's open Student Balance.

    Args:
        amount: Fixed amount to pay (allocated by due date order).
        invoices: JSON list of {"sales_invoice": name, "amount": value} dicts.
    """
    from oikonomos.financial.sales_invoice_permissions import (
        _current_student,
        _should_restrict,
    )

    if not _should_restrict(frappe.session.user):
        frappe.throw(_("This action is only available for students."))

    student = _current_student(frappe.session.user)
    if not student:
        frappe.throw(_("Student record not found."))

    settings = frappe.get_single("Seminary Settings")
    if not settings.portal_payment_enable or not settings.payment_gateway:
        frappe.throw(_("Online payments are not enabled."))

    sb = _get_open_student_balance(student)

    if flt(sb.net_outstanding) <= 0:
        frappe.throw(_("No outstanding balance to pay."))

    # Reset all allocations
    for row in sb.invoices:
        row.allocated_amount = 0

    if invoices:
        # Parse if string
        if isinstance(invoices, str):
            invoices = json.loads(invoices)
        invoice_map = {item["sales_invoice"]: flt(item["amount"]) for item in invoices}
        for row in sb.invoices:
            if row.sales_invoice in invoice_map:
                alloc = min(invoice_map[row.sales_invoice], flt(row.outstanding_amount))
                row.allocated_amount = alloc
    elif amount:
        amount = flt(amount)
        if amount <= 0 or amount > flt(sb.net_outstanding):
            frappe.throw(_("Invalid payment amount."))
        # Allocate by due date
        remaining = amount
        sorted_rows = sorted(sb.invoices, key=lambda r: r.due_date or "9999-12-31")
        for row in sorted_rows:
            if row.is_return or flt(row.outstanding_amount) <= 0:
                continue
            alloc = min(flt(row.outstanding_amount), remaining)
            row.allocated_amount = alloc
            remaining -= alloc
            if remaining <= 0:
                break
    else:
        frappe.throw(_("Please specify an amount or select invoices to pay."))

    total_allocated = sum(
        flt(row.allocated_amount)
        for row in sb.invoices
        if not row.is_return and flt(row.allocated_amount) > 0
    )
    if total_allocated <= 0:
        frappe.throw(_("No amount allocated for payment."))

    sb.save(ignore_permissions=True)

    pr = _create_balance_payment_request(sb, total_allocated, settings)
    return {"payment_url": pr.get_payment_url(), "student_balance": sb.name}


def _get_open_student_balance(student):
    """Get the open Student Balance for a student, or throw."""
    sb_name = frappe.db.get_value(
        "Student Balance", {"student": student, "is_open": 1}, "name"
    )
    if not sb_name:
        frappe.throw(_("No open balance found for this student."))
    return frappe.get_doc("Student Balance", sb_name)


def _create_balance_payment_request(sb, amount, settings):
    """Create and submit a Payment Request against a Student Balance."""
    from erpnext.accounts.doctype.payment_request.payment_request import (
        cancel_old_payment_requests,
    )

    gateway_account = frappe.db.get_value(
        "Payment Gateway Account",
        {"payment_gateway": settings.payment_gateway},
        ["name", "payment_gateway", "payment_account", "payment_channel", "message"],
        as_dict=True,
    )
    if not gateway_account:
        frappe.throw(
            _("No Payment Gateway Account configured for {0}.").format(
                settings.payment_gateway
            )
        )

    cancel_old_payment_requests("Student Balance", sb.name)

    pr = frappe.new_doc("Payment Request")
    pr.update(
        {
            "payment_gateway_account": gateway_account.name,
            "payment_gateway": gateway_account.payment_gateway,
            "payment_account": gateway_account.payment_account,
            "payment_channel": gateway_account.payment_channel,
            "payment_request_type": "Inward",
            "currency": sb.currency,
            "grand_total": amount,
            "email_to": frappe.session.user,
            "subject": _("Payment for Student Balance {0}").format(sb.name),
            "message": gateway_account.message or "",
            "reference_doctype": "Student Balance",
            "reference_name": sb.name,
            "company": sb.company,
            "party_type": "Customer",
            "party": sb.customer,
            "mute_email": 1,
        }
    )
    # Add a payment_reference row so that validate_payment_request_amount
    # is skipped — it only knows standard doctypes like Sales Invoice.
    pr.append(
        "payment_reference",
        {
            "amount": amount,
            "description": _("Student Balance {0}").format(sb.name),
        },
    )
    pr.insert(ignore_permissions=True)
    pr.submit()

    sb.db_set("payment_request", pr.name)
    return pr

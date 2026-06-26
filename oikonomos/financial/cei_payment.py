# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Payment-reactive Course Enrollment advancement (oikonomos side).

Relocated from seminary's cei_lifecycle. These handlers are inherently shaped by
ERPNext billing documents (Sales Invoice / Payment Entry), so they live in the
bridge: oikonomos subscribes to those doctypes from its hooks.py, traces each
back to a Course Enrollment Individual, and calls seminary's academic entry point
`react_to_cei_payment(cei_name)`. The academic state machine and the payment
threshold stay in seminary; only the "which billing doc maps to which CEI" wiring
is here.
"""

import frappe


def maybe_advance_cei_on_payment(doc, method=None):
    """Sales Invoice hook. ERPNext updates SI.outstanding_amount via db.set_value
    on payment, which doesn't trigger on_update_after_submit — the actual
    payment-driven advancement happens in `on_payment_entry_submit`. This hook
    still fires for direct SI form saves and runs the same recompute, harmlessly."""
    cei_name = getattr(doc, "custom_cei", None)
    if not cei_name:
        return
    _react(cei_name)


def maybe_notify_registrar_on_invoice_cancel(doc, method=None):
    """Sales Invoice on_cancel hook. If a refund/cancellation drops the linked
    CEI's paid_percent below the program threshold while the CEI is already in
    Submitted state, seminary notifies registrars — but does NOT revert the
    workflow state."""
    cei_name = getattr(doc, "custom_cei", None)
    if not cei_name:
        return
    _react(cei_name)


def on_payment_entry_submit(doc, method=None):
    """Payment Entry hook. ERPNext updates Sales Invoice.outstanding_amount via
    db.set_value when a payment posts, which bypasses SI's on_update_after_submit
    — so we hook on Payment Entry directly. For each linked SI that traces back
    to a CEI, recompute payment status and advance / notify as needed."""
    for cei_name in _ceis_from_payment_entry(doc):
        _react(cei_name)


def on_payment_entry_cancel(doc, method=None):
    """Payment Entry on_cancel — refund/reversal path. Same fan-out as submit."""
    for cei_name in _ceis_from_payment_entry(doc):
        _react(cei_name)


def _react(cei_name):
    from seminary.seminary.cei_lifecycle import react_to_cei_payment

    react_to_cei_payment(cei_name)


def _ceis_from_payment_entry(pe_doc):
    """Distinct CEI names traced from this Payment Entry's references via
    Sales Invoice.custom_cei. Skips reference rows that aren't Sales Invoices
    or whose SI has no linked CEI."""
    cei_names = set()
    for ref in pe_doc.references or []:
        if ref.reference_doctype != "Sales Invoice" or not ref.reference_name:
            continue
        cei = frappe.db.get_value("Sales Invoice", ref.reference_name, "custom_cei")
        if cei:
            cei_names.add(cei)
    return cei_names

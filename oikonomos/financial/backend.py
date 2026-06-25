# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""The ERPNext-backed implementation of seminary's FinancialBackend.

This is the real billing backend. It implements the contract seminary defines
(`seminary.seminary.financial.backend.FinancialBackend`) and is registered from
oikonomos's hooks.py under `seminary_financial_backend`. Seminary never imports
this module; the dependency runs oikonomos -> seminary only.

Phase 2a relocated this from seminary (where it lived temporarily as
`SeminaryErpnextBackend`). The billing *engine* (build_and_create_invoice and
the get_inv_data_ce body) still lives in seminary at this point and is invoked
across the app boundary; later sub-phases move that engine here too.
"""

import frappe
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
        # The billing body still lives on the seminary CEI controller
        # (get_inv_data_ce -> seminary.seminary.billing.build_and_create_invoice).
        # A later sub-phase relocates that engine into oikonomos.
        cei_doc.get_inv_data_ce()


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

# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""The ledger's totals for an accreditor's yearly report (aretenic decision 080 §7).

Answers aretenic's `aretenic_report_financials` hook while oikonomos is the active
billing app: total revenue and total expenses for the fiscal year, and net assets
at its end, read from the default company's General Ledger. A total with no ledger
entries behind it is left out, so the report asks for it instead of showing a zero.
Tuition comes through seminary's sources-of-funding seam, not from here."""

import frappe
from frappe.utils import flt

from oikonomos.financial.active import is_active


def report_financials(start, end) -> dict:
    if not is_active():
        return {}
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        return {}
    out = {}
    flows = dict(
        frappe.db.sql(
            """SELECT acc.root_type, SUM(gle.debit) - SUM(gle.credit)
               FROM `tabGL Entry` gle JOIN `tabAccount` acc ON acc.name = gle.account
               WHERE gle.company = %s AND gle.is_cancelled = 0 AND gle.posting_date BETWEEN %s AND %s
                 AND acc.root_type IN ('Income', 'Expense')
               GROUP BY acc.root_type""",
            (company, start, end),
        )
    )
    if "Income" in flows:
        out["revenue_total"] = -flt(flows["Income"], 2)
    if "Expense" in flows:
        out["expense_total"] = flt(flows["Expense"], 2)
    # Assets carry a debit balance and liabilities a credit one, so their sum is net assets.
    position = frappe.db.sql(
        """SELECT COUNT(*), SUM(gle.debit) - SUM(gle.credit)
           FROM `tabGL Entry` gle JOIN `tabAccount` acc ON acc.name = gle.account
           WHERE gle.company = %s AND gle.is_cancelled = 0 AND gle.posting_date <= %s
             AND acc.root_type IN ('Asset', 'Liability')""",
        (company, end),
    )[0]
    if position[0]:
        out["net_assets"] = flt(position[1], 2)
    return out

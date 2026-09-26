# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Hooks that act only while oikonomos is the site's active billing app.

Another billing app (tamias, which books in QuickBooks Online) may be installed
beside oikonomos, so a school that changes ledgers keeps its history on the same
site. Seminary Settings names the active one, and seminary's resolver asks only
that one. Doc events and scheduler jobs, though, fire for every installed app,
so the ones that bill or create customers go through these wrappers: when
another app is active they do nothing, and it bills instead.

Handlers on oikonomos's own documents (Sales Invoice, Payment Entry) and on
payroll stay unguarded: they only fire on oikonomos documents, so settling an
invoice raised before a change of app still works.

The wrapped functions keep their own names and behaviour for direct callers
(backfills, demo data, tests).
"""

import frappe


def is_active() -> bool:
    from seminary.seminary.financial.backend import get_financial_backend

    from oikonomos.financial.backend import OikonomosFinancialBackend

    return isinstance(get_financial_backend(), OikonomosFinancialBackend)


def _only_when_active(path: str):
    def handler(*args, **kwargs):
        if is_active():
            return frappe.get_attr(path)(*args, **kwargs)
        return None

    handler.__name__ = path.rsplit(".", 1)[1]
    handler.__doc__ = f"{path}, only while oikonomos is the active billing app."
    return handler


# Academic events that raise or cancel invoices.
extension_on_submit = _only_when_active("oikonomos.financial.extension.on_submit")
extension_on_cancel = _only_when_active("oikonomos.financial.extension.on_cancel")
graduation_on_submit = _only_when_active("oikonomos.financial.graduation.on_submit")
graduation_on_cancel = _only_when_active("oikonomos.financial.graduation.on_cancel")
prepare_enrollment_payers = _only_when_active("oikonomos.financial.backend.prepare_enrollment_payers")
on_cei_cancel = _only_when_active("oikonomos.financial.backend.on_cei_cancel")
on_applicant_insert = _only_when_active("oikonomos.financial.application.on_applicant_insert")

# A student's Customer and Student Balance.
create_student_balance = _only_when_active(
    "oikonomos.oikonomos.doctype.student_balance.student_balance.create_student_balance"
)
on_student_update = _only_when_active("oikonomos.financial.customer_person.on_student_update")

# Daily jobs.
run_billing_automation = _only_when_active("oikonomos.financial.invoicing.run_billing_automation")
review_scholarship_retention = _only_when_active("oikonomos.financial.scholarship.review_scholarship_retention")

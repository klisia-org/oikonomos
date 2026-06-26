# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Student Applicant application-fee billing (oikonomos side effects).

Relocated from the seminary Student Applicant controller's after_insert.
Oikonomos subscribes to `Student Applicant.after_insert` via doc_events and
raises the Application-fee Sales Invoice(s) so the post-application payment page
has something to charge against. With no bridge installed the applicant is
created with no charge.

The shared billing helpers (`_billing_context`, `_ensure_applicant_customer`,
`_empty_invoice_result`) still live in `seminary.seminary.api` and are imported
across the boundary; they relocate into oikonomos with the rest of the api.py
billing block in a later phase.
"""

import frappe
from frappe import _


def on_applicant_insert(doc, method=None):
    """after_insert handler. Billing failures are logged, not raised, so a
    pricing/config gap never blocks applicant creation (matches the prior
    controller behaviour)."""
    try:
        _generate_application_invoices(doc.name)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Application invoice generation failed for {doc.name}",
        )


def _generate_application_invoices(applicant_name):
    """Generate Application-fee Sales Invoices for a Student Applicant.

    Walks `Program.pgm_pgmfees` rows where `pgm_feeevent = 'Application'` and
    creates one Sales Invoice per submitted Fee Category that has an Item Price
    under the resolved Customer Group's default price list.

    Idempotent: per-row safety net via `seminary_trigger = APP:<applicant>:<pf_row>`.
    Free programs and applicants whose Program has no Application fee configured
    are no-ops.
    """
    from seminary.seminary.api import (
        _billing_context,
        _empty_invoice_result,
        _ensure_applicant_customer,
    )

    if not applicant_name:
        return _empty_invoice_result("no applicant")
    applicant = frappe.get_doc("Student Applicant", applicant_name)
    if not applicant.program:
        return _empty_invoice_result("no program")
    program = frappe.get_doc("Program", applicant.program)
    if program.is_free:
        return _empty_invoice_result("free program")

    # Program Fees is now a standalone oikonomos doctype linked back to Program
    # (the inversion of the old Program.pgm_pgmfees child table).
    application_rows = frappe.get_all(
        "Program Fees",
        filters={"program": program.name, "pgm_feeevent": "Application"},
        fields=["name", "pgm_feecategory"],
    )
    application_rows = [r for r in application_rows if r.pgm_feecategory]
    if not application_rows:
        return _empty_invoice_result("no Application fee configured on program")

    customer = _ensure_applicant_customer(applicant)
    customer_group = frappe.db.get_value("Customer", customer, "customer_group")
    default_price_list = frappe.db.get_value(
        "Customer Group", customer_group, "default_price_list"
    )
    if not default_price_list:
        frappe.throw(
            _(
                "Customer Group {0} has no default Price List; cannot price the Application fee."
            ).format(customer_group)
        )

    ctx = _billing_context()
    counts = {"created": 0, "skipped": 0, "failed": 0}

    for pf_row in application_rows:
        tag = f"APP:{applicant_name}:{pf_row.name}"
        if frappe.db.exists(
            "Sales Invoice", {"seminary_trigger": tag, "docstatus": ["<", 2]}
        ):
            counts["skipped"] += 1
            continue

        fc = frappe.db.get_value(
            "Fee Category",
            pf_row.pgm_feecategory,
            ["item", "payment_term_template", "docstatus"],
            as_dict=True,
        )
        if not fc or fc.docstatus != 1 or not fc.item:
            counts["skipped"] += 1
            continue

        price_list_rate = frappe.db.get_value(
            "Item Price",
            {"price_list": default_price_list, "item_code": fc.item},
            "price_list_rate",
        )
        if price_list_rate is None:
            counts["skipped"] += 1
            frappe.log_error(
                f"No Item Price for {fc.item} on {default_price_list}; "
                f"skipped Application fee for {applicant_name}.",
                "generate_application_invoices",
            )
            continue

        summary = _("Application — {0}").format(pf_row.pgm_feecategory)
        try:
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
                    "customer": customer,
                    "selling_price_list": default_price_list,
                    "base_grand_total": price_list_rate,
                    "payment_terms_template": fc.payment_term_template,
                    "remarks": summary,
                    "seminary_trigger": tag,
                    "seminary_summary": summary,
                    "items": [
                        {
                            "doctype": "Sales Invoice Item",
                            "item_code": fc.item,
                            "qty": 1,
                            "rate": 0,
                            "description": _("Application fee for program {0}").format(
                                applicant.program
                            ),
                            "income_account": ctx["income_account"],
                            "cost_center": ctx["cost_center"],
                            "base_rate": 0,
                            "price_list_rate": price_list_rate,
                        }
                    ],
                    "cost_center": ctx["cost_center"],
                }
            )
            si.flags.ignore_permissions = True
            si.run_method("set_missing_values")
            si.insert(ignore_permissions=True)
            if ctx["auto_submit"]:
                si.submit()
            counts["created"] += 1
        except Exception:
            counts["failed"] += 1
            frappe.log_error(
                frappe.get_traceback(), f"seminary application billing tag {tag}"
            )

    frappe.logger().info(f"generate_application_invoices({applicant_name}): {counts}")
    return counts

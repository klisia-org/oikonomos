# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Withdrawal refund processing (oikonomos side effects).

Relocated from seminary's withdrawal.py. The seminary dispatcher
(`dispatch_withdrawal_effects`) still owns the academic decision of *when* a
financial effect is due (it keys off the 5-state Course Withdrawal workflow
transition); it delegates the *what* — credit notes against the withdrawn CEI's
Sales Invoices — to the financial backend, which routes here. With no bridge
installed, withdrawals apply their academic effects only and raise no refunds.
"""

import frappe


def process_refunds(doc):
    """Generate credit notes against Sales Invoices for the withdrawn CEI."""
    from erpnext.controllers.sales_and_purchase_return import make_return_doc

    doc.financial_processed_by = frappe.session.user

    if not doc.withdrawal_rule:
        return

    rule = frappe.get_doc("Withdrawal Rules", doc.withdrawal_rule)
    if not rule.has_refund or not rule.withdrawal_refunds:
        return

    cei_name = doc.course_enrollment_individual

    # Find all submitted, non-return Sales Invoices for this CEI
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "custom_cei": cei_name,
            "docstatus": 1,
            "is_return": 0,
        },
        fields=["name", "customer", "grand_total"],
    )

    if not invoices:
        return

    # Get payer type references
    settings = frappe.get_cached_doc("Seminary Settings")
    scholarship_cust = settings.scholarship_cust
    scholarship_procedure = settings.default_scholarship_withdrawal_procedure

    student = frappe.db.get_value("Course Enrollment Individual", cei_name, "student_ce")
    student_customer = (
        frappe.db.get_value("Student", student, "customer") if student else None
    )

    # Build refund map by payer type
    refund_map = {}
    for row in rule.withdrawal_refunds:
        refund_map[row.payer_type] = {
            "refund_percent": row.refund_percent,
            "refund_to": row.refund_to,
        }

    for inv in invoices:
        # Determine payer type
        if scholarship_cust and inv.customer == scholarship_cust:
            payer_type = "Scholarships"
        elif student_customer and inv.customer == student_customer:
            payer_type = "Student"
        else:
            payer_type = "Other Payers"

        refund_info = refund_map.get(payer_type)
        if not refund_info or not refund_info["refund_percent"]:
            continue

        refund_pct = refund_info["refund_percent"] / 100

        # Skip scholarship invoices with 0 grand_total (100% discount)
        if inv.grand_total == 0 and payer_type == "Scholarships":
            continue

        # Create return doc using ERPNext's built-in method
        return_doc = make_return_doc("Sales Invoice", inv.name)

        # Scale item quantities by refund percentage
        for item in return_doc.items:
            item.qty = item.qty * refund_pct

        # Student invoices now carry the scholarship forgiveness as an absolute
        # discount_amount (computed at invoice time). Scale it with the quantities
        # so the credit note refunds the same proportion of the net.
        if return_doc.get("discount_amount"):
            return_doc.discount_amount = return_doc.discount_amount * refund_pct

        return_doc.remarks = (
            f"Withdrawal refund for {cei_name} ({refund_info['refund_percent']}%)"
        )
        return_doc.insert(ignore_permissions=True)
        return_doc.submit()

        # If scholarship procedure requires invoicing the student
        if (
            payer_type == "Scholarships"
            and scholarship_procedure
            == "Refund to Scholarship Fund and Create Invoice for Student"
            and student_customer
            and inv.grand_total > 0
        ):
            _create_student_invoice_for_scholarship(
                inv, student_customer, refund_pct, cei_name, settings
            )


def _create_student_invoice_for_scholarship(
    original_inv, student_customer, refund_pct, cei_name, settings
):
    """Create a new Sales Invoice to the student for the scholarship amount being clawed back."""
    source_doc = frappe.get_doc("Sales Invoice", original_inv.name)

    items = []
    for item in source_doc.items:
        items.append(
            {
                "item_name": item.item_name,
                "item_code": item.item_code,
                "qty": abs(item.qty) * refund_pct,
                "rate": item.rate,
                "income_account": item.income_account,
                "cost_center": item.cost_center,
                "description": f"Scholarship withdrawal charge for {cei_name}",
            }
        )

    si = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "naming_series": "ACC-SINV-.YYYY.-",
            "posting_date": frappe.utils.today(),
            "company": source_doc.company,
            "currency": source_doc.currency,
            "debit_to": frappe.db.get_single_value(
                "Seminary Settings", "receivable_account"
            ),
            "customer": student_customer,
            "selling_price_list": source_doc.selling_price_list,
            "remarks": f"Scholarship withdrawal charge for {cei_name}",
            "items": items,
            "custom_student": frappe.db.get_value(
                "Course Enrollment Individual", cei_name, "student_ce"
            ),
        }
    )
    si.insert(ignore_permissions=True)
    si.submit()

# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Student-facing invoice reads (oikonomos).

Relocated from seminary.api. These read Sales Invoices for the portal (the Fees
page, the enrollment list, the program audit). Seminary exposes the whitelisted
method names as thin shims that delegate here through the financial backend; a
Frappe-only seminary returns empty (there are no invoices).
"""

import frappe
from frappe import _


def student_invoices(student=None):
    """The student's submitted Sales Invoices, formatted for the Fees page.

    If the caller is a student user, the scope is forced to their own Student
    record (a client-supplied ``student`` is ignored) to prevent cross-student
    access."""
    from oikonomos.financial.sales_invoice_permissions import (
        _current_student,
        _should_restrict,
    )

    if _should_restrict(frappe.session.user):
        student = _current_student(frappe.session.user)
        if not student:
            return []

    if not student:
        frappe.throw("student is required")

    # Only show invoices where the student is the customer (not church/scholarship)
    student_customer = frappe.db.get_value("Student", student, "customer")

    si_filters = {"custom_student": student, "docstatus": 1}
    if student_customer:
        si_filters["customer"] = student_customer

    sales_invoice_list = frappe.get_all(
        "Sales Invoice",
        filters=si_filters,
        fields=[
            "name",
            "customer",
            "posting_date",
            "due_date",
            "total",
            "outstanding_amount",
            "status",
            "is_return",
            "return_against",
            "custom_cei",
            "seminary_summary",
        ],
    )
    for invoice in sales_invoice_list:
        invoice["name"] = frappe.get_value("Sales Invoice", invoice["name"], "name")
        invoice["customer"] = frappe.get_value(
            "Customer", invoice["customer"], "customer_name"
        )
        # Prefer the explicit seminary_summary; fall back to the legacy CEI course
        # label so invoices that pre-date the summary field still get a label.
        summary = invoice.get("seminary_summary")
        if not summary and invoice.get("custom_cei"):
            course = frappe.db.get_value(
                "Course Enrollment Individual", invoice["custom_cei"], "course_data"
            )
            summary = _("Course: {0}").format(course) if course else None
        invoice["summary"] = summary
        invoice["course"] = summary  # back-compat for Fees.vue field name
        invoice["posting_date"] = frappe.utils.formatdate(invoice["posting_date"])
        invoice["outstanding_raw"] = invoice["outstanding_amount"]
        invoice["total_raw"] = invoice["total"]
        if invoice["is_return"]:
            invoice["status"] = "Return"
        invoice["total"] = "{:,.2f}".format(invoice["total"])
        invoice["outstanding_amount"] = "{:,.2f}".format(invoice["outstanding_amount"])
    sales_invoice_list = sorted(
        sales_invoice_list, key=lambda x: (x["status"], x["posting_date"]), reverse=True
    )

    return sales_invoice_list


def pe_unpaid_invoices(program_enrollment):
    """Aggregate every unpaid Sales Invoice tied to this Program Enrollment,
    grouped by payer (Customer). Covers three linkage paths:

    - Course Enrollment Individual via Sales Invoice.custom_cei
    - Graduation Request via Sales Invoice.custom_graduation_request
    - Trigger invoices (NAT/NAY/Monthly/etc.) via the seminary_trigger
      tag's last segment, which is the pgm_enroll_payers row name.

    Returns a list grouped by customer, sorted by total_unpaid desc.
    """
    if not program_enrollment:
        return []

    rows = frappe.db.sql(
        """
        SELECT * FROM (
            SELECT si.name, si.customer, si.grand_total, si.outstanding_amount,
                   'Course Enrollment' AS source
            FROM `tabSales Invoice` si
            INNER JOIN `tabCourse Enrollment Individual` cei ON cei.name = si.custom_cei
            WHERE si.docstatus = 1
              AND si.is_return = 0
              AND si.outstanding_amount > 0
              AND cei.program_ce = %(pe)s

            UNION ALL

            SELECT si.name, si.customer, si.grand_total, si.outstanding_amount,
                   'Graduation Request' AS source
            FROM `tabSales Invoice` si
            INNER JOIN `tabGraduation Request` gr ON gr.name = si.custom_graduation_request
            WHERE si.docstatus = 1
              AND si.is_return = 0
              AND si.outstanding_amount > 0
              AND gr.program_enrollment = %(pe)s

            UNION ALL

            SELECT si.name, si.customer, si.grand_total, si.outstanding_amount,
                   'Recurring Fee' AS source
            FROM `tabSales Invoice` si
            INNER JOIN `tabpgm_enroll_payers` pep
                ON pep.name = SUBSTRING_INDEX(si.seminary_trigger, ':', -1)
            INNER JOIN `tabPayers Fee Category PE` pfc ON pfc.name = pep.parent
            WHERE si.docstatus = 1
              AND si.is_return = 0
              AND si.outstanding_amount > 0
              AND si.seminary_trigger IS NOT NULL
              AND si.seminary_trigger != ''
              AND pfc.pf_pe = %(pe)s
        ) AS u
        ORDER BY u.customer, u.name
        """,
        {"pe": program_enrollment},
        as_dict=True,
    )

    # Group by customer
    by_customer = {}
    for r in rows:
        bucket = by_customer.setdefault(
            r.customer, {"customer": r.customer, "invoices": [], "total_unpaid": 0.0}
        )
        bucket["invoices"].append(
            {
                "name": r.name,
                "grand_total": float(r.grand_total or 0),
                "outstanding_amount": float(r.outstanding_amount or 0),
                "source": r.source,
            }
        )
        bucket["total_unpaid"] += float(r.outstanding_amount or 0)

    return sorted(by_customer.values(), key=lambda b: b["total_unpaid"], reverse=True)


def unpaid_invoice_for_cei(cei_name):
    """The most recent submitted, non-return Sales Invoice for a CEI (name +
    totals), or None. Surfaces the unpaid invoice on the enrollment list so an
    Awaiting-Payment student can click through to pay."""
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"custom_cei": cei_name, "docstatus": 1, "is_return": 0},
        fields=["name", "grand_total", "outstanding_amount"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0] if rows else None


def graduation_request_invoices(gr_name):
    """Submitted, non-return Sales Invoices linked to a Graduation Request."""
    return frappe.get_all(
        "Sales Invoice",
        filters={
            "custom_graduation_request": gr_name,
            "docstatus": 1,
            "is_return": 0,
        },
        fields=["name", "grand_total", "outstanding_amount"],
    )

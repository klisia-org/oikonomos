# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Student Applicant application-fee billing (oikonomos side effects).

Relocated from the seminary Student Applicant controller's after_insert.
Oikonomos subscribes to `Student Applicant.after_insert` via doc_events and
raises the Application-fee Sales Invoice(s) so the post-application payment page
has something to charge against. With no bridge installed the applicant is
created with no charge.

The shared billing helpers (`_billing_context`, `_ensure_applicant_customer`,
`_empty_invoice_result`) live alongside the trigger-invoice generators in
`oikonomos.financial.invoicing`.
"""

import frappe
from frappe import _
from frappe.utils import flt


def on_applicant_insert(doc, method=None):
	"""after_insert handler. Billing failures are logged, not raised, so a
	pricing/config gap never blocks applicant creation (matches the prior
	controller behaviour)."""
	if frappe.flags.in_import:
		return  # an imported application is history, not a new one to charge (seminary 094 §1)
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
	from oikonomos.financial.invoicing import (
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
	default_price_list = frappe.db.get_value("Customer Group", customer_group, "default_price_list")
	if not default_price_list:
		frappe.throw(
			_("Customer Group {0} has no default Price List; cannot price the Application fee.").format(
				customer_group
			)
		)

	# Seminary decides the discount: a window, a fee code (seminary decisions/113 §4).
	percent, source = _discount(applicant)
	if percent >= 100:
		return _empty_invoice_result("fee waived")

	ctx = _billing_context()
	counts = {"created": 0, "skipped": 0, "failed": 0}

	for pf_row in application_rows:
		tag = f"APP:{applicant_name}:{pf_row.name}"
		if frappe.db.exists("Sales Invoice", {"seminary_trigger": tag, "docstatus": ["<", 2]}):
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
					"remarks": summary
					+ (" " + _("({0}% off: {1})").format(f"{percent:g}", _(source or "")) if percent else ""),
					"seminary_trigger": tag,
					"seminary_summary": summary,
					"items": [
						{
							"doctype": "Sales Invoice Item",
							"item_code": fc.item,
							"qty": 1,
							"rate": 0,
							"description": _("Application fee for program {0}").format(applicant.program),
							"income_account": ctx["income_account"],
							"cost_center": ctx["cost_center"],
							"base_rate": 0,
							"price_list_rate": price_list_rate,
							"discount_percentage": percent,
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
			frappe.log_error(frappe.get_traceback(), f"seminary application billing tag {tag}")

	frappe.logger().info(f"generate_application_invoices({applicant_name}): {counts}")
	return counts


# -- discounts and waivers (seminary decisions/113) --------------------------------------------


def _discount(applicant):
	try:
		from seminary.seminary.admissions import application_fee_discount
	except ImportError:
		return 0.0, None
	percent, source = application_fee_discount(applicant)
	return min(max(flt(percent), 0), 100), source


def _application_invoices(applicant_name, docstatus=("<", 2)):
	return frappe.get_all(
		"Sales Invoice",
		filters={
			"seminary_trigger": ("like", f"APP:{applicant_name}:%"),
			"docstatus": docstatus,
			"is_return": 0,
		},
		pluck="name",
		order_by="creation asc",
	)


def application_fee_configured(program):
	return bool(frappe.db.exists("Program Fees", {"program": program, "pgm_feeevent": "Application"}))


def application_fee_paid(applicant_name):
	"""Payment Entries allocated to the applicant's invoices; credit notes don't count."""
	invoices = _application_invoices(applicant_name, 1)
	if not invoices:
		return 0.0
	rows = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"reference_doctype": "Sales Invoice",
			"reference_name": ("in", invoices),
			"docstatus": 1,
		},
		fields=["allocated_amount"],
	)
	return flt(sum(flt(r.allocated_amount) for r in rows), 2)


def waive_application_fee(applicant_name, percent, reason):
	"""Bring each open application invoice down to `percent` off its price-list
	price: a draft is repriced, a submitted one gets a credit note."""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	percent = min(max(flt(percent), 0), 100)
	done = []
	for name in _application_invoices(applicant_name):
		inv = frappe.get_doc("Sales Invoice", name)
		if inv.docstatus == 0:
			for item in inv.items:
				item.discount_percentage = percent
				item.rate = 0
			inv.flags.ignore_permissions = True
			inv.run_method("calculate_taxes_and_totals")
			inv.save()
			done.append(inv.name)
			continue
		full = sum(flt(i.price_list_rate or i.rate) * flt(i.qty) for i in inv.items)
		target = flt(full * (100 - percent) / 100, 2)
		amount = flt(flt(inv.outstanding_amount) - target, 2)
		if amount <= 0 or flt(inv.grand_total) <= 0:
			continue
		if frappe.db.exists("Sales Invoice", {"return_against": inv.name, "docstatus": 1, "is_return": 1}):
			continue
		ratio = amount / flt(inv.grand_total)
		credit = make_return_doc("Sales Invoice", inv.name)
		for item in credit.items:
			item.qty = flt(item.qty) * ratio
		if credit.get("discount_amount"):
			credit.discount_amount = flt(credit.discount_amount) * ratio
		credit.remarks = (_("Application fee waiver ({0}%): {1}").format(f"{percent:g}", reason or ""))[:140]
		# ERPNext compares the credit to the invoice's outstanding before it
		# recomputes totals; stale mapped totals make the credit keep its own
		# outstanding, and the invoice would stay unpaid.
		credit.run_method("calculate_taxes_and_totals")
		credit.update_outstanding_for_self = 0
		credit.insert(ignore_permissions=True)
		credit.submit()
		done.append(credit.name)
	return done


def react_to_payment_entry(pe_doc):
	"""Payment Entry hook: a paid application fee starts review (decisions/113 §6)."""
	applicants = set()
	for ref in pe_doc.references or []:
		if ref.reference_doctype != "Sales Invoice" or not ref.reference_name:
			continue
		tag = frappe.db.get_value("Sales Invoice", ref.reference_name, "seminary_trigger") or ""
		if tag.startswith("APP:"):
			applicants.add(tag[4:].rsplit(":", 1)[0])
	if not applicants:
		return
	from seminary.seminary import admissions

	if not hasattr(admissions, "on_fee_settled"):
		return
	for applicant in applicants:
		admissions.on_fee_settled(applicant)

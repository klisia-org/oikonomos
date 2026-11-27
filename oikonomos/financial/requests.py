# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Incomplete-extension and transcript-request fees (seminary decisions/119 §6).

Both fees are optional. A school sets one up the usual way: a Fee Category
whose Item has a price on the payer's Customer Group price list, added to the
Program's Program Fees with the event 'Incomplete Extension Request' or
'Transcript Request'. The enrollment's payer snapshot then carries a row for
that event, and each payer gets one Sales Invoice for its share. With no such
row nothing is raised and the request goes ahead free.

The invoices carry a `seminary_trigger` tag, `IER:<request>:<payer row>` or
`TRQ:<request>:<payer row>`, which makes raising them idempotent and is how
payment status and the payment callback find them again.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from oikonomos.financial.billing import build_and_create_invoice

INCOMPLETE_EXTENSION = "Incomplete Extension Request"
TRANSCRIPT = "Transcript Request"
PREFIX = {INCOMPLETE_EXTENSION: "IER", TRANSCRIPT: "TRQ"}


def _like(doctype, name):
	escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return f"{PREFIX[doctype]}:{escaped}:%"


def _latest_enrollment(student):
	rows = frappe.get_all(
		"Program Enrollment",
		filters={"student": student, "docstatus": 1},
		pluck="name",
		order_by="enrollment_date desc, creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def _payer_rows(program_enrollment, event):
	"""Priced payer rows for one event. Inactive snapshots count: an alumnus
	whose enrollment has ended can still order a transcript."""
	return frappe.db.sql(
		"""SELECT pep.name AS pep_name, pep.payer, pep.fee_category, pep.pay_percent,
                  pep.payterm_payer, fc.item, cg.default_price_list, ip.price_list_rate
           FROM `tabpgm_enroll_payers` pep
           INNER JOIN `tabPayers Fee Category PE` pfc ON pep.parent = pfc.name
           INNER JOIN `tabFee Category` fc ON pep.fee_category = fc.name
           INNER JOIN `tabCustomer Group` cg ON pfc.pf_custgroup = cg.customer_group_name
           INNER JOIN `tabItem Price` ip
                   ON ip.price_list = cg.default_price_list AND ip.item_code = fc.item
           WHERE pfc.pf_pe = %s AND pep.pep_event = %s""",
		(program_enrollment, event),
		as_dict=True,
	)


def _bill(doctype, name, student, program_enrollment, qty, summary):
	if not program_enrollment:
		return []
	sch_customer = frappe.db.get_single_value("Seminary Settings", "scholarship_cust")
	created = []
	for row in _payer_rows(program_enrollment, doctype):
		tag = f"{PREFIX[doctype]}:{name}:{row.pep_name}"
		if frappe.db.exists("Sales Invoice", {"seminary_trigger": tag, "docstatus": ("<", 2)}):
			continue
		created.append(
			build_and_create_invoice(
				customer=row.payer,
				item_code=row.item,
				qty=flt(row.pay_percent) / 100 * qty,
				price_list_rate=row.price_list_rate,
				selling_price_list=row.default_price_list,
				payment_terms_template=row.payterm_payer,
				summary=summary,
				student=student,
				is_scholarship=bool(sch_customer and row.payer == sch_customer),
				seminary_trigger=tag,
			)
		)
	return created


def charge_incomplete_extension(name):
	"""Bill an approved extension to the enrollment the course counts toward."""
	doc = frappe.get_doc(INCOMPLETE_EXTENSION, name)
	program = frappe.db.get_value("Scheduled Course Roster", doc.roster, "program_std_scr")
	pe = program and frappe.db.get_value(
		"Program Enrollment", {"student": doc.student, "program": program, "docstatus": 1}
	)
	return _bill(
		INCOMPLETE_EXTENSION,
		name,
		doc.student,
		pe or _latest_enrollment(doc.student),
		1,
		_("Incomplete extension: {0}").format(doc.course_title or doc.course_schedule or doc.roster),
	)


def charge_transcript_request(name):
	"""Bill an official transcript; a printed copy is charged per copy."""
	doc = frappe.get_doc(TRANSCRIPT, name)
	copies = max(cint(doc.copies) or 1, 1) if doc.delivery == "Printed copy" else 1
	return _bill(
		TRANSCRIPT,
		name,
		doc.student,
		doc.program_enrollment or _latest_enrollment(doc.student),
		copies,
		_("Official transcript ({0})").format(_(doc.delivery) if doc.delivery else ""),
	)


def request_invoices(doctype, name, docstatus=("<", 2)):
	return frappe.get_all(
		"Sales Invoice",
		filters={"seminary_trigger": ("like", _like(doctype, name)), "docstatus": docstatus, "is_return": 0},
		fields=["name", "docstatus", "grand_total", "outstanding_amount"],
		order_by="creation asc",
	)


def payment_status(doctype, name):
	from seminary.seminary.financial.backend import PaymentAggregate

	rows = request_invoices(doctype, name, 1)
	invoiced = flt(sum(flt(r.grand_total) for r in rows))
	paid = flt(sum(flt(r.grand_total) - flt(r.outstanding_amount) for r in rows))
	if invoiced > 0:
		percent = paid / invoiced * 100.0
	elif rows:
		percent = 100.0  # all zero (a scholarship payer): nothing to collect
	else:
		percent = 0.0
	return PaymentAggregate(invoiced=invoiced, paid=paid, si_count=len(rows), paid_percent=percent)


def waive_request_charges(doctype, name, reason):
	"""Delete the request's draft invoices and cancel its fully unpaid ones. A
	paid or part-paid invoice stays for the accounts team to refund."""
	if doctype not in PREFIX:
		return []
	done = []
	for row in request_invoices(doctype, name):
		inv = frappe.get_doc("Sales Invoice", row.name)
		inv.flags.ignore_permissions = True
		if inv.docstatus == 0:
			inv.delete(ignore_permissions=True)
		elif flt(inv.outstanding_amount) == flt(inv.grand_total):
			inv.add_comment("Comment", _("Fee waived: {0}").format(reason or ""))
			inv.cancel()
		else:
			continue
		done.append(row.name)
	return done


# -- payment callback ---------------------------------------------------------------------


def _transcript_requests(invoice_names):
	requests = set()
	for invoice in invoice_names:
		tag = frappe.db.get_value("Sales Invoice", invoice, "seminary_trigger") or ""
		if tag.startswith("TRQ:"):
			requests.add(tag[4:].rsplit(":", 1)[0])
	return requests


def _react(requests):
	if not requests:
		return
	from seminary.seminary import transcripts

	for request in requests:
		transcripts.react_to_transcript_payment(request)


def on_payment_entry_submit(doc, method=None):
	"""A payment on a transcript fee lets the request be issued."""
	_react(
		_transcript_requests(
			ref.reference_name
			for ref in doc.references or []
			if ref.reference_doctype == "Sales Invoice" and ref.reference_name
		)
	)


def on_si_submit(doc, method=None):
	"""An invoice submitted after the request (auto-submit off, or a zero-amount
	scholarship invoice) may already settle it."""
	_react(_transcript_requests([doc.name]))

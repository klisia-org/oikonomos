# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Fees billed as ERPNext Sales Invoices for seminary requests: the incomplete
extension and transcript fees (seminary decisions/119 §6) and the discounted
application fee (seminary decisions/113 §4-5).

The requests and the applicant are inserted directly: billing only reads their
fields, and their own controllers would charge them a second time.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today
from seminary.seminary.tests import cohort_fixtures as fx

from oikonomos.financial import application, requests
from oikonomos.financial.backend import OikonomosFinancialBackend

PRICE_LIST = "ZZ Oikonomos Selling"
GROUP = "ZZ Oikonomos Students"


class RequestFeesTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = frappe.defaults.get_defaults().company
		company = frappe.get_cached_doc("Company", self.company)
		for field, value in (
			("company", self.company),
			("receivable_account", company.default_receivable_account),
			("cost_center", company.cost_center),
			("auto_submit_sales_invoice", 1),
		):
			frappe.db.set_single_value("Seminary Settings", field, value)
		if not frappe.db.exists("Price List", PRICE_LIST):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": PRICE_LIST,
					"selling": 1,
					"currency": company.default_currency,
				}
			).insert()
		if not frappe.db.exists("Customer Group", GROUP):
			frappe.get_doc(
				{
					"doctype": "Customer Group",
					"customer_group_name": GROUP,
					"parent_customer_group": "All Customer Groups",
					"default_price_list": PRICE_LIST,
				}
			).insert()
		for event in (requests.INCOMPLETE_EXTENSION, requests.TRANSCRIPT, "Application"):
			if not frappe.db.exists("Trigger Fee Events", event):
				frappe.get_doc({"doctype": "Trigger Fee Events", "trigger": event, "active": 1}).insert()
		self.program = fx.make_program()

	def tearDown(self):
		frappe.db.rollback()

	def with_fee(self, event, amount):
		"""A Fee Category priced at `amount`, on the program for `event`."""
		label = f"ZZ {event} {frappe.generate_hash(length=5)}"
		item_group = frappe.db.get_value("Item Group", {"is_group": 0}) or "All Item Groups"
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": label,
				"item_name": label,
				"item_group": item_group,
				"stock_uom": "Fee",  # the fixture UOM: payer shares are fractions
				"is_stock_item": 0,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item.name,
				"price_list": PRICE_LIST,
				"price_list_rate": amount,
			}
		).insert()
		fee = frappe.get_doc(
			{
				"doctype": "Fee Category",
				"category_name": label,
				"item": item.name,
				"fc_event": event,
				"feecategory_type": item_group,
				"payment_term_template": self.terms(),
			}
		).insert()
		fee.submit()  # the application fee bills only a submitted category
		frappe.get_doc(
			{
				"doctype": "Program Fees",
				"program": self.program.name,
				"pgm_feecategory": fee.name,
				"pgm_feeevent": event,
			}
		).insert()
		return fee.name

	def terms(self):
		name = "ZZ Oikonomos Immediate"
		if not frappe.db.exists("Payment Terms Template", name):
			frappe.get_doc(
				{
					"doctype": "Payment Terms Template",
					"template_name": name,
					"terms": [
						{
							"invoice_portion": 100,
							"credit_days": 0,
							"due_date_based_on": "Day(s) after invoice date",
						}
					],
				}
			).insert()
		return name

	def enrol(self):
		"""Submitting the enrollment builds its payer snapshot from Program Fees,
		so set the fees up first."""
		self.student = fx.make_student()
		self.pe = fx.make_enrollment(self.student, self.program)
		pfc = frappe.db.get_value("Payers Fee Category PE", {"pf_pe": self.pe.name})
		self.assertTrue(pfc, "submitting the enrollment builds the payer snapshot")
		frappe.db.set_value("Payers Fee Category PE", pfc, "pf_custgroup", GROUP)

	def request(self, doctype, **values):
		doc = frappe.get_doc({"doctype": doctype, "student": self.student.name, **values})
		doc.name = f"ZZ-REQ-{frappe.generate_hash(length=8)}"
		doc.db_insert()
		return doc

	def pay(self, invoice):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		cash = frappe.db.get_value("Company", self.company, "default_cash_account") or frappe.db.get_value(
			"Account", {"company": self.company, "account_type": "Cash", "is_group": 0}
		)
		pe = get_payment_entry("Sales Invoice", invoice, bank_account=cash)
		pe.reference_no, pe.reference_date = "ZZ", today()
		pe.insert()
		pe.submit()
		return pe


class TestRequestFees(RequestFeesTestCase):
	def test_no_fee_set_up_charges_nothing(self):
		self.enrol()
		req = self.request(requests.TRANSCRIPT, delivery="Student", copies=1, program_enrollment=self.pe.name)
		backend = OikonomosFinancialBackend()
		self.assertEqual(backend.charge_transcript_request(req.name), [])
		self.assertEqual(backend.payment_status_for_transcript_request(req.name).si_count, 0)

	def test_a_printed_transcript_bills_per_copy_and_a_waiver_voids_it(self):
		self.with_fee(requests.TRANSCRIPT, 10)
		self.enrol()
		req = self.request(
			requests.TRANSCRIPT, delivery="Printed copy", copies=3, program_enrollment=self.pe.name
		)
		backend = OikonomosFinancialBackend()
		[invoice] = backend.charge_transcript_request(req.name)
		self.assertEqual(backend.charge_transcript_request(req.name), [])  # once
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice, "grand_total")), 30)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "custom_student"), self.student.name)
		status = backend.payment_status_for_transcript_request(req.name)
		self.assertEqual((status.invoiced, status.paid_percent), (30, 0))

		self.assertEqual(
			backend.waive_request_charges(requests.TRANSCRIPT, req.name, "Alumni courtesy"), [invoice]
		)
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 2)

	def test_an_emailed_transcript_is_one_copy(self):
		self.with_fee(requests.TRANSCRIPT, 10)
		self.enrol()
		req = self.request(requests.TRANSCRIPT, delivery="Email", copies=4, program_enrollment=self.pe.name)
		[invoice] = requests.charge_transcript_request(req.name)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice, "grand_total")), 10)

	def test_a_payment_settles_the_transcript_and_tells_seminary(self):
		self.with_fee(requests.TRANSCRIPT, 10)
		self.enrol()
		req = self.request(requests.TRANSCRIPT, delivery="Student", copies=1)  # latest enrollment
		[invoice] = requests.charge_transcript_request(req.name)
		with patch("seminary.seminary.transcripts.react_to_transcript_payment") as react:
			self.pay(invoice)
		react.assert_called_once_with(req.name)
		self.assertEqual(
			OikonomosFinancialBackend().payment_status_for_transcript_request(req.name).paid_percent, 100
		)
		# A paid fee is left for the accounts team to refund.
		self.assertEqual(requests.waive_request_charges(requests.TRANSCRIPT, req.name, "late"), [])

	def test_a_paid_fee_releases_an_awaiting_request(self):
		"""Through seminary's own callback: Awaiting Payment moves on once paid."""
		self.with_fee(requests.TRANSCRIPT, 10)
		self.enrol()
		req = self.request(requests.TRANSCRIPT, delivery="Student", copies=1, program_enrollment=self.pe.name)
		charges = requests.charge_transcript_request(req.name)
		req.db_set({"charges": "\n".join(charges), "status": "Awaiting Payment"})
		from seminary.seminary import transcripts

		self.assertEqual(transcripts.advance(req.name), "Awaiting Payment")
		with patch("seminary.seminary.transcripts.blocking_holds", return_value=[]), patch("frappe.enqueue"):
			self.pay(charges[0])
		self.assertEqual(frappe.db.get_value(requests.TRANSCRIPT, req.name, "status"), "Ready")

	def test_an_extension_bills_the_roster_s_enrollment(self):
		self.with_fee(requests.INCOMPLETE_EXTENSION, 25)
		self.enrol()
		roster = f"ZZ-SCR-{frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Scheduled Course Roster",
				"name": roster,
				"student": self.student.name,
				"program_std_scr": self.program.name,
				"active": 1,
			}
		).db_insert()
		req = self.request(requests.INCOMPLETE_EXTENSION, roster=roster, course_title="ZZ Greek")
		[invoice] = OikonomosFinancialBackend().charge_incomplete_extension(req.name)
		inv = frappe.db.get_value("Sales Invoice", invoice, ["grand_total", "seminary_trigger"], as_dict=True)
		self.assertEqual(flt(inv.grand_total), 25)
		self.assertTrue(inv.seminary_trigger.startswith(f"IER:{req.name}:"))
		self.assertEqual(requests.charge_incomplete_extension(req.name), [])  # once


class TestPayerResync(RequestFeesTestCase):
	def test_a_resync_adds_only_the_missing_fee_and_keeps_the_rest(self):
		from oikonomos.financial.payers import get_payers

		first = self.with_fee("Transcript Request", 10)
		self.enrol()
		rows = lambda: frappe.get_all(  # noqa: E731
			"pgm_enroll_payers",
			filters={"parent": self.pe.name, "parenttype": "Payers Fee Category PE"},
			fields=["fee_category", "payterm_payer"],
		)
		self.assertEqual([r.fee_category for r in rows()], [first])
		# the payment term, not the share, lands in the payer's term
		self.assertEqual(rows()[0].payterm_payer, self.terms())

		second = self.with_fee("Incomplete Extension Request", 20)
		get_payers(self.pe)  # the header exists: this used to loop forever
		get_payers(self.pe)
		self.assertEqual(sorted(r.fee_category for r in rows()), sorted([first, second]))


class TestApplicationDiscount(RequestFeesTestCase):
	"""ADR 113's ERPNext path: `_discount` prices the fee, a waiver credits it."""

	def applicant(self):
		doc = frappe.get_doc(
			{
				"doctype": "Student Applicant",
				"first_name": "ZZ",
				"last_name": "Applicant",
				"title": "ZZ Applicant",
				"program": self.program.name,
				"customer_group": GROUP,
				"student_email_id": f"zz.app.{frappe.generate_hash(length=6)}@example.test",
			}
		)
		doc.name = f"ZZ-APP-{frappe.generate_hash(length=8)}"
		doc.db_insert()
		return doc

	def discount(self, percent, source="Window"):
		return patch("seminary.seminary.admissions.application_fee_discount", return_value=(percent, source))

	def test_discount_is_clamped_and_optional(self):
		with self.discount(140):
			self.assertEqual(application._discount(frappe._dict()), (100, "Window"))
		with self.discount(-5):
			self.assertEqual(application._discount(frappe._dict())[0], 0)

	def test_a_full_discount_raises_nothing(self):
		self.with_fee("Application", 40)
		applicant = self.applicant()
		with self.discount(100):
			result = application._generate_application_invoices(applicant.name)
		self.assertEqual(result["reason"], "fee waived")
		self.assertEqual(application._application_invoices(applicant.name), [])

	def test_an_imported_application_raises_no_invoice(self):
		self.with_fee("Application", 40)
		applicant = self.applicant()
		frappe.flags.in_import = True
		try:
			application.on_applicant_insert(applicant)
		finally:
			frappe.flags.in_import = False
		self.assertEqual(application._application_invoices(applicant.name), [])

	def test_the_discount_prices_the_fee_and_a_waiver_credits_it(self):
		self.with_fee("Application", 40)
		backend = OikonomosFinancialBackend()
		self.assertTrue(backend.application_fee_configured(self.program.name))
		applicant = self.applicant()
		with self.discount(25):
			self.assertEqual(application._generate_application_invoices(applicant.name)["created"], 1)
		[invoice] = application._application_invoices(applicant.name)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice, "grand_total")), 30)
		self.assertTrue(backend.application_fee_outstanding(applicant.name))
		self.assertEqual(backend.application_fee_paid(applicant.name), 0)

		[credit] = backend.waive_application_fee(applicant.name, 100, "Hardship")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", credit, "grand_total")), -30)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")), 0)
		self.assertFalse(backend.application_fee_outstanding(applicant.name))
		self.assertEqual(backend.waive_application_fee(applicant.name, 100, "again"), [])  # once

	def test_a_partial_waiver_leaves_the_rest_to_pay(self):
		self.with_fee("Application", 40)
		applicant = self.applicant()
		with self.discount(0):
			application._generate_application_invoices(applicant.name)
		[invoice] = application._application_invoices(applicant.name)
		OikonomosFinancialBackend().waive_application_fee(applicant.name, 75, "Partner church")
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")), 10)

	def test_a_paid_fee_is_counted_and_tells_admissions(self):
		self.with_fee("Application", 40)
		applicant = self.applicant()
		with self.discount(0):
			application._generate_application_invoices(applicant.name)
		[invoice] = application._application_invoices(applicant.name)
		with patch("seminary.seminary.admissions.on_fee_settled") as settled:
			self.pay(invoice)
		settled.assert_called_once_with(applicant.name)
		self.assertEqual(OikonomosFinancialBackend().application_fee_paid(applicant.name), 40)

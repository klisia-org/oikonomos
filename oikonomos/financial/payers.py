# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Payer-snapshot construction (oikonomos billing).

Builds the `Payers Fee Category PE` header and its `pgm_enroll_payers` rows for a
Program Enrollment from the program's current `Program Fees`. This is the seam
between the academic enrollment and the trigger-invoice generators in
`oikonomos.financial.invoicing`, which bill against the snapshot.

Relocated from `seminary.seminary.api`. Seminary reaches it only through the
financial backend (`sync_enrollment_payers`), so a Frappe-only seminary builds no
payer rows. Oikonomos drives it on Program Enrollment before_submit
(`prepare_enrollment_payers`), at backfill, and from the PE form's re-sync action.
"""

import frappe


def get_payers(program_enrollment, method=None):
    pe = program_enrollment
    pen = pe.name
    active = pe.pgmenrol_active
    student = pe.student
    turn = 1
    while turn <= 2:
        if (
            not frappe.db.exists({"doctype": "Payers Fee Category PE", "pf_pe": pen})
            and turn == 1
        ):
            pfc = frappe.new_doc("Payers Fee Category PE")
            pfc.pf_pe = pen
            pfc.pf_student = student
            pfc.pf_active = active
            pfc.pf_custgroup = "Student"
            pfc.insert()
            pfc.save()
            turn += 1
        elif (
            frappe.db.exists({"doctype": "Payers Fee Category PE", "pf_pe": pen})
            and turn == 2
        ):
            get_payers_fees(pen)
            break
    return


def get_payers_fees(pen):
    pfc = frappe.get_doc({"doctype": "Payers Fee Category PE", "pf_pe": pen})

    doc = []
    doc = frappe.db.sql(
        """select pf.pgm_feecategory as feecat, pf.pgm_feeevent as event, s.customer, '1' as percentage, fc.payment_term_template as term
			from `tabProgram Enrollment`pe, `tabStudent` s, `tabProgram` p, `tabProgram Fees` pf, `tabFee Category` fc
			where pe.student = s.name and
			pe.program = p.name and
			p.name = pf.program and
			pf.pgm_feecategory = fc.name and
			pe.name = %s""",
        (pen),
        as_list=1,
    )
    row_count = frappe.db.sql(
        """select count(pf.pgm_feecategory) from `tabProgram Enrollment`pe, `tabStudent` s, `tabProgram` p, `tabProgram Fees` pf, `tabFee Category` fc
			where pe.student = s.name and
			pe.program = p.name and
			p.name = pf.program and
			pf.pgm_feecategory = fc.name and
			pe.name = %s""",
        (pen),
    )[0][0]
    i = 0
    while i < row_count:
        feecat = doc[i][0]
        event = doc[i][1]
        customer = doc[i][2]
        term = doc[i][3]
        ppe = frappe.new_doc("pgm_enroll_payers")
        ppe.parent = pen
        ppe.parentfield = "pf_payers"
        ppe.parenttype = "Payers Fee Category PE"
        ppe.fee_category = feecat
        ppe.pep_event = event
        ppe.payer = customer
        ppe.payterm_payer = term
        ppe.pay_percent = "100"
        ppe.insert()
        ppe.save()
        i += 1
    return

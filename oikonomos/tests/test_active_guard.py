# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""oikonomos bills only while it is the site's active billing app."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from oikonomos.financial import active
from oikonomos.financial.backend import OikonomosFinancialBackend
from seminary.seminary.financial.backend import NullFinancialBackend

GUARDED = {
    "extension_on_submit": "oikonomos.financial.extension.on_submit",
    "graduation_on_submit": "oikonomos.financial.graduation.on_submit",
    "prepare_enrollment_payers": "oikonomos.financial.backend.prepare_enrollment_payers",
    "on_cei_cancel": "oikonomos.financial.backend.on_cei_cancel",
    "on_applicant_insert": "oikonomos.financial.application.on_applicant_insert",
    "on_student_update": "oikonomos.financial.customer_person.on_student_update",
    "run_billing_automation": "oikonomos.financial.invoicing.run_billing_automation",
}


class TestActiveGuard(UnitTestCase):
    def _backend(self, backend):
        return patch("seminary.seminary.financial.backend.get_financial_backend", return_value=backend)

    def test_is_active_follows_the_resolver(self):
        with self._backend(OikonomosFinancialBackend()):
            self.assertTrue(active.is_active())
        with self._backend(NullFinancialBackend()):
            self.assertFalse(active.is_active())

    def test_guarded_hooks_run_only_while_active(self):
        doc = frappe._dict(name="ZZ")
        for wrapper, target in GUARDED.items():
            with patch(target) as real:
                with self._backend(NullFinancialBackend()):
                    getattr(active, wrapper)(doc, "on_submit")
                real.assert_not_called()
                with self._backend(OikonomosFinancialBackend()):
                    getattr(active, wrapper)(doc, "on_submit")
                real.assert_called_once_with(doc, "on_submit")

    def test_the_hooks_point_at_the_guards(self):
        events = frappe.get_hooks("doc_events", app_name="oikonomos")
        for doctype, event in (
            ("Graduation Request", "on_submit"),
            ("Culminating Project Extension", "on_submit"),
            ("Program Enrollment", "before_submit"),
            ("Course Enrollment Individual", "on_cancel"),
            ("Student Applicant", "after_insert"),
            ("Student", "on_update"),
        ):
            paths = events[doctype][event]
            paths = paths if isinstance(paths, list) else [paths]
            self.assertTrue(all(p.startswith("oikonomos.financial.active.") for p in paths), (doctype, paths))
        daily = frappe.get_hooks("scheduler_events", app_name="oikonomos")["daily"]
        self.assertTrue(all(p.startswith("oikonomos.financial.active.") for p in daily), daily)

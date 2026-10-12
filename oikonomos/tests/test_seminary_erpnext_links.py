# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# See license.txt
"""Seminary's links to ERPNext doctypes are oikonomos custom fields (seminary
ADR 039 addendum, 2026-10-12): seminary stays installable without ERPNext."""

import frappe
from frappe.tests import IntegrationTestCase
from seminary.seminary.tests.test_p006_api import _make_user

from oikonomos.financial import instructor


class TestSeminaryErpnextLinks(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.student = _make_user("Student", "erpl-student")
        cls.instructor = _make_user("Instructor", "erpl-instr")
        cls.chair = _make_user("Program Chair", "erpl-chair")

    def tearDown(self):
        frappe.set_user("Administrator")

    def test_links_exist_as_custom_fields(self):
        expected = {
            "Campus": {"location": "Location"},
            "Building": {"location": "Location"},
            "Room": {"location": "Location"},
            "Instructor": {"employee": "Employee", "supplier": "Supplier"},
            "Partner Organization": {"customer": "Customer"},
            "Partner Seminary": {"customer": "Customer"},
        }
        for dt, fields in expected.items():
            for fieldname, options in fields.items():
                with self.subTest(doctype=dt, field=fieldname):
                    self.assertEqual(
                        frappe.db.get_value(
                            "Custom Field", {"dt": dt, "fieldname": fieldname}, "options"
                        ),
                        options,
                    )
        self.assertTrue(
            frappe.get_meta("Seminary Settings").has_field("sync_rooms_to_asset_locations")
        )

    def test_paid_instructor_needs_an_employee(self):
        with self.assertRaises(frappe.ValidationError):
            instructor.validate(frappe._dict(instructor_type="Salaried"))
        instructor.validate(frappe._dict(instructor_type="Volunteer"))

    def test_create_supplier_is_not_self_service(self):
        for user in (self.student, self.instructor):
            frappe.set_user(user)
            with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
                instructor.create_supplier("ZZT-no-such-instructor")

    def test_create_supplier_admits_the_chair_past_the_gate(self):
        frappe.set_user(self.chair)
        with self.assertRaises(frappe.DoesNotExistError):
            instructor.create_supplier("ZZT-no-such-instructor")

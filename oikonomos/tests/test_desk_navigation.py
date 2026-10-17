# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt

"""Desk navigation (seminary decisions 088, 088a): the dock mounts on seminary and its sidebars open
only objects this app, ERPNext or Seminary own."""

import json
from pathlib import Path

from frappe.tests import UnitTestCase

PACKAGE = Path(__file__).resolve().parents[1]
APPS = PACKAGE.parents[1]
OWNERS = ("oikonomos", "erpnext", "seminary")


def _load(path):
	try:
		doc = json.loads(path.read_text())
	except (OSError, ValueError):
		return {}
	return doc if isinstance(doc, dict) else {}


def _names(doctype, folder):
	return {
		doc["name"]
		for app in OWNERS
		for path in (APPS / app).glob(f"**/{folder}/*/*.json")
		if (doc := _load(path)).get("doctype") == doctype
	}


class UnitTestDeskNavigation(UnitTestCase):
	def test_dock_mounts_on_seminary_and_opens_our_sidebar(self):
		dock = _load(PACKAGE / "dock" / "oikonomos" / "oikonomos.json")
		self.assertEqual(dock["mount_on"], "seminary")
		sidebars = {_load(p)["name"] for p in (PACKAGE / "oikonomos" / "sidebar").glob("*/*.json")}
		for row in dock["items"]:
			self.assertEqual(row["link_type"], "Sidebar")
			self.assertIn(row["link_to"], sidebars)

	def test_sidebar_links_resolve(self):
		known = {"DocType": _names("DocType", "doctype"), "Report": _names("Report", "report"),
			"Workspace": _names("Workspace", "workspace")}
		for path in (PACKAGE / "oikonomos" / "sidebar").glob("*/*.json"):
			for item in _load(path)["items"]:
				if item["type"] == "Link":
					self.assertIn(item["link_to"], known[item["link_type"]], item["label"])

	def test_reports_are_permissioned_on_a_parent_doctype(self):
		# Frappe checks report access on ref_doctype; a child table has no permissions, so the
		# report opens for Administrator only.
		import frappe

		for path in PACKAGE.glob("*/report/*/*.json"):
			report = _load(path)
			if report.get("doctype") == "Report":
				ref = report["ref_doctype"]
				self.assertFalse(frappe.db.get_value("DocType", ref, "istable"), f"{report['name']} -> {ref}")

	def test_setup_sections_open_objects_we_ship(self):
		from oikonomos import hooks

		known = _names("DocType", "doctype")
		self.assertTrue(hooks.seminary_setup_sections)
		for spec in hooks.seminary_setup_sections:
			self.assertTrue(spec["section"])
			for link in spec["links"]:
				self.assertIn(link["link_to"], known, link["label"])

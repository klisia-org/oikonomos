# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Re-own the Program Pricing desk Page relocated from seminary to oikonomos.

The page (a financial fee-schedule report) moved to the bridge. Frappe preserves
an existing record's `module` on re-import, so on sites that already had it under
Seminary the record keeps pointing there (and its roles stay the seminary set).
Re-own it to Oikonomos and add the Accounts roles. Fresh installs import it
correctly and this is a harmless no-op there.
"""

import frappe

DESIRED_ROLES = ["Program Chair", "Seminary Manager", "Accounts Manager", "Accounts User"]


def execute():
    _reown_page()
    _drop_stale_workspace_links()
    frappe.db.commit()


def _reown_page():
    if not frappe.db.exists("Page", "program-pricing"):
        return
    page = frappe.get_doc("Page", "program-pricing")
    page.module = "Oikonomos"
    existing = {r.role for r in page.roles}
    for role in DESIRED_ROLES:
        if role not in existing:
            page.append("roles", {"role": role})
    page.flags.ignore_permissions = True
    page.save()


def _drop_stale_workspace_links():
    """The seminary workspaces no longer link the (relocated) Program Pricing
    page in their files, but pre-relocation sites kept the stale Workspace Link
    in the DB (Frappe doesn't overwrite an existing workspace's links on
    migrate). Remove it so non-Accounts roles don't hit a 'no access to Page'
    error loading the workspace."""
    stale = frappe.get_all(
        "Workspace Link",
        filters={"link_type": "Page", "link_to": "program-pricing"},
        fields=["name", "parent"],
    )
    for row in stale:
        frappe.db.delete("Workspace Link", {"name": row.name})

# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Oikonomos financial backend.

Oikonomos owns every flow that touches an ERPNext doctype (Sales Invoice,
Payment Entry, Customer, ...). It implements the `FinancialBackend` interface
defined in seminary and registers it via the `seminary_financial_backend` hook,
so seminary's academic flows get real billing when oikonomos is installed and a
no-op null backend when it is not.
"""

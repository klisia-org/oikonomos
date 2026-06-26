# Copyright (c) 2026, Klisia / SeminaryERP and contributors
# For license information, please see license.txt
"""Program Pricing report (oikonomos).

Renders a per-Price-List view of every Program's fee schedule — Program Fees,
their Fee Category lookups (item, is_credit, is_audit, payment term) and the
matching Item Price. All of those (Price List, Fee Category, Program Fees, Item
Price) are ERPNext / oikonomos doctypes, so the report and its desk Page live in
the bridge; with no oikonomos installed there is nothing to price.
"""

import frappe
from frappe import _


_PROGRAM_PRICING_TEMPLATE = """
<style>
.program-pricing { font-size: 13px; margin-left: 6px; }
.program-pricing h2 { margin-top: 1.5rem; padding-bottom: 0.25rem; border-bottom: 2px solid #333; }
.program-pricing h2 .currency { font-weight: normal; color: #555; font-size: 0.85em; }
.program-pricing .customer-groups { margin: 0.5rem 0 1rem; color: #444; }
.program-pricing .program-block { margin: 1rem 0 1.5rem; padding: 0.75rem 1rem; border: 1px solid #ddd; border-radius: 4px; page-break-inside: avoid; }
.program-pricing .program-block h3 { margin: 0 0 0.5rem; font-size: 1.05rem; }
.program-pricing .program-meta { list-style: none; padding: 0; margin: 0 0 0.75rem; display: flex; flex-wrap: wrap; gap: 0.25rem 1.25rem; color: #333; }
.program-pricing .program-meta li { margin: 0; }
.program-pricing .fees-table { width: 100%; border-collapse: collapse; }
.program-pricing .fees-table th, .program-pricing .fees-table td { border: 1px solid #ddd; padding: 4px 8px; text-align: left; vertical-align: top; }
.program-pricing .fees-table th { background: #f5f5f5; font-weight: 600; }
.program-pricing .fees-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.program-pricing .not-priced { color: #c0392b; font-weight: 600; }
.program-pricing .check { color: #2e7d32; font-weight: 700; }
.program-pricing .no-fees { color: #777; font-style: italic; margin: 0; }
@media print {
  .program-pricing h2 { page-break-after: avoid; }
}
</style>
<div class="program-pricing">
{% for pl in price_lists %}
  <section class="price-list-section">
    <h2>{{ _("Price List") }}: {{ pl.name }}{% if pl.currency %} <span class="currency">— {{ _("Currency") }}: {{ pl.currency }}</span>{% endif %}</h2>
    <p class="customer-groups">
      <strong>{{ _("This price list affects the following customer groups:") }}</strong>
      {% if pl.customer_groups %}{{ pl.customer_groups | join(", ") }}{% else %}<em>{{ _("None") }}</em>{% endif %}
    </p>
    {% for program in programs %}
      <article class="program-block">
        <h3>{{ program.program_name or program.name }}</h3>
        <ul class="program-meta">
          <li><strong>{{ _("Free Program") }}:</strong> {% if program.is_free %}<span class="check">✓</span>{% else %}—{% endif %}</li>
          <li><strong>{{ _("Require Payment Before Enrollment") }}:</strong> {% if program.require_pay_submit %}<span class="check">✓</span>{% else %}—{% endif %}</li>
          <li><strong>{{ _("Minimum Payment %") }}:</strong> {{ (program.percent_to_pay or 0) }}%</li>
        </ul>
        {% if program.fees %}
        <table class="fees-table">
          <thead>
            <tr>
              <th>{{ _("Fee Category") }}</th>
              <th>{{ _("Event to charge") }}</th>
              <th>{{ _("Item") }}</th>
              <th>{{ _("Academic Credit") }}</th>
              <th>{{ _("Audit") }}</th>
              <th>{{ _("Payment Term") }}</th>
              <th>{{ _("Item Price") }}</th>
              <th>{{ _("Price last modified on") }}</th>
            </tr>
          </thead>
          <tbody>
            {% for fee in program.fees %}
              {% set price = pl.prices.get(fee.item) if fee.item else None %}
              <tr>
                <td>{{ fee.fee_category or "—" }}</td>
                <td>{{ fee.event or "—" }}</td>
                <td>{{ fee.item or "—" }}</td>
                <td>{% if fee.is_credit %}<span class="check">✓</span>{% else %}—{% endif %}</td>
                <td>{% if fee.is_audit %}<span class="check">✓</span>{% else %}—{% endif %}</td>
                <td>{{ fee.payment_term_template or "—" }}</td>
                {% if price %}
                  <td class="num">{{ "{:,.2f}".format(price.rate or 0) }}</td>
                  <td>{{ price.modified_display or "—" }}</td>
                {% else %}
                  <td class="not-priced">{{ _("Not priced") }}</td>
                  <td class="not-priced">—</td>
                {% endif %}
              </tr>
            {% endfor %}
          </tbody>
        </table>
        {% else %}
        <p class="no-fees">{{ _("No fees configured.") }}</p>
        {% endif %}
      </article>
    {% endfor %}
  </section>
{% else %}
  <p>{{ _("No selling price lists found.") }}</p>
{% endfor %}
</div>
"""


@frappe.whitelist()
def get_program_pricing_html():
    """Render the Program Pricing report (one block per selling Price List).

    Resolves: customer groups whose default_price_list = the price list,
    every Program with its Program Fees rows, the Fee Category lookups
    (item, is_credit, is_audit, payment_term_template), and the matching
    Item Price for the chosen Price List.
    """
    price_lists = frappe.get_all(
        "Price List",
        filters={"selling": 1, "enabled": 1},
        fields=["name", "currency"],
        order_by="name asc",
    )

    programs_raw = frappe.get_all(
        "Program",
        fields=[
            "name",
            "program_name",
            "is_free",
            "require_pay_submit",
            "percent_to_pay",
        ],
        order_by="program_name asc",
    )
    program_names = [p["name"] for p in programs_raw]

    fee_rows = []
    if program_names:
        fee_rows = frappe.get_all(
            "Program Fees",
            filters={"program": ["in", program_names]},
            fields=["program", "pgm_feecategory", "pgm_feeevent", "idx"],
            order_by="program asc, idx asc",
        )

    fee_category_names = sorted(
        {r["pgm_feecategory"] for r in fee_rows if r.get("pgm_feecategory")}
    )
    fee_categories = {}
    if fee_category_names:
        for fc in frappe.get_all(
            "Fee Category",
            filters={"name": ["in", fee_category_names]},
            fields=[
                "name",
                "category_name",
                "item",
                "is_credit",
                "is_audit",
                "payment_term_template",
            ],
        ):
            fee_categories[fc["name"]] = fc

    fees_by_program = {}
    referenced_items = set()
    for r in fee_rows:
        fc = fee_categories.get(r.get("pgm_feecategory")) or {}
        item = fc.get("item")
        if item:
            referenced_items.add(item)
        fees_by_program.setdefault(r["program"], []).append(
            {
                "fee_category": fc.get("category_name") or r.get("pgm_feecategory"),
                "event": r.get("pgm_feeevent"),
                "item": item,
                "is_credit": fc.get("is_credit"),
                "is_audit": fc.get("is_audit"),
                "payment_term_template": fc.get("payment_term_template"),
            }
        )

    programs = []
    for p in programs_raw:
        programs.append({**p, "fees": fees_by_program.get(p["name"], [])})

    enriched_price_lists = []
    for pl in price_lists:
        customer_groups = [
            cg["name"]
            for cg in frappe.get_all(
                "Customer Group",
                filters={"default_price_list": pl["name"]},
                fields=["name"],
                order_by="name asc",
            )
        ]

        prices = {}
        if referenced_items:
            for ip in frappe.get_all(
                "Item Price",
                filters={
                    "price_list": pl["name"],
                    "item_code": ["in", list(referenced_items)],
                },
                fields=["item_code", "price_list_rate", "modified"],
                order_by="modified desc",
            ):
                if ip["item_code"] in prices:
                    continue
                prices[ip["item_code"]] = {
                    "rate": ip.get("price_list_rate"),
                    "modified_display": frappe.utils.format_datetime(
                        ip.get("modified"), "yyyy-MM-dd HH:mm"
                    ),
                }

        enriched_price_lists.append(
            {
                "name": pl["name"],
                "currency": pl.get("currency"),
                "customer_groups": customer_groups,
                "prices": prices,
            }
        )

    return frappe.render_template(
        _PROGRAM_PRICING_TEMPLATE,
        {"price_lists": enriched_price_lists, "programs": programs},
    )

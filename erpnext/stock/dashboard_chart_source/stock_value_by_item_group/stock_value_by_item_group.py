# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from typing import Any

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils.dashboard import cache_source

from erpnext import _refuse, require_permission


@frappe.whitelist()
@cache_source
def get(
	chart_name: str | None = None,
	chart: Any = None,
	no_cache: Any = None,
	filters: dict | str | None = None,
	from_date: Any = None,
	to_date: Any = None,
	timespan: Any = None,
	time_interval: Any = None,
	heatmap_year: Any = None,
):
	"""
	Return the stock value by item group chart, after checking select on the company and on Warehouse, which
	every role that owns the chart holds.
	"""
	if filters and isinstance(filters, str):
		filters = frappe.parse_json(filters)

	company = filters.get("company") if filters else None
	if not company:
		company = frappe.defaults.get_defaults().company

	if company:
		require_permission("Company", company, "select")
	if not frappe.has_permission("Warehouse", "select"):
		_refuse()

	labels, datasets = get_stock_value_by_item_group(company)

	return {
		"labels": labels,
		"datasets": [{"name": _("Stock Value"), "values": datasets}],
	}


def get_stock_value_by_item_group(company):
	"""
	Return the top item groups by stock value across the warehouses the current user can read, returning no
	figures at all when no warehouse is readable.
	"""
	doctype = frappe.qb.DocType("Bin")
	item_doctype = frappe.qb.DocType("Item")

	warehouse_filters = [["is_group", "=", 0]]
	if company:
		warehouse_filters.append(["company", "=", company])

	warehouses = frappe.get_list("Warehouse", pluck="name", filters=warehouse_filters)

	if not warehouses:
		return [], []

	stock_value = Sum(doctype.stock_value)

	query = (
		frappe.qb.from_(doctype)
		.inner_join(item_doctype)
		.on(doctype.item_code == item_doctype.name)
		.select(item_doctype.item_group, stock_value.as_("stock_value"))
		.groupby(item_doctype.item_group)
		.orderby(stock_value, order=frappe.qb.desc)
		.limit(10)
	)

	query = query.where(doctype.warehouse.isin(warehouses))

	results = query.run(as_dict=True)

	labels = []
	datapoints = []

	for row in results:
		if not row.stock_value:
			continue

		labels.append(_(row.item_group))
		datapoints.append(row.stock_value)

	return labels, datapoints

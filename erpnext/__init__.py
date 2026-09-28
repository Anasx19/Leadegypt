import functools
import inspect

import frappe
from frappe.utils.user import is_website_user

__version__ = "15.112.0"


def get_default_company(user=None):
	"""Get default company for user"""
	from frappe.defaults import get_user_default_as_list

	if not user:
		user = frappe.session.user

	companies = get_user_default_as_list("company", user)
	if companies:
		default_company = companies[0]
	else:
		default_company = frappe.db.get_single_value("Global Defaults", "default_company")

	return default_company


def get_default_currency():
	"""Returns the currency of the default company"""
	company = get_default_company()
	if company:
		return frappe.get_cached_value("Company", company, "default_currency")


def get_default_cost_center(company):
	"""Returns the default cost center of the company"""
	if not company:
		return None

	if not frappe.flags.company_cost_center:
		frappe.flags.company_cost_center = {}
	if company not in frappe.flags.company_cost_center:
		frappe.flags.company_cost_center[company] = frappe.get_cached_value("Company", company, "cost_center")
	return frappe.flags.company_cost_center[company]


def get_company_currency(company):
	"""Returns the default company currency"""
	if not frappe.flags.company_currency:
		frappe.flags.company_currency = {}
	if company not in frappe.flags.company_currency:
		frappe.flags.company_currency[company] = frappe.db.get_value(
			"Company", company, "default_currency", cache=True
		)
	return frappe.flags.company_currency[company]


def set_perpetual_inventory(enable=1, company=None):
	if not company:
		company = "_Test Company" if frappe.flags.in_test else get_default_company()

	company = frappe.get_doc("Company", company)
	company.enable_perpetual_inventory = enable
	company.save()


def encode_company_abbr(name, company=None, abbr=None):
	"""Returns name encoded with company abbreviation"""
	company_abbr = abbr or frappe.get_cached_value("Company", company, "abbr")
	parts = name.rsplit(" - ", 1)

	if parts[-1].lower() != company_abbr.lower():
		parts.append(company_abbr)

	return " - ".join(parts)


def is_perpetual_inventory_enabled(company):
	if not company:
		company = "_Test Company" if frappe.flags.in_test else get_default_company()

	if not hasattr(frappe.local, "enable_perpetual_inventory"):
		frappe.local.enable_perpetual_inventory = {}

	if company not in frappe.local.enable_perpetual_inventory:
		frappe.local.enable_perpetual_inventory[company] = (
			frappe.get_cached_value("Company", company, "enable_perpetual_inventory") or 0
		)

	return frappe.local.enable_perpetual_inventory[company]


def get_default_finance_book(company=None):
	if not company:
		company = get_default_company()

	if not hasattr(frappe.local, "default_finance_book"):
		frappe.local.default_finance_book = {}

	if company not in frappe.local.default_finance_book:
		frappe.local.default_finance_book[company] = frappe.get_cached_value(
			"Company", company, "default_finance_book"
		)

	return frappe.local.default_finance_book[company]


def get_party_account_type(party_type):
	if not hasattr(frappe.local, "party_account_types"):
		frappe.local.party_account_types = {}

	if party_type not in frappe.local.party_account_types:
		frappe.local.party_account_types[party_type] = (
			frappe.db.get_value("Party Type", party_type, "account_type") or ""
		)

	return frappe.local.party_account_types[party_type]


def get_region(company=None):
	"""Return the default country based on flag, company or global settings

	You can also set global company flag in `frappe.flags.company`
	"""

	if not company:
		company = frappe.local.flags.company

	if company:
		return frappe.get_cached_value("Company", company, "country")

	return frappe.flags.country or frappe.get_system_settings("country")


def allow_regional(fn):
	"""Decorator to make a function regionally overridable

	Example:
	@erpnext.allow_regional
	def myfunction():
	  pass"""

	@functools.wraps(fn)
	def caller(*args, **kwargs):
		overrides = frappe.get_hooks("regional_overrides", {}).get(get_region())
		function_path = f"{inspect.getmodule(fn).__name__}.{fn.__name__}"

		if not overrides or function_path not in overrides:
			return fn(*args, **kwargs)

		# Priority given to last installed app
		return frappe.get_attr(overrides[function_path][-1])(*args, **kwargs)

	return caller


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True

	if is_website_user():
		return False

	return True


def get_unwritable_doctype(names_by_doctype):
	"""Return the first doctype in the mapping holding a name the current user may not write, or None when
	every requested voucher is writable, checking the whole batch."""
	writable = get_writable_vouchers(_get_voucher_pairs(names_by_doctype))
	for doctype, names in names_by_doctype.items():
		if not _are_all_writable(doctype, names, writable):
			return doctype
	return None


def _get_voucher_pairs(names_by_doctype):
	"""Flatten a mapping of doctype to voucher names into (doctype, name) pairs, turning a malformed name
	into None so it can be hashed and is never writable."""
	pairs = []
	for doctype, names in names_by_doctype.items():
		for name in names:
			pairs.append((doctype, get_record_name(name)))
	return pairs


def _are_all_writable(doctype, names, writable):
	"""Return whether every one of the names under this doctype appears in the set of (doctype, name)
	pairs the current user was confirmed to be able to write."""
	for name in names:
		if (doctype, get_record_name(name)) not in writable:
			return False
	return True


def get_writable_vouchers(vouchers, ptype="write"):
	"""Return the (doctype, name) pairs the current user may write, or hold the given ptype on, checking
	each record and dropping an empty or missing name quietly."""
	writable = set()
	for doctype, name in vouchers:
		if _is_writable_voucher(doctype, name, ptype):
			writable.add((doctype, name))
	return writable


def _is_writable_voucher(doctype, name, ptype="write"):
	"""Return whether the voucher exists and the current user holds the ptype on it; existence is checked
	first because has_permission admits Administrator without loading it."""
	if not doctype:
		return False
	if not get_record_name(name):
		return False
	if not frappe.db.exists(doctype, name):
		return False
	return _is_permitted(doctype, name, ptype)


def require_user_permission(doctype, name):
	"""Raise PermissionError unless the caller's User Permissions admit the named record; this checks the
	fence only, not whether the caller's roles grant the doctype."""
	if not _is_within_user_permissions(doctype, name):
		_refuse()


def _is_within_user_permissions(doctype, name):
	"""Return whether the caller's User Permissions admit the named record, treating an empty or missing
	name as refused and keeping the check's messages out of the response."""
	from frappe.permissions import has_user_permission

	if not get_record_name(name):
		return False
	saved_messages = frappe.get_message_log()
	frappe.clear_messages()
	try:
		return has_user_permission(frappe.get_doc(doctype, name), frappe.session.user)
	except frappe.DoesNotExistError:
		return False
	finally:
		frappe.local.message_log = saved_messages


def require_permission(doctype, name, ptype="read"):
	"""Raise PermissionError unless the caller may use the named record for this ptype; an empty, missing,
	malformed or forbidden name is refused the same way."""
	if not _is_permitted(doctype, name, ptype):
		_refuse()


def _is_permitted(doctype, name, ptype):
	"""Return whether the caller may use the named record for this ptype, treating an empty or missing name
	as refused and keeping the check's messages out of the response."""
	if not get_record_name(name):
		return False
	saved_messages = frappe.get_message_log()
	frappe.clear_messages()
	try:
		return _has_permission_or_read(doctype, name, ptype)
	except frappe.DoesNotExistError:
		return False
	finally:
		frappe.local.message_log = saved_messages


def _has_permission_or_read(doctype, name, ptype):
	"""Check the ptype on the record, letting read satisfy select as newer frappe does, because released
	v15 frappe has no select-implies-read fallback."""
	if frappe.has_permission(doctype, ptype, doc=name):
		return True
	if ptype != "select":
		return False
	return frappe.has_permission(doctype, "read", doc=name)


def _refuse():
	"""Raise frappe's constant permission error without a traceback, so every refused record looks identical
	and the response never names the doctype or the record."""
	frappe.flags.disable_traceback = True
	# v15 frappe has no throw_permission_error; this is the call it wraps on newer frappe
	frappe.throw(frappe._("Not permitted"), frappe.PermissionError)


def get_record_name(value):
	"""Return the value when it names a record the way frappe.has_permission reads one, a string or
	integer, and None for a dict, list or anything usable as filters."""
	if isinstance(value, bool):
		return None
	if isinstance(value, str | int):
		return value
	return None

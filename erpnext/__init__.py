import functools
import inspect
from typing import TypeVar

import frappe
from frappe.model.document import Document
from frappe.utils.user import is_website_user

__version__ = "16.26.2"


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
		company = "_Test Company" if frappe.in_test else get_default_company()

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
		company = "_Test Company" if frappe.in_test else get_default_company()

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


T = TypeVar("T")


def normalize_ctx_input(T: type) -> callable:
	"""
	Normalizes the first argument (ctx) of the decorated function by:
	- Converting Document objects to dictionaries
	- Parsing JSON strings
	- Casting the result to the specified type T
	"""

	def decorator(func: callable):
		# conserve annotations for frappe.utils.typing_validations
		@functools.wraps(
			func,
			assigned=(
				a for a in functools.WRAPPER_ASSIGNMENTS if a not in ("__annotations__", "__annotate__")
			),
		)
		def wrapper(ctx: T | Document | dict | str, *args, **kwargs):
			if isinstance(ctx, Document):
				ctx = T(**ctx.as_dict())
			elif isinstance(ctx, dict):
				ctx = T(**ctx)
			else:
				ctx = T(**frappe.parse_json(ctx))

			return func(ctx, *args, **kwargs)

		# set annotations from function
		wrapper.__annotations__.update({k: v for k, v in func.__annotations__.items() if k != "ctx"})
		return wrapper

	return decorator


def get_unwritable_doctype(names_by_doctype: dict) -> str | None:
	"""
	Return the first doctype in `names_by_doctype` holding a name the current user may not write, or None
	when every requested voucher is writable, checking the whole batch at once.
	"""
	writable = get_writable_vouchers(_get_voucher_pairs(names_by_doctype))
	for doctype, names in names_by_doctype.items():
		if not _are_all_writable(doctype, names, writable):
			return doctype
	return None


def _get_voucher_pairs(names_by_doctype: dict) -> list:
	"""
	Flatten a mapping of doctype to voucher names into a list of (doctype, name) pairs, the shape
	get_writable_vouchers expects for a batch of vouchers.
	"""
	pairs = []
	for doctype, names in names_by_doctype.items():
		for name in names:
			pairs.append((doctype, name))
	return pairs


def _are_all_writable(doctype: str, names, writable: set) -> bool:
	"""
	Return whether every one of `names` under `doctype` appears in `writable`, the set of (doctype, name)
	pairs the current user was confirmed to be able to write.
	"""
	for name in names:
		if (doctype, name) not in writable:
			return False
	return True


def get_writable_vouchers(vouchers, ptype: str = "write") -> set:
	"""
	Return the (doctype, name) pairs from `vouchers` that the current user may `ptype`, checking each record
	with frappe.has_permission and treating an empty or missing name as refused.
	"""
	writable = set()
	for doctype, name in vouchers:
		if _is_writable_voucher(doctype, name, ptype):
			writable.add((doctype, name))
	return writable


def _is_writable_voucher(doctype: str, name, ptype: str = "write") -> bool:
	"""
	Return whether the voucher exists and the current user may `ptype` it; the existence check comes first
	because has_permission admits Administrator without loading the record.
	"""
	if not doctype:
		return False
	if not get_record_name(name):
		return False
	if not frappe.db.exists(doctype, name):
		return False
	return _is_permitted(doctype, name, ptype)


def require_user_permission(doctype: str, name: str | int | None) -> None:
	"""
	Raise PermissionError unless the caller's User Permissions admit the named record; this checks the fence
	only, not whether the caller's roles grant the doctype.
	"""
	if not _is_within_user_permissions(doctype, name):
		_refuse()


def _is_within_user_permissions(doctype: str, name: str | int | None) -> bool:
	"""
	Return whether the caller's User Permissions admit the named record, treating an empty or missing name
	as refused and keeping the check's messages out of the response.
	"""
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


def require_permission(doctype: str, name: str | int | None, ptype: str = "read") -> None:
	"""
	Raise PermissionError unless the caller may `ptype` the named record; an empty, missing or forbidden name
	is refused the same way, without logging the record.
	"""
	if not _is_permitted(doctype, name, ptype):
		_refuse()


def _is_permitted(doctype: str, name: str | int | None, ptype: str) -> bool:
	"""
	Return whether the caller may `ptype` the named record, treating an empty or missing name as refused and
	keeping the check's messages out of the response.
	"""
	if not get_record_name(name):
		return False
	saved_messages = frappe.get_message_log()
	frappe.clear_messages()
	try:
		return frappe.has_permission(doctype, ptype, doc=name)
	except frappe.DoesNotExistError:
		return False
	finally:
		frappe.local.message_log = saved_messages


def _refuse() -> None:
	"""
	Raise frappe's constant permission error without a traceback, so every refused record looks identical and
	the response never names the doctype or the record.
	"""
	frappe.flags.disable_traceback = True
	frappe.throw_permission_error()


def get_record_name(value) -> str | int | None:
	"""
	Return `value` when it names a record the way frappe.has_permission reads one, a string or integer,
	and None for a dict, list or other value that could act as filters.
	"""
	if isinstance(value, bool):
		return None
	if isinstance(value, str | int):
		return value
	return None

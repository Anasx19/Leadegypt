import frappe
from frappe.utils import cint

from erpnext.patches.v16_0.mirror_release_perms_to_custom_docperm import (
	GRANTS,
	get_grant_flags,
	removed_roles,
)

DOCTYPE = "Payment Terms Template"
SAVEPOINT = "remove_all_role_from_payment_terms_template"
SHIPPED_ALL_RIGHTS = ("select", "report", "export", "print", "email", "share")


def execute():
	"""
	Remove the All rule this release drops from a customised Payment Terms Template, only when it is an
	unchanged shipped copy and every granted role holds its rule.
	"""
	grant_flags = get_grant_flags()
	rules = get_all_role_rules(grant_flags)
	if not rules:
		return
	blocking_role = get_blocking_role()
	if blocking_role:
		report_blocking_role(blocking_role)
		return
	for rule in rules:
		remove_if_unchanged(rule, grant_flags)


def get_all_role_rules(grant_flags: list) -> list:
	"""
	Return the level-0 Custom DocPerm rules granting All on Payment Terms Template, with the creator-only flag
	and every grant flag needed to tell whether the site changed them.
	"""
	return frappe.get_all(
		"Custom DocPerm",
		filters={"parent": DOCTYPE, "role": "All", "permlevel": 0},
		fields=["name", "if_owner", *grant_flags],
	)


def get_blocking_role() -> str | None:
	"""
	Return the first role this release grants on Payment Terms Template without a full rule for its right,
	skipping roles absent from the site and rules the site deliberately deleted.
	"""
	removed = removed_roles(DOCTYPE)
	for role, ptypes in GRANTS[DOCTYPE].items():
		if not frappe.db.exists("Role", role):
			continue
		if role in removed:
			continue
		if not has_full_rule(role, ptypes):
			return role
	return None


def has_full_rule(role: str, ptypes: tuple) -> bool:
	"""
	Return whether the role holds a level-0 Custom DocPerm rule on Payment Terms Template that grants every
	type in `ptypes` on all records, not only those the user created.
	"""
	rule = get_full_rule(role, ptypes)
	if not rule:
		return False
	for ptype in ptypes:
		if not cint(rule.get(ptype)):
			return False
	return True


def get_full_rule(role: str, ptypes: tuple):
	"""
	Return the role's level-0 Custom DocPerm rule on Payment Terms Template that applies to every record,
	with the `ptypes` flags, or None when only a creator-only rule exists.
	"""
	return frappe.db.get_value(
		"Custom DocPerm",
		{"parent": DOCTYPE, "role": role, "permlevel": 0, "if_owner": 0},
		list(ptypes),
		as_dict=True,
	)


def report_blocking_role(role: str):
	"""
	Print that the All rule was kept because the role's rule on Payment Terms Template does not grant its
	shipped rights on every record, naming the role and the rights.
	"""
	rights = ", ".join(GRANTS[DOCTYPE][role])
	print(f"{DOCTYPE} / All: kept, the {role} rule does not grant {rights} on every record")


def remove_if_unchanged(rule, grant_flags: list):
	"""
	Remove the All rule only when it is an exact copy of the old shipped rule no admin has edited; any other
	rule records the site's choice.
	"""
	if not is_unchanged_copy(rule, grant_flags):
		print(f"{DOCTYPE} / All: kept, this site changed the rule")
		return
	remove_rule(rule.name)


def is_unchanged_copy(rule, grant_flags: list) -> bool:
	"""
	Return whether the All rule still has exactly the shipped rights and Permission Log shows no admin edit to
	it, so removing it undoes no site choice.
	"""
	if not is_shipped_copy(rule, grant_flags):
		return False
	return not has_update_log(rule.name)


def is_shipped_copy(rule, grant_flags: list) -> bool:
	"""
	Return whether the rule applies to every record and grants exactly the rights the All rule on Payment
	Terms Template shipped with before this release, nothing more or less.
	"""
	if cint(rule.if_owner):
		return False
	for flag in grant_flags:
		expected = 1 if flag in SHIPPED_ALL_RIGHTS else 0
		if cint(rule.get(flag)) != expected:
			return False
	return True


def has_update_log(rule_name: str) -> bool:
	"""
	Return whether Permission Log records an admin editing this Custom DocPerm rule; an insert from copying
	the shipped rules logs Added and does not count.
	"""
	return bool(
		frappe.db.exists(
			"Permission Log",
			{"reference_type": "Custom DocPerm", "reference": rule_name, "status": "Updated"},
		)
	)


def remove_rule(rule_name: str):
	"""
	Delete the Custom DocPerm rule and clear the doctype's cache, printing the removal because migrate writes
	no Permission Log entry; a failure is rolled back and logged.
	"""
	try:
		frappe.db.savepoint(SAVEPOINT)
		frappe.delete_doc("Custom DocPerm", rule_name, ignore_permissions=True)
		frappe.clear_cache(doctype=DOCTYPE)
		print(f"{DOCTYPE} / All: removed")
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(
			title="Could not remove permission", message=f"{DOCTYPE} / All\n\n{frappe.get_traceback()}"
		)

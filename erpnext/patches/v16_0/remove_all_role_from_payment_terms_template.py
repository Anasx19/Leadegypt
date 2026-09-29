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
	Remove the All rule this release drops from a customised Payment Terms Template, only where it is an
	unedited copy of the shipped rule and every granted role holds its own.
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
	and every grant flag needed to compare them with the shipped rule.
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
	Return whether any of the role's level-0 Custom DocPerm rules on Payment Terms Template grants every type
	in `ptypes` on all records, not only those the user created.
	"""
	for rule in get_full_rules(role, ptypes):
		if grants_all(rule, ptypes):
			return True
	return False


def get_full_rules(role: str, ptypes: tuple) -> list:
	"""
	Return every level-0 Custom DocPerm rule the role holds on Payment Terms Template that applies to all
	records, with the `ptypes` flags; creator-only rules are left out.
	"""
	return frappe.get_all(
		"Custom DocPerm",
		filters={"parent": DOCTYPE, "role": role, "permlevel": 0, "if_owner": 0},
		fields=list(ptypes),
	)


def grants_all(rule, ptypes: tuple) -> bool:
	"""
	Return whether one Custom DocPerm rule turns on every permission type in `ptypes`, so the role reaches
	the records it needs through that single rule.
	"""
	for ptype in ptypes:
		if not cint(rule.get(ptype)):
			return False
	return True


def report_blocking_role(role: str):
	"""
	Print that the All rule was kept because the role's rule on Payment Terms Template does not grant its
	shipped rights on every record, naming the role and the rights.
	"""
	rights = ", ".join(GRANTS[DOCTYPE][role])
	print(f"{DOCTYPE} / All: kept, the {role} rule does not grant {rights} on every record")


def remove_if_unchanged(rule, grant_flags: list):
	"""
	Remove the All rule only when it is an exact copy of the shipped rule that no administrator edited; any
	other All rule records a choice the site made, so it is kept.
	"""
	if not is_shipped_copy(rule, grant_flags) or has_update_log(rule.name):
		print(f"{DOCTYPE} / All: kept, this site changed the rule")
		return
	remove_rule(rule.name)


def is_shipped_copy(rule, grant_flags: list) -> bool:
	"""
	Return whether the rule applies to every record and grants exactly the rights the All rule shipped with
	before this release, no more and no fewer.
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
	Return whether Permission Log records an edit to this Custom DocPerm rule; migrate writes no log, so an
	entry marks a change an administrator made.
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

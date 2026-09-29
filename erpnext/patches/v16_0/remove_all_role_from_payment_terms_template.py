import frappe
from frappe.utils import cint

from erpnext.patches.v16_0.mirror_release_perms_to_custom_docperm import GRANTS, get_grant_flags

DOCTYPE = "Payment Terms Template"
SAVEPOINT = "remove_all_role_from_payment_terms_template"
SHIPPED_ALL_RIGHTS = ("select", "report", "export", "print", "email", "share")


def execute():
	"""Remove the All rule this release drops from a customised Payment Terms Template, only while it is an
	unchanged copy and every granted role holds its rule."""
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


def get_all_role_rules(grant_flags):
	"""Return the level-0 Custom DocPerm rules granting All on Payment Terms Template, with the owner flag
	and every grant flag needed to recognise an unchanged copy."""
	return frappe.get_all(
		"Custom DocPerm",
		filters={"parent": DOCTYPE, "role": "All", "permlevel": 0},
		fields=["name", "if_owner", *grant_flags],
	)


def get_blocking_role():
	"""Return the first granted role present on this site that lacks a rule granting its shipped rights on
	every record, or None when all are in place."""
	# v15 has no Permission Log, so a rule the site deleted still blocks removal here
	for role, ptypes in GRANTS[DOCTYPE].items():
		if not frappe.db.exists("Role", role):
			continue
		if not has_full_rule(role, ptypes):
			return role
	return None


def has_full_rule(role, ptypes):
	"""Return whether the role holds a level-0 rule, not limited to its own records, that grants every
	ptype this release ships for it on Payment Terms Template."""
	rule = get_full_rule(role, ptypes)
	if not rule:
		return False
	for ptype in ptypes:
		if not cint(rule.get(ptype)):
			return False
	return True


def get_full_rule(role, ptypes):
	"""Return the role's level-0 rule on Payment Terms Template that is not limited to its own records, with
	the shipped ptypes, or None when there is none."""
	return frappe.db.get_value(
		"Custom DocPerm",
		{"parent": DOCTYPE, "role": role, "permlevel": 0, "if_owner": 0},
		list(ptypes),
		as_dict=True,
	)


def report_blocking_role(role):
	"""Print that the All rule was kept because a granted role lacks its shipped rights on every record, so
	removing All could strand that role."""
	rights = ", ".join(GRANTS[DOCTYPE][role])
	print(f"{DOCTYPE} / All: kept, the {role} rule does not grant {rights} on every record")


def remove_if_unchanged(rule, grant_flags):
	"""Remove an All rule only when it is an exact copy of the row earlier releases shipped; a rule the site
	changed in any way is kept and reported."""
	if not is_shipped_all_copy(rule, grant_flags):
		print(f"{DOCTYPE} / All: kept, this site changed the rule")
		return
	remove_rule(rule.name)


def is_shipped_all_copy(rule, grant_flags):
	"""Return whether the rule matches the old shipped All row exactly: not owner-only, the six shipped
	rights set, and every other grant flag clear."""
	if cint(rule.if_owner):
		return False
	for flag in grant_flags:
		expected = 1 if flag in SHIPPED_ALL_RIGHTS else 0
		if cint(rule.get(flag)) != expected:
			return False
	return True


def remove_rule(rule_name):
	"""Delete the Custom DocPerm rule through frappe.delete_doc and print the removal, rolling back and
	logging instead of stopping the migration on failure."""
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

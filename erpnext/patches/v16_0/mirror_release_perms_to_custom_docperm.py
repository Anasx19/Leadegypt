import json

import frappe
from frappe.utils import cint

GRANTS = {
	"Payment Terms Template": {
		"Maintenance Manager": ("read",),
		"Maintenance User": ("read",),
		"Manufacturing Manager": ("read",),
		"Purchase Manager": ("read",),
		"Purchase User": ("read",),
		"Sales Manager": ("read",),
		"Sales User": ("read",),
		"HR Manager": ("select",),
		"Purchase Master Manager": ("select",),
		"Sales Master Manager": ("select",),
	},
	"Payment Term": {
		"Manufacturing Manager": ("select",),
	},
	"Serial and Batch Bundle": {
		"Sales User": ("select",),
	},
	"POS Invoice": {
		"Sales Manager": ("read",),
		"Sales User": ("read",),
	},
	"Asset": {
		"Accounts Manager": ("select",),
	},
}

PTYPES = (
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
)

NON_GRANT_FLAGS = ("if_owner", "is_app_disabled")

SAVEPOINT = "mirror_release_perms_to_custom_docperm"


def execute():
	"""
	Mirror this release's new permission rows onto doctypes with Custom DocPerm rows, inserting only for roles
	with no rule and no admin history, never changing an existing rule.
	"""
	if not frappe.db.exists("DocType", "Permission Log"):
		print(
			"mirror_release_perms_to_custom_docperm: Permission Log is not installed on this site, "
			"so a rule that was created and later deleted cannot be told apart from one that never "
			"existed. Skipping rather than re-granting a rule the site may have removed."
		)
		return

	for doctype, roles in GRANTS.items():
		if has_custom_perms(doctype):
			mirror_doctype(doctype, roles)


def has_custom_perms(doctype: str) -> bool:
	"""
	Return whether `doctype` exists on this site and already carries Custom DocPerm rows, the only case where
	shipped permission rows are ignored and must be mirrored.
	"""
	if not frappe.db.exists("DocType", doctype):
		return False
	return bool(frappe.db.exists("Custom DocPerm", {"parent": doctype}))


def mirror_doctype(doctype: str, roles: dict):
	"""
	Mirror each role's grant onto the customised `doctype`, leaving roles an admin changed alone, and clear the
	doctype's cache when at least one rule was added.
	"""
	changed = changed_roles(doctype)
	added = False
	for role, ptypes in roles.items():
		if mirror_role(doctype, role, ptypes, changed):
			added = True
	if added:
		frappe.clear_cache(doctype=doctype)


def mirror_role(doctype: str, role: str, ptypes: tuple, changed: set) -> bool:
	"""
	Insert the role's rule only when it has no level-0 rule and no admin history on `doctype`; report an
	existing rule that falls short instead of changing it.
	"""
	if not frappe.db.exists("Role", role):
		return False
	rules = get_existing_rules(doctype, role)
	if rules:
		report_short_rules(doctype, role, ptypes, rules)
		return False
	if role in changed:
		print(f"{doctype} / {role}: skipped, this site changed the rule")
		return False
	return insert_rule(doctype, role, ptypes)


def report_short_rules(doctype: str, role: str, ptypes: tuple, rules: list):
	"""
	Print that the role's existing rules were kept as the site set them when none grants `ptypes` on every
	record, so the shortfall shows in the migrate log.
	"""
	if not has_full_rule(rules, ptypes):
		print(f"{doctype} / {role}: kept, the site's rule does not grant {', '.join(ptypes)}")


def has_full_rule(rules: list, ptypes: tuple) -> bool:
	"""
	Return whether any of the role's rules applies to every record and grants every permission type in
	`ptypes`, so the role reaches all records.
	"""
	for rule in rules:
		if cint(rule.if_owner):
			continue
		if not get_missing_ptypes(ptypes, rule):
			return True
	return False


def changed_roles(doctype: str) -> set:
	"""
	Return the roles whose rule on `doctype` Permission Log shows an admin updating or deleting, a choice the
	site made that this patch must never override.
	"""
	return get_logged_roles(doctype, ("Removed", "Updated"))


def removed_roles(doctype: str) -> set:
	"""
	Return the roles whose rule on `doctype` this site created and later deleted, read from Permission Log, so
	a deliberately removed rule is never re-granted.
	"""
	return get_logged_roles(doctype, ("Removed",))


def get_logged_roles(doctype: str, statuses: tuple) -> set:
	"""
	Return the roles named by level-0 Custom DocPerm entries on `doctype` in Permission Log with one of
	`statuses`, skipping entries that cannot be read.
	"""
	roles = set()
	for changes in get_role_logs(doctype, statuses):
		role = get_logged_role(changes)
		if role:
			roles.add(role)
	return roles


def get_role_logs(doctype: str, statuses: tuple) -> list:
	"""
	Return the changes JSON of every Permission Log entry recording a Custom DocPerm row on `doctype` with one
	of `statuses`, the trail an admin's edit leaves behind.
	"""
	return frappe.get_all(
		"Permission Log",
		filters={
			"for_doctype": "DocType",
			"for_document": doctype,
			"reference_type": "Custom DocPerm",
			"status": ("in", list(statuses)),
		},
		pluck="changes",
	)


def get_logged_role(changes: str) -> str | None:
	"""
	Return the role named by one Permission Log entry when the rule was level 0 or its level was not recorded,
	or None for unreadable entries and higher levels.
	"""
	before = get_previous_values(changes)
	if cint(before.get("permlevel")):
		return None
	return before.get("role")


def get_previous_values(changes: str) -> dict:
	"""
	Return the `from` values recorded in a Permission Log entry's changes JSON, or an empty dict when the
	entry cannot be parsed, so it names no role.
	"""
	try:
		logged = json.loads(changes) or {}
	except (TypeError, ValueError):
		return {}
	return logged.get("from") or {}


def get_existing_rules(doctype: str, role: str) -> list:
	"""
	Return the role's level-0 Custom DocPerm rules on `doctype` with their name, creator-only flag and every
	grant flag the site's table carries.
	"""
	return frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": role, "permlevel": 0},
		fields=["name", "if_owner", *get_grant_flags()],
	)


def get_grant_flags() -> list:
	"""
	Return the Custom DocPerm check fields that grant a right and exist as columns on this site, including
	permission types the site defined, so no unknown flag breaks a query.
	"""
	flags = []
	for field in frappe.get_meta("Custom DocPerm").fields:
		if field.fieldtype != "Check":
			continue
		if field.fieldname in NON_GRANT_FLAGS:
			continue
		if frappe.db.has_column("Custom DocPerm", field.fieldname):
			flags.append(field.fieldname)
	return flags


def get_missing_ptypes(ptypes: tuple, existing) -> list:
	"""
	Return the permission types from `ptypes` that the existing Custom DocPerm row does not grant yet, in
	the order they are listed in the release's grant.
	"""
	missing = []
	for ptype in ptypes:
		if not existing.get(ptype):
			missing.append(ptype)
	return missing


def insert_rule(doctype: str, role: str, ptypes: tuple) -> bool:
	"""
	Insert a level-0 Custom DocPerm row granting exactly `ptypes` to the role on `doctype`, and return
	whether it was written; a failure is rolled back and logged.
	"""
	try:
		frappe.db.savepoint(SAVEPOINT)
		row = frappe.new_doc("Custom DocPerm")
		row.update(get_new_rule_values(doctype, role, ptypes))
		row.insert(ignore_permissions=True)
		return True
	except Exception:
		log_failure("Could not add read permission", doctype, role)
		return False


def get_new_rule_values(doctype: str, role: str, ptypes: tuple) -> dict:
	"""
	Return the field values for a new level-0 Custom DocPerm row, setting every permission flag explicitly
	because Custom DocPerm defaults read and export to on.
	"""
	values = {
		"parent": doctype,
		"parenttype": "DocType",
		"parentfield": "permissions",
		"role": role,
		"permlevel": 0,
		"if_owner": 0,
		"select": 1 if "select" in ptypes else 0,
	}
	for ptype in PTYPES:
		values[ptype] = 1 if ptype in ptypes else 0
	return values


def log_failure(title: str, doctype: str, role: str):
	"""
	Roll back to the savepoint before logging, because a failed statement leaves a Postgres transaction
	unusable, then record the error with the doctype and role.
	"""
	frappe.db.rollback(save_point=SAVEPOINT)
	frappe.log_error(title=title, message=f"{doctype} / {role}\n\n{frappe.get_traceback()}")

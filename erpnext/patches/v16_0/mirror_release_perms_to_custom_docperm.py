import json

import frappe
from frappe.utils import cint

GRANTS = {
	"Payment Terms Template": {
		"Maintenance Manager": ("read",),
		"Maintenance User": ("read",),
		"Purchase Manager": ("read",),
		"Purchase User": ("read",),
		"Sales Manager": ("read",),
		"Sales User": ("read",),
		"HR Manager": ("select",),
		"Purchase Master Manager": ("select",),
		"Sales Master Manager": ("select",),
	},
	"POS Invoice": {
		"Sales Manager": ("read",),
		"Sales User": ("read",),
	},
	"Serial and Batch Bundle": {
		"Sales Manager": ("select",),
		"Sales User": ("select",),
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

# The rights the previous release (v16.36.1) shipped for each GRANTS pair whose shipped rule this release
# changes. A customised site's untouched copy of that rule is widened to this release's grant.
PREVIOUS_SHIPPED_RULES = {
	("POS Invoice", "Sales Manager"): ("select",),
	("POS Invoice", "Sales User"): ("select",),
}

NON_GRANT_FLAGS = ("if_owner", "is_app_disabled")

SAVEPOINT = "mirror_release_perms_to_custom_docperm"


def execute():
	"""
	Add this release's new permission rules to doctypes with Custom DocPerm rows for pairs the site never ruled
	on, and widen only untouched copies of the previous release's rule.
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
	Mirror each role's grant onto the customised `doctype`, skipping pairs an administrator changed, and clear
	the doctype's cache when at least one rule was added.
	"""
	changed = get_changed_roles(doctype)
	added = False
	for role, ptypes in roles.items():
		if mirror_role(doctype, role, ptypes, changed):
			added = True
	if added:
		frappe.clear_cache(doctype=doctype)


def mirror_role(doctype: str, role: str, ptypes: tuple, changed: set) -> bool:
	"""
	Insert the role's rule only when it has no level-0 rule and no change history; an existing rule is widened
	only when it is an untouched copy of the previous release's rule.
	"""
	if not frappe.db.exists("Role", role):
		return False
	rules = get_existing_rules(doctype, role)
	if rules:
		return settle_existing_rules(doctype, role, ptypes, rules, changed)
	if role in changed:
		print(f"{doctype} / {role}: skipped, this site changed the rule")
		return False
	return insert_rule(doctype, role, ptypes)


def settle_existing_rules(doctype: str, role: str, ptypes: tuple, rules: list, changed: set) -> bool:
	"""
	Widen the role's rule when it is an untouched copy of the previous release's shipped rule, and otherwise
	leave every rule as the site set it, reporting any shortfall.
	"""
	for rule in rules:
		if is_unedited_release_copy(doctype, role, rule, changed):
			return widen_rule(doctype, role, ptypes, rule)
	report_short_rule(doctype, role, ptypes, rules)
	return False


def is_unedited_release_copy(doctype: str, role: str, rule, changed: set) -> bool:
	"""
	Return whether the rule grants exactly what the previous release shipped for this pair, on every record,
	and Permission Log shows no administrator ever edited or removed the pair.
	"""
	previous = PREVIOUS_SHIPPED_RULES.get((doctype, role))
	if previous is None:
		return False
	if role in changed:
		return False
	if cint(rule.if_owner):
		return False
	return has_exact_rights(rule, previous)


def has_exact_rights(rule, rights: tuple) -> bool:
	"""
	Return whether the rule grants every right in `rights` and nothing else, checking every grant flag the
	site's Custom DocPerm table carries, including site-defined permission types.
	"""
	for flag in get_grant_flags():
		expected = 1 if flag in rights else 0
		if cint(rule.get(flag)) != expected:
			return False
	return True


def widen_rule(doctype: str, role: str, ptypes: tuple, rule) -> bool:
	"""
	Add the rights this release grants that the untouched release copy lacks, never removing any, and return
	whether it was widened; a failure is rolled back and logged.
	"""
	missing = get_missing_ptypes(ptypes, rule)
	if not missing:
		return False
	try:
		frappe.db.savepoint(SAVEPOINT)
		row = frappe.get_doc("Custom DocPerm", rule.name)
		for ptype in missing:
			row.set(ptype, 1)
		row.save(ignore_permissions=True)
		print(f"{doctype} / {role}: widened, unedited copy of the release rule (added {', '.join(missing)})")
		return True
	except Exception:
		log_failure("Could not widen permission", doctype, role)
		return False


def report_short_rule(doctype: str, role: str, ptypes: tuple, rules: list):
	"""
	Print a line naming the rights the site's existing rules do not grant on every record, so an
	administrator knows what to grant; the rules themselves are never changed.
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


def get_missing_ptypes(ptypes: tuple, existing) -> list:
	"""
	Return the permission types from `ptypes` that the existing Custom DocPerm row does not grant, in the
	order they are listed in the release's grant.
	"""
	missing = []
	for ptype in ptypes:
		if not cint(existing.get(ptype)):
			missing.append(ptype)
	return missing


def get_changed_roles(doctype: str) -> set:
	"""
	Return the roles whose Custom DocPerm rules on `doctype` an administrator edited or deleted, per
	Permission Log, so the patch never touches a pair the site ruled on.
	"""
	roles = set()
	for log in get_change_logs(doctype, ("Updated", "Removed")):
		roles.update(get_logged_roles(log))
	return roles


def removed_roles(doctype: str) -> set:
	"""
	Return the roles whose Custom DocPerm rule on `doctype` this site created and later deleted, read from
	Permission Log, so a revoked rule is never treated as missing.
	"""
	roles = set()
	for log in get_change_logs(doctype, ("Removed",)):
		roles.update(get_logged_roles(log))
	return roles


def get_change_logs(doctype: str, statuses: tuple) -> list:
	"""
	Return the Permission Log entries recording Custom DocPerm rows on `doctype` with one of `statuses`,
	with the changes JSON and the referenced row name.
	"""
	return frappe.get_all(
		"Permission Log",
		filters={
			"for_doctype": "DocType",
			"for_document": doctype,
			"reference_type": "Custom DocPerm",
			"status": ["in", list(statuses)],
		},
		fields=["changes", "reference"],
	)


def get_logged_roles(log) -> set:
	"""
	Return every role a Permission Log entry concerns: both sides of a role change, the removed role, or the
	referenced row's role when an edit did not record one.
	"""
	roles = get_recorded_roles(log.changes)
	if roles:
		return roles
	role = frappe.db.get_value("Custom DocPerm", log.reference, "role")
	return {role} if role else set()


def get_recorded_roles(changes: str) -> set:
	"""
	Return the non-empty roles on the `from` and `to` sides of a Permission Log entry's changes JSON; a
	removal records its role only on the `from` side.
	"""
	try:
		logged = json.loads(changes) or {}
	except (TypeError, ValueError):
		return set()
	roles = set()
	for side in ("from", "to"):
		role = (logged.get(side) or {}).get("role")
		if role:
			roles.add(role)
	return roles


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
		print(f"{doctype} / {role}: added {', '.join(ptypes)}")
		return True
	except Exception:
		log_failure("Could not add permission", doctype, role)
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

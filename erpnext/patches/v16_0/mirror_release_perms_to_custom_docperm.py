import frappe
from frappe.utils import cint

# rows this release adds to shipped DocType JSON; a doctype with Custom DocPerm rows never reads them
GRANTS = {
	"Payment Terms Template": {
		"Maintenance Manager": ("read",),
		"Maintenance User": ("read",),
		"Purchase Manager": ("read",),
		"Purchase User": ("read",),
		"Sales Manager": ("read",),
		"Sales User": ("read",),
		"Purchase Master Manager": ("select",),
		"Sales Master Manager": ("select",),
	},
	"POS Invoice": {
		"Sales Manager": ("read",),
		"Sales User": ("read",),
	},
	"Serial and Batch Bundle": {
		"Sales User": ("select",),
	},
}

# the rights the previous release (v15.121.5) shipped for each GRANTS pair whose shipped row now changes;
# a site rule still exactly equal to one of these is an unedited copy, not an admin decision
PREVIOUS_SHIPPED_RULES = {
	("POS Invoice", "Sales Manager"): ("select",),
	("POS Invoice", "Sales User"): ("select",),
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

NON_GRANT_FLAGS = ("if_owner",)

SAVEPOINT = "mirror_release_perms_to_custom_docperm"


def execute():
	"""Give each role in GRANTS its rule on doctypes this site customised, inserting where the role has no
	level-0 rule and widening only unedited copies of the previous release's rule."""
	# v15 frappe has no Permission Log, so a rule the site deleted cannot be told apart from one that
	# never existed: such a pair is granted again
	for doctype, roles in GRANTS.items():
		if has_custom_perms(doctype):
			mirror_doctype(doctype, roles)


def has_custom_perms(doctype):
	"""Return whether the doctype exists on this site and already carries Custom DocPerm rows, the only
	case where shipped rows are ignored and must be mirrored."""
	if not frappe.db.exists("DocType", doctype):
		return False
	return bool(frappe.db.exists("Custom DocPerm", {"parent": doctype}))


def mirror_doctype(doctype, roles):
	"""Mirror every granted role onto one customised doctype, clearing its cached permissions once when
	at least one rule was inserted for it."""
	added = False
	for role, ptypes in roles.items():
		if mirror_role(doctype, role, ptypes):
			added = True
	if added:
		frappe.clear_cache(doctype=doctype)


def mirror_role(doctype, role, ptypes):
	"""Insert the role's rule when it has none at level 0 and widen an unedited copy of the previous
	release's rule; any other existing rule is left alone and reported."""
	if not frappe.db.exists("Role", role):
		return False
	rules = get_existing_rules(doctype, role)
	if not rules:
		return insert_rule(doctype, role, ptypes)
	if is_unedited_release_copy(doctype, role, rules):
		return widen_rule(doctype, role, ptypes, rules[0])
	report_existing_rules(doctype, role, ptypes, rules)
	return False


def is_unedited_release_copy(doctype, role, rules):
	"""Return whether the pair's only level-0 rule grants exactly what the previous release shipped for it,
	not owner-only, which is the one shape v15 can tell unedited."""
	previous = PREVIOUS_SHIPPED_RULES.get((doctype, role))
	if previous is None:
		return False
	if len(rules) != 1:
		return False
	if cint(rules[0].if_owner):
		return False
	return get_granted_flags(rules[0]) == set(previous)


def get_granted_flags(rule):
	"""Return the set of grant flags the rule has switched on, read against every grant checkbox the
	installed Custom DocPerm table really has."""
	granted = set()
	for flag in get_grant_flags():
		if cint(rule.get(flag)):
			granted.add(flag)
	return granted


def widen_rule(doctype, role, ptypes, rule):
	"""Add only the newly shipped ptypes to an unedited copy of the previous release's rule and print it,
	rolling back and logging instead of stopping the migration on failure."""
	try:
		frappe.db.savepoint(SAVEPOINT)
		row = frappe.get_doc("Custom DocPerm", rule.name)
		for ptype in ptypes:
			row.set(ptype, 1)
		row.save(ignore_permissions=True)
		print(f"{doctype} / {role}: widened, unedited copy of the release rule")
		return True
	except Exception:
		log_failure("Could not widen permission", doctype, role)
		return False


def report_existing_rules(doctype, role, ptypes, rules):
	"""Print that the site's own rule was kept, saying whether it already grants the rights this release
	ships for the role on every record."""
	rights = ", ".join(ptypes)
	if has_full_rule(rules, ptypes):
		print(f"{doctype} / {role}: kept, the site's rule already grants {rights}")
		return
	print(f"{doctype} / {role}: kept, the site's rule does not grant {rights}")


def has_full_rule(rules, ptypes):
	"""Return whether one of the rules, not limited to the role's own records, grants every ptype this
	release ships for the role."""
	for rule in rules:
		if cint(rule.if_owner):
			continue
		if not get_missing_ptypes(ptypes, rule):
			return True
	return False


def get_missing_ptypes(ptypes, rule):
	"""Return the ptypes from the shipped grant that the site's rule does not set, in the order the grant
	lists them, for reporting a rule that falls short."""
	missing = []
	for ptype in ptypes:
		if not cint(rule.get(ptype)):
			missing.append(ptype)
	return missing


def get_existing_rules(doctype, role):
	"""Return every level-0 Custom DocPerm rule the site holds for the role on the doctype, owner-only
	ones included, with each grant flag the table has."""
	return frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": role, "permlevel": 0},
		fields=["name", "if_owner", *get_grant_flags()],
	)


def get_grant_flags():
	"""Return every grant checkbox the installed Custom DocPerm table really has, read from its meta and
	columns, since v15 has no mask or impersonate field."""
	flags = []
	for field in frappe.get_meta("Custom DocPerm").fields:
		if field.fieldtype != "Check":
			continue
		if field.fieldname in NON_GRANT_FLAGS:
			continue
		if frappe.db.has_column("Custom DocPerm", field.fieldname):
			flags.append(field.fieldname)
	return flags


def insert_rule(doctype, role, ptypes):
	"""Insert a level-0 rule granting exactly the shipped ptypes and print it, rolling back and logging
	instead of stopping the migration when the insert fails."""
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


def get_new_rule_values(doctype, role, ptypes):
	"""Return the field values of a new level-0 rule, setting every ptype explicitly because Custom DocPerm
	defaults read and export to 1."""
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


def log_failure(title, doctype, role):
	"""Roll back to the savepoint before logging, because a failed statement leaves the transaction
	unusable on Postgres and log_error would then fail too."""
	frappe.db.rollback(save_point=SAVEPOINT)
	frappe.log_error(title=title, message=f"{doctype} / {role}\n\n{frappe.get_traceback()}")

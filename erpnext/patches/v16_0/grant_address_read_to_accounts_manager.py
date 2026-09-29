from erpnext.setup.install import grant_address_read_to_accounts_manager


def execute():
	"""
	Give Accounts Manager read on Address, which the tax rule lookup now checks, unless the role already has a
	rule there or an admin changed one.
	"""
	grant_address_read_to_accounts_manager()

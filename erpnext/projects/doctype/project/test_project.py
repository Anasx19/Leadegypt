# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import add_days, getdate, nowdate

from erpnext.projects.doctype.project_template.test_project_template import make_project_template
from erpnext.projects.doctype.task.test_task import create_task
from erpnext.selling.doctype.sales_order.mapper import make_project as make_project_from_so
from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order
from erpnext.tests.utils import ERPNextTestSuite


class TestProject(ERPNextTestSuite):
	def test_get_timeline_data_runs(self):
		# get_timeline_data groups Timesheet Detail by Date(from_time); the selected day key must be the
		# same grouped expression (UnixTimestamp(Date(from_time))) to be valid on Postgres.
		from erpnext.projects.doctype.project.project import get_timeline_data
		from erpnext.projects.doctype.timesheet.test_timesheet import make_timesheet
		from erpnext.setup.doctype.employee.test_employee import make_employee

		project = make_project({"project_name": "_Test Timeline Project", "company": "_Test Company"})
		emp = make_employee("test_timeline@example.com", company="_Test Company")
		make_timesheet(emp, simulate=True, project=project.name)

		data = get_timeline_data("Project", project.name)
		self.assertIsInstance(data, dict)
		self.assertGreaterEqual(sum(data.values()), 1)

	def test_project_total_costing_and_billing_amount(self):
		from erpnext.projects.doctype.timesheet.test_timesheet import make_timesheet
		from erpnext.setup.doctype.employee.test_employee import make_employee

		project_name = "Test Project Costing"
		employee = make_employee("employee@frappe.io", company="_Test Company")
		project = make_project({"project_name": project_name})
		timesheet = make_timesheet(
			employee=employee,
			is_billable=1,
			currency="USD",
			project=project.name,
			simulate=True,
			exchange_rate=80,
		)
		timesheet.reload()
		project.reload()
		self.assertEqual(project.total_costing_amount, 3200)
		self.assertEqual(project.total_billable_amount, 8000)

	def test_project_with_template_having_no_parent_and_depend_tasks(self):
		project_name = "Test Project with Template - No Parent and Dependend Tasks"
		frappe.db.delete("Task", {"project": project_name})
		frappe.delete_doc("Project", project_name)

		task1 = task_exists("Test Template Task with No Parent and Dependency")
		if not task1:
			task1 = create_task(
				subject="Test Template Task with No Parent and Dependency",
				is_template=1,
				begin=5,
				duration=3,
				priority="High",
			)

		template = make_project_template("Test Project Template - No Parent and Dependend Tasks", [task1])
		project = get_project(project_name, template)
		tasks = frappe.get_all(
			"Task",
			["subject", "exp_end_date", "depends_on_tasks", "priority"],
			dict(project=project.name),
			order_by="creation asc",
		)

		self.assertEqual(tasks[0].priority, "High")
		self.assertEqual(tasks[0].subject, "Test Template Task with No Parent and Dependency")
		self.assertEqual(getdate(tasks[0].exp_end_date), calculate_end_date(project, 5, 3))
		self.assertEqual(len(tasks), 1)

	def test_project_template_having_parent_child_tasks(self):
		project_name = "Test Project with Template - Tasks with Parent-Child Relation"

		if frappe.db.get_value("Project", {"project_name": project_name}, "name"):
			project_name = frappe.db.get_value("Project", {"project_name": project_name}, "name")

		frappe.db.delete("Task", {"project": project_name})
		frappe.delete_doc("Project", project_name)

		task1 = task_exists("Test Template Task Parent")
		if not task1:
			task1 = create_task(
				subject="Test Template Task Parent", is_group=1, is_template=1, begin=1, duration=10
			)

		task2 = task_exists("Test Template Task Child 1")
		if not task2:
			task2 = create_task(
				subject="Test Template Task Child 1",
				parent_task=task1.name,
				is_template=1,
				begin=1,
				duration=3,
			)

		task3 = task_exists("Test Template Task Child 2")
		if not task3:
			task3 = create_task(
				subject="Test Template Task Child 2",
				parent_task=task1.name,
				is_template=1,
				begin=2,
				duration=3,
			)

		template = make_project_template(
			"Test Project Template  - Tasks with Parent-Child Relation", [task1, task2, task3]
		)
		project = get_project(project_name, template)
		tasks = frappe.get_all(
			"Task",
			["subject", "exp_end_date", "depends_on_tasks", "name", "parent_task"],
			dict(project=project.name),
			order_by="creation asc",
		)

		self.assertEqual(tasks[0].subject, "Test Template Task Parent")
		self.assertEqual(getdate(tasks[0].exp_end_date), calculate_end_date(project, 1, 10))

		self.assertEqual(tasks[1].subject, "Test Template Task Child 1")
		self.assertEqual(getdate(tasks[1].exp_end_date), calculate_end_date(project, 1, 3))
		self.assertEqual(tasks[1].parent_task, tasks[0].name)

		self.assertEqual(tasks[2].subject, "Test Template Task Child 2")
		self.assertEqual(getdate(tasks[2].exp_end_date), calculate_end_date(project, 2, 3))
		self.assertEqual(tasks[2].parent_task, tasks[0].name)

		self.assertEqual(len(tasks), 3)

	def test_project_template_having_dependent_tasks(self):
		project_name = "Test Project with Template - Dependent Tasks"
		frappe.db.delete("Task", {"project": project_name})
		frappe.delete_doc("Project", project_name)

		task1 = task_exists("Test Template Task for Dependency")
		if not task1:
			task1 = create_task(
				subject="Test Template Task for Dependency", is_template=1, begin=3, duration=1
			)

		task2 = task_exists("Test Template Task with Dependency")
		if not task2:
			task2 = create_task(
				subject="Test Template Task with Dependency",
				depends_on=task1.name,
				is_template=1,
				begin=2,
				duration=2,
			)

		template = make_project_template("Test Project with Template - Dependent Tasks", [task1, task2])
		project = get_project(project_name, template)
		tasks = frappe.get_all(
			"Task",
			["subject", "exp_end_date", "depends_on_tasks", "name"],
			dict(project=project.name),
			order_by="creation asc",
		)

		self.assertEqual(tasks[1].subject, "Test Template Task with Dependency")
		self.assertEqual(getdate(tasks[1].exp_end_date), calculate_end_date(project, 2, 2))
		self.assertGreaterEqual(tasks[1].depends_on_tasks.find(tasks[0].name), 0)

		self.assertEqual(tasks[0].subject, "Test Template Task for Dependency")
		self.assertEqual(getdate(tasks[0].exp_end_date), calculate_end_date(project, 3, 1))

		self.assertEqual(len(tasks), 2)

	def test_project_linking_with_sales_order(self):
		so = make_sales_order()
		project = make_project_from_so(so.name)

		project.save()
		self.assertEqual(project.sales_order, so.name)

		so.reload()
		self.assertEqual(so.project, project.name)

		project.delete()

		so.reload()
		self.assertFalse(so.project)

	def test_sales_order_link_is_not_overwritten_by_second_project(self):
		so = make_sales_order()

		first_project = make_project_from_so(so.name).save()
		so.reload()
		self.assertEqual(so.project, first_project.name)

		# A second project for the same sales order must not steal the link.
		second_project = frappe.get_doc(
			doctype="Project",
			project_name="Second project for same sales order",
			company=so.company,
			sales_order=so.name,
		).insert()
		self.assertEqual(second_project.sales_order, so.name)

		so.reload()
		self.assertEqual(so.project, first_project.name)

	def test_project_with_template_tasks_having_common_name(self):
		# Step - 1: Create Template Parent Tasks
		template_parent_task1 = create_task(subject="Parent Task - 1", is_template=1, is_group=1)
		template_parent_task2 = create_task(subject="Parent Task - 2", is_template=1, is_group=1)
		template_parent_task3 = create_task(subject="Parent Task - 1", is_template=1, is_group=1)

		# Step - 2: Create Template Child Tasks
		template_task1 = create_task(
			subject="Task - 1", is_template=1, parent_task=template_parent_task1.name
		)
		template_task2 = create_task(
			subject="Task - 2", is_template=1, parent_task=template_parent_task2.name
		)
		template_task3 = create_task(
			subject="Task - 1", is_template=1, parent_task=template_parent_task3.name
		)

		# Step - 3: Create Project Template
		template_tasks = [
			template_parent_task1,
			template_task1,
			template_parent_task2,
			template_task2,
			template_parent_task3,
			template_task3,
		]
		project_template = make_project_template("Project template with common Task Subject", template_tasks)

		# Step - 4: Create Project against the Project Template
		project = get_project("Project with common Task Subject", project_template)
		project_tasks = frappe.get_all(
			"Task", {"project": project.name}, ["subject", "parent_task", "is_group"]
		)

		# Test - 1: No. of Project Tasks should be equal to No. of Template Tasks
		self.assertEqual(len(project_tasks), len(template_tasks))

		# Test - 2: All child Project Tasks should have Parent Task linked
		for pt in project_tasks:
			if not pt.is_group:
				self.assertIsNotNone(pt.parent_task)

	def test_project_having_no_tasks_complete(self):
		project_name = "Test Project - No Tasks Completion"
		frappe.db.delete("Task", {"project": project_name})
		frappe.delete_doc("Project", project_name)

		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": project_name,
				"status": "Open",
				"expected_start_date": nowdate(),
				"company": "_Test Company",
			}
		).insert()

		tasks = frappe.get_all(
			"Task",
			["subject", "exp_end_date", "depends_on_tasks", "name", "parent_task"],
			dict(project=project.name),
			order_by="creation asc",
		)

		self.assertEqual(project.status, "Open")
		self.assertEqual(len(tasks), 0)
		project.status = "Completed"
		project.save()
		self.assertEqual(project.status, "Completed")

	def _project_with_tasks(self, method, count):
		name = f"_Test PercentComplete {frappe.generate_hash(length=8)}"
		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": name,
				"status": "Open",
				"percent_complete_method": method,
				"company": "_Test Company",
				"expected_start_date": nowdate(),
			}
		).insert()
		task_names = []
		for i in range(count):
			task = frappe.get_doc(
				{
					"doctype": "Task",
					"subject": f"{name} Task {i}",
					"project": project.name,
					"status": "Open",
					"exp_start_date": nowdate(),
					"exp_end_date": nowdate(),
				}
			).insert()
			task_names.append(task.name)
		return project, task_names

	def test_percent_complete_by_task_completion(self):
		project, tasks = self._project_with_tasks("Task Completion", 4)

		frappe.db.set_value("Task", tasks[0], "status", "Completed")
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 25)  # 1 of 4

		for task in tasks:
			frappe.db.set_value("Task", task, "status", "Completed")
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 100)
		self.assertEqual(project.status, "Completed")  # 100% flips status to Completed

		# reopening a task drops below 100% and flips status back to Open
		frappe.db.set_value("Task", tasks[0], "status", "Open")
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 75)
		self.assertEqual(project.status, "Open")

		# a Cancelled project keeps its status regardless of completion
		project.status = "Cancelled"
		for task in tasks:
			frappe.db.set_value("Task", task, "status", "Completed")
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 100)
		self.assertEqual(project.status, "Cancelled")

	def test_on_hold_project_keeps_status(self):
		project, tasks = self._project_with_tasks("Task Completion", 4)

		# an On hold project is not auto-flipped to Completed even at 100%
		project.status = "On hold"
		for task in tasks:
			frappe.db.set_value("Task", task, "status", "Completed")
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 100)
		self.assertEqual(project.status, "On hold")

		# nor auto-flipped back to Open when below 100%
		frappe.db.set_value("Task", tasks[0], "status", "Open")
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 75)
		self.assertEqual(project.status, "On hold")

	def test_percent_complete_manual(self):
		project, tasks = self._project_with_tasks("Manual", 2)

		# manual value is preserved on save, even with linked tasks
		project.percent_complete = 42
		project.save()
		self.assertEqual(project.percent_complete, 42)

		# task updates do not overwrite the manual value
		frappe.db.set_value("Task", tasks[0], "status", "Completed")
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 42)

		# out-of-range values are rejected
		project.percent_complete = 150
		self.assertRaises(frappe.ValidationError, project.save)
		project.reload()

		project.percent_complete = -10
		self.assertRaises(frappe.ValidationError, project.save)
		project.reload()

		# Completed status forces 100 regardless of the manual value
		project.percent_complete = 42
		project.status = "Completed"
		project.save()
		self.assertEqual(project.percent_complete, 100)

	def test_percent_complete_by_task_progress(self):
		project, tasks = self._project_with_tasks("Task Progress", 2)

		frappe.db.set_value("Task", tasks[0], "progress", 50)
		frappe.db.set_value("Task", tasks[1], "progress", 100)
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 75)  # (50 + 100) / 2

	def test_percent_complete_by_task_weight(self):
		project, tasks = self._project_with_tasks("Task Weight", 2)

		frappe.db.set_value("Task", tasks[0], {"progress": 100, "task_weight": 3})
		frappe.db.set_value("Task", tasks[1], {"progress": 0, "task_weight": 1})
		project.update_percent_complete()
		self.assertEqual(project.percent_complete, 75)  # 100 * 3/4 + 0 * 1/4

	def test_create_duplicate_project_copies_tasks(self):
		from erpnext.projects.doctype.project.project import create_duplicate_project

		source, tasks = self._project_with_tasks("Task Completion", 2)
		new_name = f"{source.project_name} Copy"

		new_project = create_duplicate_project(frappe.as_json(source.as_dict()), new_name)

		# Project is named by series, so the returned name is what the form navigates to
		self.assertEqual(frappe.db.get_value("Project", new_project, "project_name"), new_name)
		copied_tasks = frappe.get_all("Task", filters={"project": new_project})
		self.assertEqual(len(copied_tasks), len(tasks))

	def test_duplicate_of_completed_project_starts_open(self):
		from erpnext.projects.doctype.project.project import create_duplicate_project

		for task_count in (2, 0):
			with self.subTest(task_count=task_count):
				source, tasks = self._project_with_tasks("Task Completion", task_count)
				for task in tasks:
					frappe.db.set_value("Task", task, {"status": "Completed", "progress": 100})
				source.reload()
				source.status = "Completed"
				source.save()
				self.assertEqual(source.percent_complete, 100)

				new_project = create_duplicate_project(
					frappe.as_json(source.as_dict()), f"{source.project_name} Copy"
				)

				copy = frappe.db.get_value(
					"Project",
					new_project,
					["status", "percent_complete", "percent_complete_method"],
					as_dict=True,
				)
				self.assertEqual(copy.status, "Open")
				self.assertEqual(copy.percent_complete, 0)
				# kept from the source (completing a project without tasks makes it Manual), not
				# forced to Manual by the copy being inserted as Completed before its tasks exist
				self.assertEqual(copy.percent_complete_method, source.percent_complete_method)

	def test_create_duplicate_project_links_copied_tasks_to_each_other(self):
		from erpnext.projects.doctype.project.project import create_duplicate_project

		source, _ = self._project_with_tasks("Task Completion", 0)
		prefix = source.project_name

		def make_task(subject, **kwargs):
			return frappe.get_doc(
				doctype="Task",
				subject=f"{prefix} {subject}",
				project=source.name,
				exp_start_date=nowdate(),
				exp_end_date=nowdate(),
				**kwargs,
			).insert()

		parent = make_task("Parent", is_group=1)
		child = make_task("Child", parent_task=parent.name)
		blocker = make_task("Blocker", status="Completed")
		blocked = make_task("Blocked", depends_on=[{"task": blocker.name}])
		# completed despite its open dependency, as data created before that check existed can be
		frappe.db.set_value("Task", blocked.name, {"status": "Completed", "progress": 100})

		new_project = create_duplicate_project(frappe.as_json(source.as_dict()), f"{prefix} Copy")

		copies = {
			t.subject.removeprefix(f"{prefix} "): t
			for t in frappe.get_all(
				"Task",
				filters={"project": new_project},
				fields=["name", "subject", "status", "progress", "parent_task"],
			)
		}
		self.assertEqual(set(copies), {"Parent", "Child", "Blocker", "Blocked"})
		self.assertEqual(copies["Child"].parent_task, copies["Parent"].name)
		self.assertEqual(
			frappe.get_all("Task Depends On", {"parent": copies["Blocked"].name}, pluck="task"),
			[copies["Blocker"].name],
		)
		# copies start afresh instead of carrying over the source's progress
		for task in copies.values():
			self.assertEqual(task.status, "Open")
			self.assertEqual(task.progress, 0)

		# the source project's tasks are left as they were
		self.assertEqual(frappe.db.get_value("Task", child.name, "parent_task"), parent.name)

	def test_create_duplicate_project_copies_nested_tasks(self):
		from erpnext.projects.doctype.project.project import create_duplicate_project

		source, _ = self._project_with_tasks("Task Completion", 0)
		prefix = source.project_name

		def make_task(subject, **kwargs):
			return frappe.get_doc(
				doctype="Task",
				subject=f"{prefix} {subject}",
				project=source.name,
				exp_start_date=nowdate(),
				exp_end_date=nowdate(),
				**kwargs,
			).insert()

		# Task itself makes each parent depend on its subtasks
		root = make_task("Root", is_group=1)
		group = make_task("Group", is_group=1, parent_task=root.name)
		leaf = make_task("Leaf", parent_task=group.name)
		make_task("Sibling", parent_task=root.name, depends_on=[{"task": leaf.name}])
		# links looping through the tree: Root needs Leaf, which needs Group, which needs Root
		root.reload()
		root.append("depends_on", {"task": leaf.name})
		root.save()

		new_project = create_duplicate_project(frappe.as_json(source.as_dict()), f"{prefix} Copy")

		copies = {
			t.subject.removeprefix(f"{prefix} "): t
			for t in frappe.get_all(
				"Task", filters={"project": new_project}, fields=["name", "subject", "parent_task"]
			)
		}
		self.assertEqual(set(copies), {"Root", "Group", "Leaf", "Sibling"})
		names = {subject: t.name for subject, t in copies.items()}

		self.assertFalse(copies["Root"].parent_task)
		self.assertEqual(copies["Group"].parent_task, names["Root"])
		self.assertEqual(copies["Leaf"].parent_task, names["Group"])
		self.assertEqual(copies["Sibling"].parent_task, names["Root"])

		def dependencies(subject):
			return sorted(
				frappe.get_all("Task Depends On", {"parent": names[subject]}, pluck="task", order_by="idx")
			)

		# the same dependencies as the source, each once and all within the copy
		self.assertEqual(dependencies("Root"), sorted([names["Group"], names["Sibling"], names["Leaf"]]))
		self.assertEqual(dependencies("Group"), [names["Leaf"]])
		self.assertEqual(dependencies("Sibling"), [names["Leaf"]])
		self.assertEqual(dependencies("Leaf"), [])

	def test_copy_order_handles_dependency_chains_beyond_recursion_limit(self):
		import sys

		from erpnext.projects.doctype.project.project import get_copy_order

		length = sys.getrecursionlimit() + 100
		# listed newest first, each task depending on the one before it
		names = [f"Task {i}" for i in reversed(range(length))]
		tasks = {name: frappe._dict(parent_task=None) for name in names}
		depends_on = {f"Task {i}": [f"Task {i - 1}"] if i else [] for i in range(length)}
		# and a subtask listed before its parent
		tasks["Subtask"] = frappe._dict(parent_task="Parent")
		tasks["Parent"] = frappe._dict(parent_task=None)
		depends_on.update({"Subtask": [], "Parent": []})

		order = get_copy_order(tasks, depends_on)

		self.assertCountEqual(order, tasks)
		position = {name: i for i, name in enumerate(order)}
		for i in range(1, length):
			self.assertLess(position[f"Task {i - 1}"], position[f"Task {i}"])
		self.assertLess(position["Parent"], position["Subtask"])

	def test_create_duplicate_project_rejects_same_name(self):
		from erpnext.projects.doctype.project.project import create_duplicate_project

		source, _ = self._project_with_tasks("Task Completion", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "different from previous project name"):
			create_duplicate_project(frappe.as_json(source.as_dict()), source.project_name)

		# the form sends its doc as it is, which may carry an unsaved edit to the Project Name
		edited = source.as_dict()
		edited.project_name = f"{source.project_name} (edited)"
		with self.assertRaisesRegex(frappe.ValidationError, "different from previous project name"):
			create_duplicate_project(frappe.as_json(edited), source.project_name)

	def test_create_duplicate_project_rejects_invalid_payload(self):
		from erpnext.projects.doctype.project.project import create_duplicate_project

		source, _ = self._project_with_tasks("Task Completion", 1)
		orphan_task = frappe.get_doc(
			doctype="Task", subject=f"{source.project_name} Orphan", exp_start_date=nowdate()
		).insert()
		projects_before = frappe.db.count("Project")

		source_dict = source.as_dict()
		invalid_payloads = {
			"not a dict": frappe.as_json([source_dict]),
			"another doctype": frappe.as_json({**source_dict, "doctype": "ToDo"}),
			"unsaved project": frappe.as_json({**source_dict, "name": None}),
			"non-string name": frappe.as_json({**source_dict, "name": ["PROJ-0001"]}),
		}
		for case, payload in invalid_payloads.items():
			with self.subTest(case=case):
				self.assertRaisesRegex(
					frappe.ValidationError,
					"Select a saved Project to duplicate",
					create_duplicate_project,
					payload,
					f"{source.project_name} {case}",
				)

		with self.assertRaisesRegex(frappe.ValidationError, "Project Name is required"):
			create_duplicate_project(frappe.as_json(source_dict), "   ")

		# outside requests and tests nothing enforces the `str` hint, as with the unwrapped function
		for project_name in (None, 42):
			with self.subTest(project_name=project_name):
				with self.assertRaisesRegex(frappe.ValidationError, "Project Name is required"):
					create_duplicate_project.__wrapped__(frappe.as_json(source_dict), project_name)

		missing_source = frappe.as_json({**source_dict, "name": "_Test Missing Project"})
		with self.assertRaises(frappe.DoesNotExistError):
			create_duplicate_project(missing_source, f"{source.project_name} missing")

		self.assertEqual(frappe.db.count("Project"), projects_before)
		# an unnamed payload must not pick up tasks that belong to no project
		self.assertEqual(frappe.db.count("Task", {"subject": orphan_task.subject}), 1)

	def test_set_project_status_updates_project_and_tasks(self):
		from erpnext.projects.doctype.project.project import set_project_status

		project, tasks = self._project_with_tasks("Task Completion", 2)

		set_project_status(project.name, "Cancelled")

		self.assertEqual(frappe.db.get_value("Project", project.name, "status"), "Cancelled")
		for task in tasks:
			self.assertEqual(frappe.db.get_value("Task", task, "status"), "Cancelled")

	def test_set_project_status_rejects_invalid_status(self):
		from erpnext.projects.doctype.project.project import set_project_status

		project, _ = self._project_with_tasks("Task Completion", 1)
		self.assertRaises(frappe.ValidationError, set_project_status, project.name, "Open")

	def test_costing_rollup_from_sales_documents(self):
		from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
		from erpnext.projects.doctype.project.project import update_costing_and_billing
		from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order

		project = make_project({"project_name": f"_Test Costing Rollup {frappe.generate_hash(length=6)}"})

		sales_order = make_sales_order(do_not_save=True)
		sales_order.project = project.name
		sales_order.insert()
		sales_order.submit()

		sales_invoice = create_sales_invoice(do_not_submit=True)
		sales_invoice.project = project.name
		sales_invoice.submit()

		update_costing_and_billing(project.name)
		project.reload()

		self.assertEqual(project.total_sales_amount, sales_order.base_net_total)
		self.assertEqual(project.total_billed_amount, sales_invoice.base_net_total)
		# with no costing/purchase/material expense, gross margin is the billed amount in full
		self.assertEqual(project.gross_margin, sales_invoice.base_net_total)
		self.assertEqual(project.per_gross_margin, 100)

	def test_consumed_material_cost_from_stock_entry(self):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		project = make_project({"project_name": f"_Test Consumed Cost {frappe.generate_hash(length=6)}"})

		# receive stock, then issue it against the project so it counts as consumed
		make_stock_entry(item_code="_Test Item", qty=10, to_warehouse="_Test Warehouse - _TC", rate=100)
		issue = make_stock_entry(
			item_code="_Test Item", qty=4, from_warehouse="_Test Warehouse - _TC", do_not_save=True
		)
		issue.project = project.name
		for row in issue.items:
			row.project = project.name
		issue.insert()
		issue.submit()
		issue.reload()

		project.set_consumed_material_cost()
		self.assertEqual(project.total_consumed_material_cost, sum(row.amount for row in issue.items))
		self.assertGreater(project.total_consumed_material_cost, 0)

	def _create_portal_user(self, email):
		"""A user with no Project-related role, so read access can only come from
		control_access_for_project_users() sharing the doc with them."""
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Portal",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		return email

	def test_new_project_grants_access_to_its_users(self):
		member = self._create_portal_user(f"new_proj_member_{frappe.generate_hash(length=6)}@example.com")

		project = frappe.get_doc(
			doctype="Project",
			project_name=f"_Test New Project Access {frappe.generate_hash(length=6)}",
			status="Open",
			company="_Test Company",
		)
		project.append("users", {"user": member, "welcome_email_sent": 1})
		project.insert()  # must not raise

		self.assertTrue(project.has_permission(user=member))
		shared_with = [d.user for d in frappe.share.get_users("Project", project.name)]
		self.assertIn(member, shared_with)

	def test_adding_and_removing_project_user_updates_access(self):
		stays = self._create_portal_user(f"stays_{frappe.generate_hash(length=6)}@example.com")
		leaves = self._create_portal_user(f"leaves_{frappe.generate_hash(length=6)}@example.com")

		project = frappe.get_doc(
			doctype="Project",
			project_name=f"_Test Project User Membership {frappe.generate_hash(length=6)}",
			status="Open",
			company="_Test Company",
		)
		project.append("users", {"user": stays, "welcome_email_sent": 1})
		project.insert()
		self.assertTrue(project.has_permission(user=stays))

		# adding a user on update (not insert) must also grant them access
		project.append("users", {"user": leaves, "welcome_email_sent": 1})
		project.save()
		self.assertTrue(project.has_permission(user=leaves))

		# removing a user must revoke the share that was granted for membership
		project.users = [d for d in project.users if d.user != leaves]
		project.save()
		self.assertFalse(project.has_permission(user=leaves))
		self.assertTrue(project.has_permission(user=stays))


def get_project(name, template):
	project = frappe.get_doc(
		doctype="Project",
		project_name=name,
		status="Open",
		project_template=template.name,
		expected_start_date=nowdate(),
		company="_Test Company",
	).insert()

	return project


def make_project(args):
	args = frappe._dict(args)

	if args.project_name and frappe.db.exists("Project", {"project_name": args.project_name}):
		return frappe.get_doc("Project", {"project_name": args.project_name})

	project = frappe.get_doc(
		doctype="Project",
		project_name=args.project_name,
		status="Open",
		expected_start_date=args.start_date,
		company=args.company or "_Test Company",
	)

	if args.project_template_name:
		template = make_project_template(args.project_template_name)
		project.project_template = template.name

	project.insert()

	return project


def task_exists(subject):
	result = frappe.db.get_list("Task", filters={"subject": subject}, fields=["name"])
	if not len(result):
		return False
	return frappe.get_doc("Task", result[0].name)


def calculate_end_date(project, start, duration):
	start = add_days(project.expected_start_date, start)
	start = project.update_if_holiday(start)
	end = add_days(start, duration)
	end = project.update_if_holiday(end)
	return getdate(end)

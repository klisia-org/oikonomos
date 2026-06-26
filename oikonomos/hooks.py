app_name = "oikonomos"
app_title = "Oikonomos"
app_publisher = "Klisia / SeminaryERP"
app_description = "Seminary to ERPNext bridge: billing, payments and financial integration for Seminary"
app_email = "support@seminaryerp.org"
app_license = "gpl-3.0"

# Apps
# ------------------

# Oikonomos is the financial bridge: it depends on BOTH seminary (the pure-Frappe
# academic core) and erpnext (the accounting engine). This one-directional
# dependency is what lets seminary run on Frappe alone — seminary never imports
# oikonomos or erpnext. See the oikonomos decoupling roadmap.
required_apps = ["seminary", "erpnext"]

# Register oikonomos as seminary's financial backend. Seminary resolves this via
# frappe.get_hooks("seminary_financial_backend"); with oikonomos installed its
# academic flows get real ERPNext-backed billing, otherwise the null backend.
seminary_financial_backend = ["oikonomos.financial.backend.OikonomosFinancialBackend"]

# Fixtures owned by oikonomos (relocated from seminary with their doctypes).
fixtures = [
    "Trigger Fee Events",
    # UOM "Fee" (billing unit). Fee Items + Payment Terms are NOT fixtured — they
    # are seeded create-once by oikonomos.financial.seed so a seminary's edits
    # survive migrate.
    {"dt": "UOM", "filters": [["name", "=", "Fee"]]},
    {"dt": "Print Format", "filters": [["name", "=", "Seminary Sales Invoice"]]},
    {"dt": "Workflow", "filters": [["name", "=", "Scholarship Award Lifecycle"]]},
]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "oikonomos",
# 		"logo": "/assets/oikonomos/logo.png",
# 		"title": "Oikonomos",
# 		"route": "/oikonomos",
# 		"has_permission": "oikonomos.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/oikonomos/css/oikonomos.css"
# app_include_js = "/assets/oikonomos/js/oikonomos.js"

# include js, css files in header of web template
# web_include_css = "/assets/oikonomos/css/oikonomos.css"
# web_include_js = "/assets/oikonomos/js/oikonomos.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "oikonomos/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "oikonomos/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "oikonomos.utils.jinja_methods",
# 	"filters": "oikonomos.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "oikonomos.install.before_install"
after_install = "oikonomos.install.after_install"
after_migrate = "oikonomos.install.after_migrate"
before_uninstall = "oikonomos.install.before_uninstall"

# Uninstallation
# ------------

# before_uninstall = "oikonomos.uninstall.before_uninstall"
# after_uninstall = "oikonomos.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "oikonomos.utils.before_app_install"
# after_app_install = "oikonomos.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "oikonomos.utils.before_app_uninstall"
# after_app_uninstall = "oikonomos.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "oikonomos.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "oikonomos.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events.
#
# Oikonomos subscribes to seminary academic doctypes here (the "emit" seam): the
# academic flow just submits its doc, and oikonomos reacts with billing. When
# oikonomos is absent these handlers are simply not registered, so seminary runs
# free.

# Override ERPNext's Payment Request to route Student Balance payments through
# the seminary gateway flow (relocated from seminary).
override_doctype_class = {
    "Payment Request": "oikonomos.financial.payment_request.SeminaryPaymentRequest",
}

doc_events = {
    "Culminating Project Extension": {
        "on_submit": "oikonomos.financial.extension.on_submit",
        "on_cancel": "oikonomos.financial.extension.on_cancel",
    },
    "Graduation Request": {
        "on_submit": "oikonomos.financial.graduation.on_submit",
        "on_cancel": "oikonomos.financial.graduation.on_cancel",
    },
    "Course Enrollment Individual": {
        "on_cancel": "oikonomos.financial.backend.on_cei_cancel",
    },
    "Student Applicant": {
        "after_insert": "oikonomos.financial.application.on_applicant_insert",
    },
    # Student Balance lifecycle (doctype relocated from seminary). A balance is
    # opened for every Student and tracks their submitted Sales Invoices.
    "Student": {
        "after_insert": "oikonomos.oikonomos.doctype.student_balance.student_balance.create_student_balance",
        "on_update": "oikonomos.financial.customer_person.on_student_update",
    },
    "Sales Invoice": {
        "on_submit": "oikonomos.oikonomos.doctype.student_balance.student_balance.add_invoice_to_student_balance",
        "on_update_after_submit": "oikonomos.oikonomos.doctype.student_balance.student_balance.refresh_balance_on_invoice_update",
        "on_cancel": "oikonomos.oikonomos.doctype.student_balance.student_balance.remove_cancelled_invoice_from_balance",
    },
    # Instructor payroll (Salary Slip + Instructor Log Payment, relocated from
    # seminary). Gated on HRMS at runtime via _hrms_enabled.
    "Salary Slip": {
        "before_validate": "oikonomos.financial.salary_slip.populate_instructor_summary",
        "on_submit": "oikonomos.financial.salary_slip.post_submit_instructor_log_payments",
        "on_cancel": "oikonomos.financial.salary_slip.cancel_instructor_log_payments",
    },
    # Provision payroll custom fields when instructor payroll is toggled on.
    "Seminary Settings": {
        "on_update": "oikonomos.financial.salary_slip.on_seminary_settings_update",
    },
}

# Student Balance + Sales Invoice are scoped to the student's own record
# (relocated from seminary; Sales Invoice is an ERPNext doctype).
permission_query_conditions = {
    "Student Balance": "oikonomos.oikonomos.doctype.student_balance.student_balance_permissions.get_permission_query_conditions",
    "Sales Invoice": "oikonomos.financial.sales_invoice_permissions.get_permission_query_conditions",
}
has_permission = {
    "Student Balance": "oikonomos.oikonomos.doctype.student_balance.student_balance_permissions.has_permission",
    "Sales Invoice": "oikonomos.financial.sales_invoice_permissions.has_permission",
}

# Student portal "Financials" page (lists the student's Sales Invoices).
standard_portal_menu_items = [
    {
        "title": "Financials",
        "route": "/financials",
        "reference_doctype": "Sales Invoice",
        "role": "Student",
        "condition": "frappe.get_all('Sales Invoice', filters={'custom_student': frappe.session.user})",
    },
]

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"oikonomos.tasks.all"
# 	],
# 	"daily": [
# 		"oikonomos.tasks.daily"
# 	],
# 	"hourly": [
# 		"oikonomos.tasks.hourly"
# 	],
# 	"weekly": [
# 		"oikonomos.tasks.weekly"
# 	],
# 	"monthly": [
# 		"oikonomos.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "oikonomos.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "oikonomos.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "oikonomos.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "oikonomos.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["oikonomos.utils.before_request"]
# after_request = ["oikonomos.utils.after_request"]

# Job Events
# ----------
# before_job = ["oikonomos.utils.before_job"]
# after_job = ["oikonomos.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"oikonomos.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


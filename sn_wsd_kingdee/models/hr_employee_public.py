# -*- coding: utf-8 -*-
"""The Kingdee fields of an employee, on ``hr.employee.public``.

Odoo serves the employee data to a user without the HR rights through
``hr.employee.public``: ``hr.employee.fetch()`` hands that model every field of a
prefetch group and refuses the ones it does not declare. The fields the
synchronization adds to ``hr.employee`` are therefore declared here too, or
reading an employee -- the shop-floor terminal reads its name -- fails with an
access error naming them. They stay restricted to the HR users, who are the ones
allowed to read the Kingdee data of an employee anyway, so a terminal user
neither fails nor sees it.
"""

from odoo import fields, models


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    kingdee_number = fields.Char(
        related="employee_id.kingdee_number", readonly=True, groups="hr.group_hr_user")
    kingdee_name = fields.Char(
        related="employee_id.kingdee_name", readonly=True, groups="hr.group_hr_user")
    kingdee_master_id = fields.Char(
        related="employee_id.kingdee_master_id", readonly=True, groups="hr.group_hr_user")
    kingdee_sync_state = fields.Selection(
        related="employee_id.kingdee_sync_state", readonly=True, groups="hr.group_hr_user")
    kingdee_last_sync_at = fields.Datetime(
        related="employee_id.kingdee_last_sync_at", readonly=True, groups="hr.group_hr_user")
    kingdee_sync_message = fields.Text(
        related="employee_id.kingdee_sync_message", readonly=True, groups="hr.group_hr_user")

# -*- coding: utf-8 -*-
"""Kingdee employee synchronization for ``hr.employee`` (BD_Empinfo).

Inbound only: the account owns its staff list (72 fields, 7 mandatory, 4 entities),
and an employee created in Odoo would have to be audited in Kingdee before a document
could name them.

What is mirrored is the identity and the place of the employee in the organization:
the name, the account's number on ``kingdee_number``, the department
(``FPostEntity.FPostDept``) and the job position (``FPostEntity.FPost``) — both
resolved through the Kingdee number of the object they point at, so a department or a
position that is not synchronized yet leaves the link empty rather than inventing one.

``FStaffNumber`` (员工编号) is not written anywhere: in this account it holds the same
value as ``FNumber``, which ``kingdee_number`` already keeps. The bank information and
the reporting entities of the form belong to the payroll perimeter, not to this
integration.
"""

from odoo import api, fields, models

from .kingdee_client import EMPLOYEE_FORM_ID

# Fields read from Kingdee (fields_master.csv, BD_Empinfo).
KINGDEE_EMPLOYEE_FIELDS = (
    "FNumber",
    "FName",
    "FStaffNumber",
    "FPostDept.FNumber",
    "FPost.FNumber",
    "FDocumentStatus",
    "FForbidStatus",
)


class HrEmployee(models.Model):
    """An employee of the account, kept in step with BD_Empinfo."""

    _name = "hr.employee"
    _inherit = ["hr.employee", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = EMPLOYEE_FORM_ID
    _kingdee_query_fields = KINGDEE_EMPLOYEE_FIELDS
    # No Odoo field mirrors the employee number: it is stored on kingdee_number, and an
    # employee Odoo already has is adopted through the name.
    _kingdee_number_field = None

    # The synchronization fields of an employee live on ``hr.employee`` only, and the
    # note at the top of ``addons/hr/models/hr_employee.py`` says what that implies: a
    # field that ``hr.employee.public`` does not carry must be restricted to the HR
    # group, because the prefetch of a user who cannot read ``hr.employee`` asks for
    # the whole group and fails on the public profile check -- reading the name of an
    # operator at the shop-floor terminal was enough. ``hr_employee_public.py``
    # declares them on the public model as well, which is the layout the official HR
    # modules use; the group is what keeps them out of that prefetch.
    kingdee_number = fields.Char(groups="hr.group_hr_user")
    kingdee_name = fields.Char(groups="hr.group_hr_user")
    kingdee_master_id = fields.Char(groups="hr.group_hr_user")
    kingdee_sync_state = fields.Selection(groups="hr.group_hr_user")
    kingdee_last_sync_at = fields.Datetime(groups="hr.group_hr_user")
    kingdee_sync_message = fields.Text(groups="hr.group_hr_user")

    def _kingdee_adopt_domain(self, data, number):
        """Adopt the employee Odoo already has, by name."""
        name = (data or {}).get("FName") or ""
        return [("name", "=", name)] if name else []

    @api.model
    def _kingdee_import_extra_values(self, data, form_id=None):
        """Place the employee in the organization the account describes."""
        values = {}
        department = self._kingdee_linked("hr.department", data.get("FPostDept.FNumber"))
        if department:
            values["department_id"] = department.id
        job = self._kingdee_linked("hr.job", data.get("FPost.FNumber"))
        if job:
            values["job_id"] = job.id
        return values

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_employees(self, filter_string="", limit=0, update_existing=True,
                                  create_missing=True, include_disabled=False,
                                  dry_run=False):
        """Read the Kingdee employees and create or update the matching ones."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=EMPLOYEE_FORM_ID,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

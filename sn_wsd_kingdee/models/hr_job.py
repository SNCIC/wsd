# -*- coding: utf-8 -*-
"""Kingdee job position synchronization for ``hr.job`` (HR_ORG_HRPOST).

Inbound only: the account owns its position list (84 fields, 9 mandatory, 6 entities).

The position is one of the two organization links an employee carries
(``FPostEntity.FPost``), so it is synchronized for the same reason a department is:
without it an imported employee has no position to point at.

Odoo's ``hr.job`` is a name and a department. The account also dates a position
(``FEffectDate`` / ``FLapseDate``), attaches role and reporting entities to it, and
all of that belongs to its own HR perimeter — none of it is read here.
"""

from odoo import api, models

from .kingdee_client import JOB_FORM_ID

# Fields read from Kingdee (fields_master.csv, HR_ORG_HRPOST).
KINGDEE_JOB_FIELDS = (
    "FNumber",
    "FName",
    "FDept.FNumber",
    "FDocumentStatus",
    "FForbidStatus",
)


class HrJob(models.Model):
    """A job position of the account, kept in step with HR_ORG_HRPOST."""

    _name = "hr.job"
    _inherit = ["hr.job", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = JOB_FORM_ID
    _kingdee_query_fields = KINGDEE_JOB_FIELDS
    # A position is matched on the Kingdee number only, never on its name: the account
    # repeats a position name across departments (收发料 exists in two of them), so a
    # name is not an identity here.
    _kingdee_number_field = None

    @api.model
    def _kingdee_import_extra_values(self, data, form_id=None):
        """Attach the position to its department when that one is synchronized."""
        department = self._kingdee_linked("hr.department", (data or {}).get("FDept.FNumber"))
        return {"department_id": department.id} if department else {}

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_jobs(self, filter_string="", limit=0, update_existing=True,
                             create_missing=True, include_disabled=False, dry_run=False):
        """Read the Kingdee positions and create or update the matching ones."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=JOB_FORM_ID,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

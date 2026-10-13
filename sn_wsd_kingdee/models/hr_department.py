# -*- coding: utf-8 -*-
"""Kingdee department synchronization for ``hr.department`` (BD_Department).

Inbound only: the account owns its organization tree, and a department created in
Odoo would have to be audited there before it could be used.

``hr.department`` carries no code, so the Kingdee number lives on ``kingdee_number``
and is the **only** link: a department is never adopted through its name, which
would silently re-point a renamed department. The object is referenced by 577 fields
of the account and is what the customer synchronization needs for ``FSALDEPTID``
(销售部门), currently typed by hand in Settings.
"""

from odoo import api, models

from .kingdee_client import DEPARTMENT_FORM_ID

# Fields read from Kingdee (fields_master.csv, BD_Department: 39 fields, 3 mandatory:
# FName, FCreateOrgId, FUseOrgId). The parent department field is not read: its name
# is not in the account index, and a guess would be a wrong field.
KINGDEE_DEPARTMENT_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
)


class HrDepartment(models.Model):
    """A department of the account, kept in step with BD_Department."""

    _inherit = ["hr.department", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = DEPARTMENT_FORM_ID
    _kingdee_query_fields = KINGDEE_DEPARTMENT_FIELDS
    # Nothing in Odoo mirrors the Kingdee number of a department: it is stored on
    # kingdee_number and nothing else is matched.
    _kingdee_number_field = None

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_departments(self, filter_string="", limit=0,
                                    update_existing=True, create_missing=True,
                                    include_disabled=False, dry_run=False):
        """Read the Kingdee departments and create or update the matching ones."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=DEPARTMENT_FORM_ID,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

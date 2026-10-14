# -*- coding: utf-8 -*-
"""Kingdee bank synchronization for ``res.bank`` (BD_BANK).

Inbound only: the account owns its bank list (31 fields, 3 mandatory: ``FName``,
``FCreateOrgId``, ``FUseOrgId``), and a bank is referenced by the bank accounts of its
partners.

Odoo already ships a bank catalogue (``res.bank`` keeps the banks of the standard
data), so a bank is **adopted** when its name is the bank's name - the name identifies
a bank, the code (``YH001``) identifies it in Kingdee, the same rule the currency
import follows with the ISO code and the unit import with the unit name.
"""

from odoo import api, models

from .kingdee_client import BANK_FORM_ID

# Fields read from Kingdee (fields_master.csv, BD_BANK). The address fields of the
# account are not read: they describe the branch and are maintained in Kingdee, where
# the bank is used.
KINGDEE_BANK_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
)


class ResBank(models.Model):
    """A bank of the account, kept in step with BD_BANK."""

    _name = "res.bank"
    _inherit = ["res.bank", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = BANK_FORM_ID
    _kingdee_query_fields = KINGDEE_BANK_FIELDS
    # No Odoo field mirrors the Kingdee number of a bank: it is stored on kingdee_number
    # and an existing bank is adopted through its name.
    _kingdee_number_field = None

    def _kingdee_adopt_domain(self, data, number):
        """Adopt the bank Odoo already has, by name."""
        name = (data or {}).get("FName") or ""
        return [("name", "=", name)] if name else []

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_banks(self, filter_string="", limit=0, update_existing=True,
                              create_missing=True, include_disabled=False,
                              dry_run=False):
        """Read the Kingdee banks and create or update the matching ones."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=BANK_FORM_ID,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

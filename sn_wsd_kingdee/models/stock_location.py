# -*- coding: utf-8 -*-
"""Kingdee warehouse synchronization for ``stock.location`` (BD_STOCK).

Inbound only: the account owns its storage list (57 fields, 6 mandatory, 3 entities),
and a warehouse created in Odoo would have to be audited in Kingdee before a document
could use it.

**Why a location and not a warehouse.** Odoo's ``stock.warehouse`` is the natural
counterpart of a Kingdee 仓库, but its short name is a five character field
(``code = fields.Char(size=5)``) and the account's codes are longer: ``02.01禁用`` is
eight characters, so mirroring the storage list as warehouses would fail on the
account's own data. Creating one also builds a whole tree of picking types and routes
per warehouse, where a document really references a **location**. A storage place is
therefore mirrored as an internal location (``usage='internal'``): the account's code
on ``kingdee_number``, its name on ``name``.

The name is not used to adopt an existing location - a name like 原材料仓 is not an
identity, and this database already carries thousands of internal locations.
"""

from odoo import api, models

from .kingdee_client import STOCK_FORM_ID

# Fields read from Kingdee (fields_master.csv, BD_STOCK). FStockProperty (仓库属性),
# FStockStatusType and FLocListFormatter are the other mandatory fields of the account:
# they describe how Kingdee manages the storage (its statuses and its bin layout), not
# what Odoo stores on a location, so they are not read.
KINGDEE_STOCK_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
)


class StockLocation(models.Model):
    """A storage place of the account, kept in step with BD_STOCK."""

    _inherit = ["stock.location", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = STOCK_FORM_ID
    _kingdee_query_fields = KINGDEE_STOCK_FIELDS
    # Nothing in Odoo mirrors the Kingdee number of a location: it is stored on
    # kingdee_number and nothing else is matched.
    _kingdee_number_field = None

    @api.model
    def _kingdee_import_extra_values(self, data, form_id=None):
        """A storage place of the account is an internal location."""
        if self:
            # An existing location keeps the usage it has: only a location this
            # integration creates is known to be an internal one.
            return {}
        return {"usage": "internal"}

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_stocks(self, filter_string="", limit=0, update_existing=True,
                               create_missing=True, include_disabled=False,
                               dry_run=False):
        """Read the Kingdee warehouses and create or update the matching locations."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=STOCK_FORM_ID,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

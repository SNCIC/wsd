# -*- coding: utf-8 -*-
"""Kingdee batch master file synchronization for ``stock.lot`` (BD_BatchMainFile).

Inbound only: a batch number is born in the account (a receipt, a production order),
never typed in Odoo.

**A lot needs its product.** Odoo requires ``product_id`` on a lot and includes it in
the unique key with the name, so a row whose material is not in Odoo yet is reported
as a failure of that row - explicit and isolated - instead of creating a lot without a
product. The material is resolved through its Kingdee number, then its internal
reference.

**A batch number is only unique per material.** Every material of this account has its
own ``1``, ``01`` or ``·`` (measured on the account), so the identity a lot is matched
and stored by is ``<material>|<batch>`` - not the batch alone, which would make the
second material's batch overwrite the first one's. See ``_kingdee_record_number()``.

**The account's batch master file is a historical record**: the first page of 2000
rows is already full, so a first run is meant to be narrowed with the console's
``Kingdee Filter`` (per material, per date) and ``Batch Limit``.

``FEntityTrace.FBillCancelStatus`` (whether the document a batch came from is
cancelled) is not read: Odoo keeps no such state on a lot, and inventing one here
would be a guess.
"""

from odoo import _, api, models
from odoo.exceptions import UserError

from .kingdee_client import BATCH_FORM_ID

# Fields read from Kingdee (fields_master.csv, BD_BatchMainFile). FName and FNumber are
# both mandatory and hold the same text in this account - the batch itself - and
# FBizType (业务类型) belongs to the account's accounting, not to Odoo.
KINGDEE_BATCH_FIELDS = (
    "FNumber",
    "FName",
    "FMaterialID.FNumber",
    "FDocumentStatus",
    "FForbidStatus",
)


class StockLot(models.Model):
    """A batch of the account, kept in step with BD_BatchMainFile."""

    _inherit = ["stock.lot", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = BATCH_FORM_ID
    _kingdee_query_fields = KINGDEE_BATCH_FIELDS
    # Nothing mirrors the Kingdee number of a batch: it is stored on kingdee_number and
    # a batch is never adopted through its name (batch codes repeat across materials).
    _kingdee_number_field = None

    def _kingdee_record_number(self, data, number):
        """Identity of a batch: its material **and** its number.

        A batch number is unique per material, not in the account: every material has
        its own ``1``, ``01``, ``·``. Storing the number alone would make the second
        material's batch look like the first one's and overwrite it, so what
        ``kingdee_number`` keeps here is ``<material>|<batch>``.
        """
        material = ((data or {}).get("FMaterialID.FNumber") or "").strip()
        return "%s|%s" % (material, number)

    @api.model
    def _kingdee_import_extra_values(self, data, form_id=None):
        """Attach the batch to the material it belongs to."""
        material = ((data or {}).get("FMaterialID.FNumber") or "").strip()
        product = self.env["product.product"].search(
            ["|", ("kingdee_number", "=", material), ("default_code", "=", material)],
            limit=1)
        if not product:
            raise UserError(_(
                "The batch belongs to the material %(number)s, which is not in Odoo: "
                "synchronize the materials first."
            ) % {"number": material or _("(no material in the answer)")})
        return {"product_id": product.id}

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_batches(self, filter_string="", limit=0, update_existing=True,
                                create_missing=True, include_disabled=False,
                                dry_run=False):
        """Read the Kingdee batches and create or update the matching lots."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=BATCH_FORM_ID,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

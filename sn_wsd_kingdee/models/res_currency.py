# -*- coding: utf-8 -*-
"""Kingdee currency synchronization for ``res.currency`` (BD_Currency).

Inbound only: the account owns its currency list, and creating a currency in the
middle of a working ERP is not something a synchronization should do on its own. A
currency Odoo already has is **adopted** through its ISO code instead of being
created twice — the Kingdee number (``PRE001``) identifies the record in Kingdee,
the ISO code (``CNY``) in Odoo — see ``_kingdee_adopt_domain()``.

The object is referenced by 766 fields of the account, which makes it one of the
first master data to have in place before documents (see
``docs/基础资料同步清单.md``).
"""

from odoo import api, models

from .kingdee_client import CURRENCY_FORM_ID

# Fields read from Kingdee (fields_master.csv, BD_Currency: 24 fields, 4 mandatory:
# FName, FNumber, FCODE 货币代码, FRoundType 舍入类型). ``FSYSMBOL`` is the currency
# symbol and is required to create a currency in Odoo 19 at all (the column is NOT
# NULL), so it is read rather than invented.
#
# FRoundType is **not** read: the account defines it as a rounding *mode*
# (枚举 1=四舍五入, 4=四舍六入五双), while Odoo stores a rounding *increment*. The two
# are not the same thing, so nothing is derived from it.
KINGDEE_CURRENCY_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
    "FCODE",
    "FSYSMBOL",
)

# Inbound mapping. The symbol comes straight from the account; ``FCODE`` is handled
# in ``_kingdee_import_extra_values()`` because Odoo keeps the ISO code on ``name``.
KINGDEE_CURRENCY_VALUE_MAP = {
    "FSYSMBOL": "symbol",
}


class ResCurrency(models.Model):
    """A currency of the account, kept in step with BD_Currency."""

    _name = "res.currency"
    _inherit = ["res.currency", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = CURRENCY_FORM_ID
    _kingdee_query_fields = KINGDEE_CURRENCY_FIELDS
    _kingdee_value_map = KINGDEE_CURRENCY_VALUE_MAP
    # The Kingdee number is mirrored on no Odoo field: a currency is named by its ISO
    # code, which is what an existing one is adopted through.
    _kingdee_number_field = None

    def _kingdee_adopt_domain(self, data, number):
        """Adopt the currency Odoo already has, by its ISO code."""
        code = (data or {}).get("FCODE") or ""
        if not code:
            return []
        return [("name", "=", code)]

    @api.model
    def _kingdee_import_extra_values(self, data, form_id=None):
        """Name a currency the account has and Odoo does not.

        Odoo knows a currency by its ISO code (``name``) and shows ``full_name``;
        Kingdee carries the code in ``FCODE`` and the label in ``FName``. The mixin
        names a new record after ``FName``, so the ISO code is set here — and, as the
        mixin keeps a name a hook already provided, this is what gets stored.
        """
        values = {}
        if self and not self.active:
            # Odoo ships about a hundred and fifty currencies and archives most of
            # them. Adopting one has to bring it back: the account uses it, and while
            # it stays archived the next run would keep finding it and writing to a
            # currency nobody can select.
            values["active"] = True
        code = (data or {}).get("FCODE")
        if code:
            values["name"] = code
        label = (data or {}).get("FName")
        if label and "full_name" in self._fields:
            values["full_name"] = label
        return values

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_currencies(self, filter_string="", limit=0, update_existing=True,
                                   create_missing=True, include_disabled=False,
                                   dry_run=False):
        """Read the Kingdee currencies and create or update the matching ones."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=CURRENCY_FORM_ID,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

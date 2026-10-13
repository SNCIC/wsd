# -*- coding: utf-8 -*-
"""Kingdee customer synchronization for ``res.partner``.

The whole skeleton (state, actions, log, notifications) comes from
``sn.wsd.kingdee.sync.mixin``; this file only declares the field mapping. See
``docs/kingdee-接入SOP.md`` for how the mapping was established.
"""

from .kingdee_client import CUSTOMER_FORM_ID
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = ["res.partner", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = CUSTOMER_FORM_ID

    kingdee_currency_number = fields.Char(
        string="Kingdee Settle Currency",
        copy=False,
        help="Kingdee currency number (BD_Currency, e.g. PRE001) sent as the settlement "
             "currency (FTRADINGCURRID) of the customer. The default from Settings "
             "(Kingdee) is used when empty.",
    )

    # ------------------------------------------------------------------
    # Kingdee hooks
    # ------------------------------------------------------------------
    def _kingdee_number(self):
        """Customer number: the Kingdee number, else the partner reference."""
        self.ensure_one()
        return (self.kingdee_number or self.ref or "").strip()

    def _kingdee_payload(self, client):
        """Return the customer Save payload.

        The header fields are sent flat, and only the fields the metadata marks
        as mandatory plus the number are sent: BD_Customer is a base data object,
        and its three mandatory fields (FName, FCreateOrgId, FTRADINGCURRID) all
        belong to the FBillHead entity (see the SOP for the account verification).
        """
        self.ensure_one()
        number = self._kingdee_number()
        currency = ((self.kingdee_currency_number or "").strip()
                    or client.get_setting("customer_currency_number"))
        return {
            "FCreateOrgId": {"FNumber": client.get_default_org("create")},
            "FUseOrgId": {"FNumber": client.get_default_org("use")},
            "FNumber": number,
            "FName": (self.name or "").strip() or number,
            "FTRADINGCURRID": {"FNumber": currency},
        }

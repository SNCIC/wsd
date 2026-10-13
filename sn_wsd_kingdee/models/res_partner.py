# -*- coding: utf-8 -*-
"""Kingdee customer synchronization for ``res.partner``.

The whole skeleton (state, actions, log, notifications) comes from
``sn.wsd.kingdee.sync.mixin``; this file only declares the field mapping. See
``docs/kingdee-接入SOP.md`` for how the mapping was established.
"""

from odoo import _, fields, models
from odoo.exceptions import UserError

from .kingdee_client import CUSTOMER_FORM_ID


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
    kingdee_salesman_number = fields.Char(
        string="Kingdee Salesman",
        copy=False,
        help="Kingdee salesman number (BD_Saler, e.g. 001) sent as FSELLER. This account "
             "refuses a customer without it. The default from Settings (Kingdee) is used "
             "when empty.",
    )
    kingdee_sales_dept_number = fields.Char(
        string="Kingdee Sales Department",
        copy=False,
        help="Kingdee department number (BD_Department) sent as FSALDEPTID. This account "
             "refuses a customer without it. The default from Settings (Kingdee) is used "
             "when empty.",
    )

    # ------------------------------------------------------------------
    # Kingdee hooks
    # ------------------------------------------------------------------
    def _kingdee_number(self):
        """Customer number: the Kingdee number, else the partner reference."""
        self.ensure_one()
        return (self.kingdee_number or self.ref or "").strip()

    def _kingdee_check_ready(self):
        """Refuse early when a field this account requires is not configured.

        The BD_Customer metadata marks only ``FName`` / ``FCreateOrgId`` /
        ``FTRADINGCURRID`` as mandatory, but this account also rejects a customer
        without ``FSELLER`` (销售员) and ``FSALDEPTID`` (销售部门) — verified by
        trial on 2026-10-13 (see the SOP). Failing here shows an actionable
        message instead of the Kingdee one.
        """
        self.ensure_one()
        client = self.env["sn.wsd.kingdee.client"]
        missing = []
        if not self._kingdee_salesman(client):
            missing.append(_("Kingdee Salesman"))
        if not self._kingdee_sales_dept(client):
            missing.append(_("Kingdee Sales Department"))
        if missing:
            raise UserError(_(
                "Set these values in Settings (Kingdee) or on the partner before "
                "synchronizing: %s. This account refuses a customer without them."
            ) % ", ".join(missing))

    def _kingdee_salesman(self, client):
        return ((self.kingdee_salesman_number or "").strip()
                or client.get_setting("customer_salesman_number"))

    def _kingdee_sales_dept(self, client):
        return ((self.kingdee_sales_dept_number or "").strip()
                or client.get_setting("customer_sales_dept_number"))

    def _kingdee_payload(self, client):
        """Return the customer Save payload.

        Header fields are sent flat, and only the fields this account accepts are
        sent: the three the metadata marks as mandatory (FName, FCreateOrgId,
        FTRADINGCURRID) plus the two the account requires (FSELLER, FSALDEPTID).
        """
        self.ensure_one()
        number = self._kingdee_number()
        currency = ((self.kingdee_currency_number or "").strip()
                    or client.get_setting("customer_currency_number"))
        payload = {
            "FCreateOrgId": {"FNumber": client.get_default_org("create")},
            "FUseOrgId": {"FNumber": client.get_default_org("use")},
            "FNumber": number,
            "FName": (self.name or "").strip() or number,
            "FTRADINGCURRID": {"FNumber": currency},
        }
        salesman = self._kingdee_salesman(client)
        if salesman:
            payload["FSELLER"] = {"FNumber": salesman}
        sales_dept = self._kingdee_sales_dept(client)
        if sales_dept:
            payload["FSALDEPTID"] = {"FNumber": sales_dept}
        return payload

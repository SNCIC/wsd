# -*- coding: utf-8 -*-
"""Kingdee customer synchronization for ``res.partner``.

The whole skeleton (state, actions, log, notifications, inbound import) comes from
``sn.wsd.kingdee.sync.mixin``; this file only declares the field mapping. See
``docs/kingdee-接入SOP.md`` for how the mapping was established.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .kingdee_client import CUSTOMER_FORM_ID
from .kingdee_sync_mixin import KINGDEE_PENDING_STATES

# Customer fields read from Kingdee, in the BillQuery notation. They come from the
# account field index (fields_master.csv, BD_Customer); a reference is read through
# .FNumber (the form the payload sends) and .FName, so the screen can show the code
# and what it stands for.
KINGDEE_CUSTOMER_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FTRADINGCURRID.FNumber",
    "FTRADINGCURRID.FName",
    "FSELLER.FNumber",
    "FSELLER.FName",
    "FSALDEPTID.FNumber",
    "FSALDEPTID.FName",
)

# Inbound field mapping (Kingdee field -> Odoo field). It holds the values the
# outbound payload derives from a partner, so a customer imported here can be pushed
# back without any value changing, plus the names of the codes for the screen.
KINGDEE_CUSTOMER_VALUE_MAP = {
    "FTRADINGCURRID.FNumber": "kingdee_currency_number",
    "FTRADINGCURRID.FName": "kingdee_currency_name",
    "FSELLER.FNumber": "kingdee_salesman_number",
    "FSELLER.FName": "kingdee_salesman_name",
    "FSALDEPTID.FNumber": "kingdee_sales_dept_number",
    "FSALDEPTID.FName": "kingdee_sales_dept_name",
}

# Number of records one "push to Kingdee" click sends at most: the outbound
# direction writes to the shared account, so a click must stay bounded.
PUSH_BATCH_LIMIT = 50


class ResPartner(models.Model):
    _inherit = ["res.partner", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = CUSTOMER_FORM_ID
    _kingdee_query_fields = KINGDEE_CUSTOMER_FIELDS
    _kingdee_value_map = KINGDEE_CUSTOMER_VALUE_MAP
    _kingdee_number_field = "ref"

    kingdee_currency_number = fields.Char(
        string="Kingdee Settle Currency", copy=False,
        help="Kingdee currency number (BD_Currency, e.g. PRE001) sent as the settlement "
             "currency (FTRADINGCURRID) of the customer. The default from Settings "
             "(Kingdee) is used when empty.",
    )
    kingdee_currency_name = fields.Char(
        string="Kingdee Currency Name", copy=False, readonly=True,
        help="Name the account gives to the currency above (FTRADINGCURRID), so the "
             "screen shows the code and what it stands for. Read from Kingdee.",
    )
    kingdee_salesman_number = fields.Char(
        string="Kingdee Salesman", copy=False,
        help="Kingdee salesman number (BD_Saler, e.g. 001) sent as FSELLER. This account "
             "refuses a customer without it. The default from Settings (Kingdee) is used "
             "when empty.",
    )
    kingdee_salesman_name = fields.Char(
        string="Kingdee Salesman Name", copy=False, readonly=True,
        help="Name the account gives to the salesman above (FSELLER), so the screen shows "
             "the code and what it stands for. Read from Kingdee.",
    )
    kingdee_sales_dept_number = fields.Char(
        string="Kingdee Sales Department", copy=False,
        help="Kingdee department number (BD_Department) sent as FSALDEPTID. This account "
             "refuses a customer without it. The default from Settings (Kingdee) is used "
             "when empty.",
    )
    kingdee_sales_dept_name = fields.Char(
        string="Kingdee Department Name", copy=False, readonly=True,
        help="Name the account gives to the department above (FSALDEPTID), so the screen "
             "shows the code and what it stands for. Read from Kingdee.",
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

        The **platform** metadata marks only ``FName`` / ``FCreateOrgId`` /
        ``FTRADINGCURRID`` as mandatory, but the **account** metadata marks
        ``FSELLER`` (销售员) and ``FSALDEPTID`` (销售部门) as mandatory too — both
        are ``必录=Y`` in ``fields_master.csv`` (the account-first master index),
        and the account rejects a customer without them. The two sources disagree
        on this form, so read the master index rather than the registration tree;
        checking it here shows an actionable message instead of the Kingdee one.
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

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_partners(self, filter_string="", limit=0, update_existing=True,
                                 create_missing=True, include_disabled=False,
                                 dry_run=False):
        """Read the Kingdee customers and create or update the matching partners."""
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
        )
        return self._kingdee_import_notification(summary, dry_run=dry_run)

    @api.model
    def _kingdee_push_partners(self, filter_string="", limit=0, dry_run=False):
        """Save the customers that can be identified and are not in sync yet.

        Only one batch is sent per call (see ``PUSH_BATCH_LIMIT``): this direction
        writes to the shared Kingdee account, so a click must stay bounded.
        """
        partners = self.search([
            ("kingdee_sync_state", "in", KINGDEE_PENDING_STATES),
            "|", ("kingdee_number", "!=", False), ("ref", "!=", False),
        ], limit=limit or PUSH_BATCH_LIMIT, order="id")
        if dry_run:
            return self._kingdee_notify(_("Kingdee"), _(
                "Preview push to Kingdee: %s customer(s) to send.") % len(partners))
        if not partners:
            return self._kingdee_notify(_("Kingdee"), _(
                "Push to Kingdee: every customer is already in sync."))
        return partners.action_kingdee_save()

# -*- coding: utf-8 -*-
"""Kingdee partner synchronization for ``res.partner``.

The whole skeleton (state, actions, log, notifications, inbound import) comes from
``sn.wsd.kingdee.sync.mixin``; this file declares the two roles a partner plays in
the account and their field mappings. See ``docs/kingdee-接入SOP.md`` for how a
mapping was established and ``docs/基础资料同步清单.md`` for the master data map of
the account.

Odoo keeps a customer and a vendor in the same model (``customer_rank`` /
``supplier_rank``) and so does Kingdee: a partner may be a customer, a vendor or
both, and the account numbers the two independently. The partner therefore carries
**two** Kingdee links, declared per object in ``_kingdee_form_fields``, which is what
keeps the customer run and the vendor run apart. Without it the 831 vendors of this
database would be sent to Kingdee as customers.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .kingdee_client import CUSTOMER_FORM_ID, SUPPLIER_FORM_ID
from .kingdee_sync_mixin import KINGDEE_PENDING_STATES, KINGDEE_SYNC_STATES

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

# Vendor fields read from Kingdee (fields_master.csv, BD_Supplier: 119 fields, 8 of
# them mandatory). Kept to the number, the name, the state and the settlement
# currency: the four mandatory fields of the account that live in the location
# sub-entity (FLocationInfo: name, address, mobile, contact) describe the vendor's
# site, not the Odoo partner, and are not read here.
KINGDEE_SUPPLIER_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
    "FPayCurrencyId.FNumber",
    "FPayCurrencyId.FName",
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

# Vendor mapping. The vendor is read only for now: its payload is not established
# yet (the console lists the vendor push as not implemented), so this holds what the
# screen shows of the account value.
KINGDEE_SUPPLIER_VALUE_MAP = {
    "FPayCurrencyId.FNumber": "kingdee_supplier_currency_number",
    "FPayCurrencyId.FName": "kingdee_supplier_currency_name",
}

# Number of records one "push to Kingdee" click sends at most: the outbound
# direction writes to the shared account, so a click must stay bounded.
PUSH_BATCH_LIMIT = 50


class ResPartner(models.Model):
    _inherit = ["res.partner", "sn.wsd.kingdee.sync.mixin"]

    # A partner is pushed to Kingdee as a customer: that is the object its payload
    # was established for. The vendor direction is inbound only for now.
    _kingdee_form_id = CUSTOMER_FORM_ID
    _kingdee_number_field = "ref"
    _kingdee_query_fields = KINGDEE_CUSTOMER_FIELDS
    _kingdee_value_map = KINGDEE_CUSTOMER_VALUE_MAP
    _kingdee_form_fields = {
        SUPPLIER_FORM_ID: {
            "number": "kingdee_supplier_number",
            "name": "kingdee_supplier_name",
            "master_id": "kingdee_supplier_master_id",
            "state": "kingdee_supplier_state",
            "last_sync": "kingdee_supplier_last_sync_at",
            "message": "kingdee_supplier_message",
        },
    }

    @classmethod
    def _kingdee_query_fields_for(cls, form_id=None):
        """FieldKeys read from the account: the two objects carry different fields."""
        if cls._kingdee_form(form_id) == SUPPLIER_FORM_ID:
            return KINGDEE_SUPPLIER_FIELDS
        return KINGDEE_CUSTOMER_FIELDS

    @classmethod
    def _kingdee_value_map_for(cls, form_id=None):
        """Kingdee key -> Odoo field, per object."""
        if cls._kingdee_form(form_id) == SUPPLIER_FORM_ID:
            return KINGDEE_SUPPLIER_VALUE_MAP
        return KINGDEE_CUSTOMER_VALUE_MAP

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
    # Vendor link (BD_Supplier)
    # ------------------------------------------------------------------
    kingdee_supplier_number = fields.Char(
        string="Kingdee Supplier Number", copy=False, index=True,
        help="Number (FNumber) of this partner in Kingdee BD_Supplier. The account "
             "numbers its customers and its vendors independently, so a partner that is "
             "both keeps the two numbers side by side.",
    )
    kingdee_supplier_name = fields.Char(
        string="Kingdee Supplier Name", copy=False, readonly=True,
        help="Name (FName) the account gives to the vendor above.",
    )
    kingdee_supplier_master_id = fields.Char(
        string="Kingdee Supplier Master ID", copy=False, readonly=True,
    )
    kingdee_supplier_state = fields.Selection(
        KINGDEE_SYNC_STATES, string="Kingdee Supplier Status",
        default="not_synced", copy=False, readonly=True,
        help="Synchronization state of the vendor link, kept apart from the customer "
             "one: the two are read and sent independently.",
    )
    kingdee_supplier_last_sync_at = fields.Datetime(
        string="Kingdee Supplier Last Sync", copy=False, readonly=True,
    )
    kingdee_supplier_message = fields.Text(
        string="Kingdee Supplier Message", copy=False, readonly=True,
    )
    kingdee_supplier_currency_number = fields.Char(
        string="Kingdee Supplier Currency", copy=False,
        help="Settlement currency of the vendor in Kingdee (FPayCurrencyId of "
             "BD_Supplier, a BD_Currency number such as PRE001). Read from Kingdee.",
    )
    kingdee_supplier_currency_name = fields.Char(
        string="Kingdee Supplier Currency Name", copy=False, readonly=True,
        help="Name the account gives to the vendor currency above.",
    )

    _kingdee_supplier_number_unique = models.Constraint(
        "UNIQUE(kingdee_supplier_number)",
        "The Kingdee supplier number must be unique.",
    )

    # ------------------------------------------------------------------
    # Kingdee hooks
    # ------------------------------------------------------------------
    def _kingdee_number(self):
        """Customer number: the Kingdee customer number, else the partner reference."""
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

    @api.model
    def _kingdee_target_domain(self, form_id=None):
        """Partners one console row applies to: a vendor is not a customer.

        The old rule took every partner carrying a reference, which would have sent
        the 831 vendors to Kingdee as customers. The role is read from the Odoo rank
        (``account``) or from the link already established with that object.
        """
        form = self._kingdee_form(form_id)
        if form == SUPPLIER_FORM_ID:
            domain = [("kingdee_supplier_number", "!=", False)]
            if "supplier_rank" in self._fields:
                return ["|", ("supplier_rank", ">", 0)] + domain
            return domain
        domain = [("kingdee_number", "!=", False)]
        if "customer_rank" in self._fields:
            return ["|", ("customer_rank", ">", 0)] + domain
        return domain

    @api.model
    def _kingdee_import_extra_values(self, data, form_id=None):
        """Mark the role the imported partner plays in Odoo.

        A partner read from BD_Supplier is a vendor: without the rank it would be a
        plain contact (invisible to a purchase order) and a later customer run would
        try to send it to Kingdee as a customer. Odoo only carries the two ranks when
        ``account`` is installed, so they are written only when they are there.
        """
        values = {}
        if self._kingdee_form(form_id) == SUPPLIER_FORM_ID:
            if "supplier_rank" in self._fields:
                values["supplier_rank"] = max(self.supplier_rank or 0, 1)
            return values
        if "customer_rank" in self._fields:
            values["customer_rank"] = max(self.customer_rank or 0, 1)
        return values

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_customers(self, filter_string="", limit=0, update_existing=True,
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
            form_id=CUSTOMER_FORM_ID,
        )
        return self._kingdee_import_notification(
            summary, dry_run=dry_run, entity=_("Customers"))

    @api.model
    def _kingdee_import_suppliers(self, filter_string="", limit=0, update_existing=True,
                                  create_missing=True, include_disabled=False,
                                  dry_run=False):
        """Read the Kingdee vendors and create or update the matching partners.

        Matching goes through ``kingdee_supplier_number`` first and the partner
        reference second, the same way a customer is matched, so an existing vendor
        list gets linked instead of duplicated.
        """
        summary = self._kingdee_import_records(
            filter_string=filter_string,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=SUPPLIER_FORM_ID,
        )
        return self._kingdee_import_notification(
            summary, dry_run=dry_run, entity=_("Suppliers"))

    @api.model
    def _kingdee_push_customers(self, filter_string="", limit=0, dry_run=False):
        """Save the customers that can be identified and are not in sync yet.

        Only one batch is sent per call (see ``PUSH_BATCH_LIMIT``): this direction
        writes to the shared Kingdee account, so a click must stay bounded. Only the
        partners that **are** customers are taken, see ``_kingdee_target_domain()``.
        """
        partners = self.search(
            self._kingdee_target_domain(CUSTOMER_FORM_ID)
            + [("kingdee_sync_state", "in", KINGDEE_PENDING_STATES)],
            limit=limit or PUSH_BATCH_LIMIT, order="id")
        if dry_run:
            return self._kingdee_notify(_("Kingdee"), _(
                "Preview push to Kingdee: %s customer(s) to send.") % len(partners))
        if not partners:
            return self._kingdee_notify(_("Kingdee"), _(
                "Push to Kingdee: every customer is already in sync."))
        return partners.action_kingdee_save()

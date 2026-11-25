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

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .kingdee_client import CUSTOMER_FORM_ID, SUPPLIER_FORM_ID
from .kingdee_sync_mixin import KINGDEE_PENDING_STATES, KINGDEE_SYNC_STATES

_logger = logging.getLogger(__name__)

# Customer fields read from Kingdee, in the BillQuery notation. They come from the
# account field index (fields_master.csv, BD_Customer); a reference is read through
# .FNumber (the form the payload sends) and .FName, so the screen can show the code
# and what it stands for. The ISO code of the currency (.FCODE) is read beside the
# number because Odoo knows a currency by its ISO code, never by the Kingdee number
# (see ``_kingdee_currency`` below).
#
# Two groups of fields describe the invoicing side of the customer rather than the
# account number: the invoicing block (FINVOICETITLE / FINVOICEBANKNAME /
# FINVOICEBANKACCOUNT / FINVOICETEL / FINVOICEADDRESS, stored by the account in
# T_BD_CUSTOMER_F) and the two fields this account added to the form:
# ``F_QNBG_Text`` (发货代号, the delivery code) and ``F_QNBG_Remark`` (发货地址, the
# delivery site). Both are account-level customisations, not platform fields: their
# keys were read from the form metadata, never guessed from a naming habit.
KINGDEE_CUSTOMER_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FTRADINGCURRID.FNumber",
    "FTRADINGCURRID.FCODE",
    "FTRADINGCURRID.FName",
    "FSELLER.FNumber",
    "FSELLER.FName",
    "FSALDEPTID.FNumber",
    "FSALDEPTID.FName",
    "FRECCONDITIONID.FNumber",
    "FRECCONDITIONID.FName",
    "FTEL",
    "FADDRESS",
    "FINVOICETITLE",
    "FINVOICEBANKNAME",
    "FINVOICEBANKACCOUNT",
    "FINVOICETEL",
    "FINVOICEADDRESS",
    "FTAXREGISTERCODE",
    "F_QNBG_Text",
    "F_QNBG_Remark",
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
#
# The invoicing block and the two account-level delivery fields land on the fields
# ``sn_wsd_partner`` declares. They are written only when that module is installed
# (``_kingdee_base_values()`` skips a field the model does not carry), so this
# integration still runs on a database without it.
KINGDEE_CUSTOMER_VALUE_MAP = {
    "FTRADINGCURRID.FNumber": "kingdee_currency_number",
    "FTRADINGCURRID.FName": "kingdee_currency_name",
    "FSELLER.FNumber": "kingdee_salesman_number",
    "FSELLER.FName": "kingdee_salesman_name",
    "FSALDEPTID.FNumber": "kingdee_sales_dept_number",
    "FSALDEPTID.FName": "kingdee_sales_dept_name",
    "FRECCONDITIONID.FNumber": "sn_rec_condition_number",
    "FRECCONDITIONID.FName": "sn_rec_condition_name",
    "FINVOICETITLE": "sn_invoice_title",
    "FINVOICEBANKNAME": "sn_invoice_bank_name",
    "FINVOICETEL": "sn_invoice_phone",
    "FINVOICEADDRESS": "sn_invoice_address",
    "F_QNBG_Text": "sn_delivery_code",
    "F_QNBG_Remark": "sn_delivery_address",
}

# Vendor mapping. The vendor is read only for now: its payload is not established
# yet (the console lists the vendor push as not implemented), so this holds what the
# screen shows of the account value.
KINGDEE_SUPPLIER_VALUE_MAP = {
    "FPayCurrencyId.FNumber": "kingdee_supplier_currency_number",
    "FPayCurrencyId.FName": "kingdee_supplier_currency_name",
}

# BillQuery answers the FieldKeys it was sent ("FTRADINGCURRID.FNumber"), a View
# answers the **property names of the form** ("TRADINGCURRID" with a nested
# "Number", "INVOICETITLE" without the F prefix, "TEL", "ADDRESS"). The read-back
# ("Refresh from Kingdee") is a View, so the keys it stores are translated here;
# without this table a View would answer nothing and the read-back would write
# nothing but the synchronization state.
#
# ``FTRADINGCURRID.FCODE`` has no counterpart in a View: the currency entity of
# the form carries the number and the name only, never the ISO code. The settlement
# currency therefore keeps the value the import wrote when a record is refreshed.
KINGDEE_VIEW_KEYS = {
    "FNumber": "Number",
    "FName": "Name",
    "FDocumentStatus": "DocumentStatus",
    "FTRADINGCURRID.FNumber": "TRADINGCURRID.Number",
    "FTRADINGCURRID.FName": "TRADINGCURRID.Name",
    "FSELLER.FNumber": "SELLER.Number",
    "FSELLER.FName": "SELLER.Name",
    "FSALDEPTID.FNumber": "SALDEPTID.Number",
    "FSALDEPTID.FName": "SALDEPTID.Name",
    "FRECCONDITIONID.FNumber": "RECCONDITIONID.Number",
    "FRECCONDITIONID.FName": "RECCONDITIONID.Name",
    "FTEL": "TEL",
    "FADDRESS": "ADDRESS",
    "FINVOICETITLE": "INVOICETITLE",
    "FINVOICEBANKNAME": "INVOICEBANKNAME",
    "FINVOICEBANKACCOUNT": "INVOICEBANKACCOUNT",
    "FINVOICETEL": "INVOICETEL",
    "FINVOICEADDRESS": "INVOICEADDRESS",
}

# Number of records one "push to Kingdee" click sends at most: the outbound
# direction writes to the shared account, so a click must stay bounded.
PUSH_BATCH_LIMIT = 50


class ResPartner(models.Model):
    _name = "res.partner"
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

    @classmethod
    def _kingdee_data_from_view(cls, data, form_id=None):
        """Normalise a View answer to the BillQuery key shape.

        A View answers the property names of the form, a query the FieldKeys it was
        sent; ``KINGDEE_VIEW_KEYS`` translates the second into the first, so a
        read-back fills the same values an import does (see the table above).
        """
        values = {}
        for key in cls._kingdee_query_fields_for(form_id):
            view_key = KINGDEE_VIEW_KEYS.get(key, key)
            values[key] = cls._kingdee_text(cls._kingdee_nested_value(data, view_key))
        return values

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
        """Mark the role the imported partner plays in Odoo, and derive the rest.

        A partner read from BD_Supplier is a vendor: without the rank it would be a
        plain contact (invisible to a purchase order) and a later customer run would
        try to send it to Kingdee as a customer. Odoo only carries the two ranks when
        ``account`` is installed, so they are written only when they are there.

        A customer row also carries values that land on another Odoo object than the
        one of the same name (a currency, a payment term, a user) and a phone and an
        address that fall back to the invoicing block; see
        ``_kingdee_customer_values()``.
        """
        values = {}
        if self._kingdee_form(form_id) == SUPPLIER_FORM_ID:
            if "supplier_rank" in self._fields:
                values["supplier_rank"] = max(self.supplier_rank or 0, 1)
            return values
        if "customer_rank" in self._fields:
            values["customer_rank"] = max(self.customer_rank or 0, 1)
        values.update(self._kingdee_customer_values(data))
        return values

    def _kingdee_customer_values(self, data):
        """Odoo values of a customer row that are not a straight field mapping.

        * the settlement currency is a ``res.currency`` claimed by ISO code;
        * the receivable condition is an ``account.payment.term`` claimed by the
          Kingdee number an administrator stores on it;
        * the salesman is an Odoo user claimed by name, and only when the partner
          has none yet (a hand-picked salesman is never overwritten);
        * the phone and the address fall back to the invoicing block: in this
          account FTEL / FADDRESS are mostly empty while FINVOICETEL /
          FINVOICEADDRESS carry the real value (349 customers read on 2026-11-25).
        """
        values = {}
        currency = self._kingdee_currency(data)
        if currency and "sn_settlement_currency_id" in self._fields:
            values["sn_settlement_currency_id"] = currency.id
        term = self._kingdee_payment_term(data)
        if term and "property_payment_term_id" in self._fields:
            values["property_payment_term_id"] = term.id
        salesman = self._kingdee_salesman_user(data)
        if salesman and "user_id" in self._fields and not self.user_id:
            values["user_id"] = salesman.id
        phone = (data or {}).get("FTEL") or (data or {}).get("FINVOICETEL")
        if phone:
            values["phone"] = phone
        address = (data or {}).get("FADDRESS") or (data or {}).get("FINVOICEADDRESS")
        if address:
            values["street"] = address
        return values

    def _kingdee_currency(self, data):
        """Odoo currency standing for the settlement currency of a row.

        The account numbers its currencies (PRE001 for 人民币) and Odoo names them
        by ISO code (CNY), and the two do not agree: the Kingdee number stored on
        an Odoo currency is whatever the currency run wrote, which is not the
        number this customer references. The ISO code (``FCODE``) is the value the
        two sides share, so it is what the currency is claimed by.
        """
        code = ((data or {}).get("FTRADINGCURRID.FCODE") or "").strip()
        if not code:
            return self.env["res.currency"].browse()
        return self.env["res.currency"].with_context(active_test=False).search(
            [("name", "=", code)], limit=1)

    def _kingdee_payment_term(self, data):
        """Odoo payment term standing for the receivable condition of a row.

        The account conditions (BD_RecCondition: ``100%预收``, ``票后1个月``) are
        instalment schemes — a percentage, a prepaid flag and a due-date algorithm
        per line — while an Odoo term is a percentage/days line: the two are not
        one to one, so nothing is derived from the account. An Odoo term is claimed
        through the ``kingdee_number`` an administrator fills on it; a condition
        nobody mapped leaves the term empty, and the raw number and name stay on
        ``sn_rec_condition_number`` / ``sn_rec_condition_name``.
        """
        number = ((data or {}).get("FRECCONDITIONID.FNumber") or "").strip()
        if not number:
            return self.env["account.payment.term"].browse()
        return self.env["account.payment.term"].search(
            [("kingdee_number", "=", number)], limit=1)

    def _kingdee_salesman_user(self, data):
        """Odoo user the salesman of a row stands for, when the account has one.

        The account salesmen (BD_Saler) are not Odoo users: ``胡茜茜`` has no user
        account in this database. The name is the only value the two share, so it
        is what a user is claimed by; a customer whose salesman has no user keeps
        the Kingdee number and name the mapping already stores.
        """
        name = ((data or {}).get("FSELLER.FName") or "").strip()
        if not name:
            return self.env["res.users"].browse()
        return self.env["res.users"].with_context(active_test=False).search(
            [("name", "=", name)], limit=1)

    def _kingdee_import_done(self, data, form_id=None):
        """Store what a customer row carries beside the contact itself.

        The invoicing bank account is a ``res.partner.bank`` of the contact, and the
        tax number goes through the ``vat`` validation (``base_vat`` refuses a
        format it does not know): neither can travel in the values written on the
        contact without risking the whole row, so both run once the contact exists.
        """
        if self._kingdee_form(form_id) != CUSTOMER_FORM_ID:
            return
        self._kingdee_store_invoice_bank(data)
        self._kingdee_store_vat(data)

    def _kingdee_store_invoice_bank(self, data):
        """Link the invoicing bank account of the row to the contact.

        The number identifies the account inside the contact (Odoo keeps
        ``sanitized_acc_number`` unique per partner), which makes a second run
        update the same record instead of adding another one. The bank name the
        account carries is the branch the customer banks at, while ``res.bank``
        holds the bank itself: only an exact match is claimed and no bank is
        created, otherwise every customer branch would become a bank.
        """
        account = ((data or {}).get("FINVOICEBANKACCOUNT") or "").strip()
        if not account:
            return
        bank_name = ((data or {}).get("FINVOICEBANKNAME") or "").strip()
        Bank = self.env["res.partner.bank"].with_context(
            sn_skip_supplier_finance_check=True).sudo()
        existing = Bank.search([
            ("partner_id", "=", self.id),
            ("acc_number", "=", account),
        ], limit=1)
        bank = (self.env["res.bank"].search([("name", "=", bank_name)], limit=1)
                if bank_name else self.env["res.bank"].browse())
        if existing:
            if bank and existing.bank_id != bank:
                existing.write({"bank_id": bank.id})
            return
        Bank.create({
            "partner_id": self.id,
            "acc_number": account,
            "bank_id": bank.id if bank else False,
        })

    def _kingdee_store_vat(self, data):
        """Store the tax number of the row, tolerating a format Odoo refuses.

        ``base_vat`` validates ``vat`` against the country format and raises for a
        number it does not know; a rejected number is reported and dropped rather
        than failing the customer, whose other values have been written already.
        """
        vat = ((data or {}).get("FTAXREGISTERCODE") or "").strip()
        if not vat or "vat" not in self._fields:
            return
        try:
            with self.env.cr.savepoint():
                self.write({"vat": vat})
        except Exception as err:  # noqa: BLE001 - reported, the row must be kept
            _logger.warning(
                "Kingdee tax number %s refused for partner %s: %s", vat, self.id, err,
            )

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

# -*- coding: utf-8 -*-
"""Skeleton of a **document** pushed to Kingdee (bill, not master data).

A master record is identified by an ``FNumber`` and can be saved again and again:
saving it twice is the same record. A document is different in four ways, and each
one is handled here rather than in every adapter:

* **Identity is the document number** (``FBillNo``), taken from the Odoo document
  name. Saving the same number again updates the document instead of creating a
  second one, which is what makes a retry safe.
* **A document that is only saved does not move anything.** The account books the
  stock and the cost when the document is *audited*, so a push runs Save, then
  Submit, then Audit (``auto_audit`` on the mapping row). An audit refused because
  the document already reached that state is not an error.
* **The account's mandatory fields are account data**: organizations, owner and
  keeper types, stock statuses, warehouse keeper and acceptance employee, bill type
  and other operation type. They come from the account row and the mapping row, and
  a missing one is reported *before* the call (``_kingdee_bill_check_ready()``)
  instead of coming back as an opaque Kingdee error.
* **A push must be provable.** After the audit the document is read back and its
  number, status and amount are compared with what was sent: the acceptance
  criteria of the migration ("回读逐字段一致", "推送成功率 100%") need that evidence,
  and the daily report is built from it.

Push happens after the business transaction commits (``_kingdee_defer_push()``):
a Kingdee outage must never roll back a validated transfer, and an Odoo rollback
must never leave a Kingdee document behind. The fallback is the scheduled action,
which retries the failed documents with a growing delay.
"""

import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError

from .kingdee_sync_mixin import CLIENT_MODEL, KINGDEE_PENDING_STATES

_logger = logging.getLogger(__name__)

# Back-off of a failed push, in minutes, indexed on the attempt number. A document
# that keeps failing stops being retried after the last step and waits for a human:
# the migration reports the failures of the day, it does not hammer the account.
RETRY_DELAYS = (10, 30, 120, 360, 1440)

# Audit answers that mean "the document already is where we want it". The account
# words them in Chinese; the SDK does not give a machine readable code for them.
BENIGN_ACTION_ERRORS = (
    "已提交", "已经提交", "已审核", "已经审核", "重复提交", "重复审核",
    "already submitted", "already audited",
)

# Quantity field of each document kind, read from the account metadata. They differ
# on purpose: a purchase receipt counts ``FRealQty`` (实收), a purchase order
# ``FQty`` (采购数量), a purchase return ``FRMREALQTY`` (实退), a material issue
# ``FActualQty`` (实发). Sending the wrong one is accepted and books nothing.
QTY_FIELDS = {
    "purchase_order": "FQty",
    "receipt": "FRealQty",
    "vendor_return": "FRMREALQTY",
    "sale_order": "FQty",
    "delivery": "FRealQty",
    "sale_return": "FRealQty",
    "other_in": "FQty",
    "other_out": "FQty",
    "internal_transfer": "FQty",
    "production_order": "FQty",
    "mes_issue": "FActualQty",
    "mes_over_pick": "FActualQty",
    "mes_return": "FQty",
    "mes_fg_receipt": "FRealQty",
}


class SnWsdKingdeeBillMixin(models.AbstractModel):
    """A document pushed to Kingdee: identity, lifecycle, verification, retry."""

    _name = "sn.wsd.kingdee.bill.mixin"
    _inherit = ["sn.wsd.kingdee.sync.mixin"]
    _description = "Kingdee Pushed Document"

    # Kind of document, see sn.wsd.kingdee.bill.map.BILL_KINDS.
    _kingdee_bill_kind_default = None

    kingdee_push_attempts = fields.Integer(
        string="Push Attempts", default=0, readonly=True, copy=False,
        help="Failed pushes since the last success. The delay before the next "
             "attempt grows with it.",
    )
    kingdee_next_retry_at = fields.Datetime(
        string="Next Retry", readonly=True, copy=False,
        help="A failed document is retried by the scheduled action from this time.",
    )
    kingdee_pushed_at = fields.Datetime(string="Pushed At", readonly=True, copy=False)
    kingdee_verified_at = fields.Datetime(
        string="Verified At", readonly=True, copy=False,
        help="Time of the read-back that matched the document that was sent.",
    )
    kingdee_pushed_qty = fields.Float(
        string="Pushed Quantity", readonly=True, copy=False, digits=(16, 4),
        help="Quantity read back from Kingdee, compared with the Odoo one.",
    )
    kingdee_pushed_amount = fields.Float(
        string="Pushed Amount", readonly=True, copy=False, digits=(16, 4),
        help="Amount read back from Kingdee, compared with the Odoo one.",
    )

    # ------------------------------------------------------------------
    # Identity of the document
    # ------------------------------------------------------------------
    def _kingdee_bill_kind(self):
        """Business kind of the document, used to find its mapping row."""
        self.ensure_one()
        if self._kingdee_bill_kind_default:
            return self._kingdee_bill_kind_default
        raise NotImplementedError("_kingdee_bill_kind() must be implemented")

    def _kingdee_number(self):
        """``FBillNo`` of the document: the Odoo name, so a retry updates it.

        Keeping the Odoo name makes the two systems reconcilable line by line: the
        double entry month of the migration asks for exactly that ("两边单号互相
        备注"), and the number stays unique per kind.
        """
        self.ensure_one()
        return (self.kingdee_number or self.name or "").strip()

    def _kingdee_bill_map(self):
        """Active mapping row of this document kind."""
        self.ensure_one()
        map_row = self.env["sn.wsd.kingdee.bill.map"]._for_kind(
            self._kingdee_bill_kind(), self._name)
        if not map_row:
            raise UserError(_(
                "%(document)s has no active Kingdee mapping: configure the document "
                "kind %(kind)s in Kingdee > Documents.",
            ) % {
                "document": self.display_name,
                "kind": self._kingdee_bill_kind(),
            })
        return map_row

    def _kingdee_form(self, form_id=None):
        """Kingdee object of this document (the mapping row decides)."""
        if form_id:
            return form_id
        return self._kingdee_bill_map().form_id

    # ------------------------------------------------------------------
    # Account values and reference helpers
    # ------------------------------------------------------------------
    def _kd_account(self):
        """Kingdee account of the company of the document."""
        company = self.company_id or self.env.company
        return self.env["sn.wsd.kingdee.account"]._for_company(company)

    def _kd_org(self, kind="create"):
        account = self._kd_account()
        if account:
            return account._org_number(kind)
        return self.env[CLIENT_MODEL].get_default_org(kind)

    @staticmethod
    def _kd_ref(number):
        """Reference to a Kingdee record by its number, or False.

        A reference is always sent by number: an internal id works in the test
        account and fails in production (SOP well known trap 3).
        """
        number = (number or "").strip() if isinstance(number, str) else number
        return {"FNumber": number} if number else False

    @staticmethod
    def _kd_put(values, key, value):
        """Write ``key`` in ``values`` unless the value would be empty."""
        if value in (None, False, "", []):
            return values
        values[key] = value
        return values

    def _kd_currency_number(self, currency=None):
        currency = currency or self.company_id.currency_id or self.env.company.currency_id
        number = (getattr(currency, "kingdee_number", False) or "").strip()
        if number:
            return number
        account = self._kd_account()
        return (account.default_currency_number if account else "") or "PRE001"

    def _kd_uom_number(self, uom):
        number = (getattr(uom, "kingdee_number", False) or "").strip()
        if number:
            return number
        return self.env[CLIENT_MODEL].get_unit_number()

    def _kd_partner_number(self, partner, role="customer"):
        """Kingdee number of a partner, in the role of the document.

        A partner is both a customer and a supplier and the account numbers the two
        roles independently, so the role decides which field is read.
        """
        if not partner:
            return ""
        if role == "supplier":
            number = (getattr(partner, "kingdee_supplier_number", False) or "").strip()
        else:
            number = (getattr(partner, "kingdee_number", False) or "").strip()
        return number or (partner.ref or "").strip() or (partner.name or "").strip()

    @staticmethod
    def _kd_product_number(product):
        """Kingdee number of a product: the variant, then its template."""
        if not product:
            return ""
        number = (getattr(product, "kingdee_number", False) or "").strip()
        if number:
            return number
        template = product.product_tmpl_id
        return (getattr(template, "kingdee_number", False) or "").strip() \
            or (product.default_code or "").strip()

    @staticmethod
    def _kd_stock_number(location):
        """Kingdee warehouse (BD_STOCK) number of an Odoo location.

        The account mirrors a **warehouse** as an internal location carrying its
        Kingdee number (``sn_wsd_kingdee.models.stock_location``), while a document
        points at a sub location. The number is therefore read on the location
        itself and then on its parents.
        """
        depth = 0
        while location and depth < 12:
            number = (getattr(location, "kingdee_number", False) or "").strip()
            if number:
                return number
            location = location.location_id
            depth += 1
        return ""

    @staticmethod
    def _kd_lot_number(lot):
        """Kingdee batch number of a lot: its **name**.

        ``stock.lot.kingdee_number`` holds ``<material>|<batch>`` (a batch number is
        only unique per material), which is not what ``FLot`` expects.
        """
        return (lot.name or "").strip() if lot else ""

    def _kd_stock_status(self, lot=None):
        """Stock status of a line: available, waiting for a decision or frozen."""
        account = self._kd_account()
        if account:
            return account._stock_status_for(lot)
        return "KCZT01_SYS"

    def _kd_employee_number(self, employee=None, role="employee"):
        """Kingdee number of the employee who handled the document.

        The migration asks for the handler of the document, not a fixed value: the
        employee of the document wins, then the default of the account, and an empty
        value is only refused when the field is mandatory.
        """
        number = (getattr(employee, "kingdee_number", False) or "").strip() if employee else ""
        if number:
            return number
        account = self._kd_account()
        if not account:
            return ""
        if role == "stocker":
            return (account.default_stocker_number or "").strip()
        if role == "salesman":
            return (account.default_salesman_number or "").strip()
        return (account.default_employee_number or "").strip()

    def _kd_department_number(self, department=None):
        number = (getattr(department, "kingdee_number", False) or "").strip() if department else ""
        if number:
            return number
        account = self._kd_account()
        return (account.default_department_number or "").strip() if account else ""

    def _kd_sales_department_number(self, department=None):
        number = self._kd_department_number(department)
        if number:
            return number
        account = self._kd_account()
        return (account.default_sales_dept_number or "").strip() if account else ""

    @staticmethod
    def _kd_date(value):
        """Kingdee writes a date as ``YYYY-MM-DD``."""
        return value.strftime("%Y-%m-%d") if value else ""

    @staticmethod
    def _kd_datetime(value):
        return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""

    def _kd_note_text(self):
        """Text carrying the Odoo document in the Kingdee note field."""
        return "Odoo %s %s" % (self._name, self.name or self.id)

    def _kingdee_bill_qty_amount(self):
        """Quantity and amount a read-back is compared with."""
        return 0.0, 0.0

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def _kd_owner(self, account):
        """Owner of the goods: the organization itself, referenced by its number."""
        return self._kd_ref(self._kd_org("create"))

    def _kd_owner_type(self, account, keeper=False):
        """Owner or keeper type of the lines (the account chooses the wording)."""
        if not account:
            return "BD_KeeperOrg" if keeper else "BD_OwnerOrg"
        return account.keeper_type if keeper else account.owner_type

    def _kingdee_bill_parts(self, kind, map_row, account):
        """Fields of the document, keyed by Kingdee name (implemented per model)."""
        raise NotImplementedError("_kingdee_bill_parts() must be implemented")

    def _kingdee_payload(self, client):
        """``Save`` model of the document, for the shared save action."""
        return self._kingdee_bill_payload(client)

    def _kingdee_bill_payload(self, client=None):
        """``Save`` model of the document: header fields flat, entities nested."""
        self.ensure_one()
        kind = self._kingdee_bill_kind()
        map_row = self._kingdee_bill_map()
        account = self._kd_account()
        payload = dict(self._kingdee_bill_parts(kind, map_row, account) or {})
        self._kd_put(payload, "FBillNo", self._kingdee_number())
        note_field = (map_row.note_field or "").strip()
        if note_field:
            self._kd_put(payload, note_field, self._kd_note_text())
        for key, value in (map_row.fixed_values or {}).items():
            payload.setdefault(key, value)
        return payload

    def _kingdee_bill_required_settings(self):
        """Values this document kind cannot be accepted without (hook)."""
        return []

    def _kingdee_bill_check_ready(self):
        """Refuse a document that cannot be accepted, with an actionable message."""
        self.ensure_one()
        map_row = self._kingdee_bill_map()
        if not (map_row.bill_type_number or "").strip():
            raise UserError(_("The bill type of %s is not configured.") % map_row.name)
        if not (map_row.form_id or "").strip():
            raise UserError(_("The Kingdee object of %s is not configured.") % map_row.name)
        if not self._kd_org("create"):
            raise UserError(_(
                "Configure the organization of the Kingdee account before pushing a "
                "document."
            ))
        missing = [
            label for label, value in self._kingdee_bill_required_settings() if not value
        ]
        if missing:
            raise UserError(_(
                "%(document)s cannot be pushed to Kingdee, these values are missing: "
                "%(missing)s.",
            ) % {"document": self.display_name, "missing": ", ".join(missing)})
        quantity, _amount = self._kingdee_bill_qty_amount()
        if not quantity:
            raise UserError(_("%s has no quantity to push.") % self.display_name)
        return True

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------
    def action_kingdee_push(self):
        """Push the selected documents to Kingdee (button of a list or a form)."""
        if not self:
            return False
        summary = self._kingdee_push_records()
        return self._kingdee_push_notification(summary)

    def _kingdee_push_records(self):
        """Push every document of the recordset, isolating each one.

        Every document runs in its own savepoint: a refusal of the account must not
        roll back the state written for the others, and the sync log already keeps
        the failed call through its own cursor.
        """
        summary = {"success": 0, "failed": 0, "details": []}
        for record in self:
            try:
                with self.env.cr.savepoint():
                    record._kingdee_push_one()
            except Exception as err:  # noqa: BLE001 - reported, the run must go on
                message = str(err)
                _logger.warning("Kingdee push failed for %s: %s", record.display_name, message)
                summary["failed"] += 1
                if len(summary["details"]) < 8:
                    summary["details"].append(
                        _("%(name)s: %(message)s") % {
                            "name": record.display_name, "message": message})
                try:
                    with self.env.cr.savepoint():
                        record._kingdee_mark_push_failed(message)
                except Exception:  # noqa: BLE001
                    _logger.exception("Unable to flag the Kingdee error on %s",
                                      record.display_name)
            else:
                summary["success"] += 1
        return summary

    def _kingdee_push_one(self):
        """Save, submit, audit and verify one document."""
        self.ensure_one()
        map_row = self._kingdee_bill_map()
        self._kingdee_bill_check_ready()
        client = self.env[CLIENT_MODEL]
        number = self._kingdee_number()
        if not number:
            raise UserError(_("%s has no number to identify it in Kingdee.")
                            % self.display_name)
        model = self._kingdee_bill_payload(client)
        options = {}
        if self._kd_account() and self._kd_account().send_create_org_id:
            org = self._kd_org("create")
            if org.isdigit():
                options["CreateOrgId"] = int(org)
        for key, value in (map_row.save_options or {}).items():
            options[key] = value

        answer = client.save(map_row.form_id, model, res_record=self, **options)
        result = client.get_result(answer)
        status = (result.get("ResponseStatus") or {}) if isinstance(
            result.get("ResponseStatus"), dict) else {}
        kingdee_number = (result.get("Number") or result.get("FBillNo") or number or "").strip()
        master_id = result.get("Id") or result.get("FID")
        if not status.get("IsSuccess") or (not master_id and not kingdee_number):
            raise UserError(_(
                "Kingdee accepted the request of %(document)s without identifying the "
                "saved document (%(answer)s).",
            ) % {
                "document": self.display_name,
                "answer": status.get("Message") or status.get("Errors") or _("no status"),
            })

        state = "saved"
        message = _("Saved to Kingdee.")
        if map_row.auto_audit:
            state, message = self._kingdee_submit_audit(client, map_row, kingdee_number)

        qty, amount = self._kingdee_bill_qty_amount()
        values = {
            "kingdee_number": kingdee_number,
            "kingdee_master_id": str(master_id) if master_id else False,
            "kingdee_sync_state": state,
            "kingdee_pushed_at": fields.Datetime.now(),
            "kingdee_last_sync_at": fields.Datetime.now(),
            "kingdee_push_attempts": 0,
            "kingdee_next_retry_at": False,
            "kingdee_sync_message": message,
            "kingdee_pushed_qty": qty,
            "kingdee_pushed_amount": amount,
        }
        self.write(values)
        if map_row.verify_readback:
            self._kingdee_verify_readback(client, map_row, kingdee_number)
        self._kingdee_post_message(_("Pushed to Kingdee: %(number)s (%(state)s).") % {
            "number": kingdee_number, "state": state})
        return values

    def _kingdee_submit_audit(self, client, map_row, number):
        """Submit then audit the document, tolerating an already reached state."""
        state = "saved"
        for api_name, target in (("Submit", "submitted"), ("Audit", "audited")):
            try:
                client.bill_action(api_name, map_row.form_id, numbers=[number],
                                   res_record=self)
            except UserError as err:
                if not self._kingdee_is_benign_action_error(err):
                    raise
                _logger.info("Kingdee %s of %s: %s", api_name, number, err)
            state = target
        return state, _("Pushed to Kingdee and audited.")

    @staticmethod
    def _kingdee_is_benign_action_error(error):
        text = str(error)
        return any(token in text for token in BENIGN_ACTION_ERRORS)

    def _kingdee_verify_readback(self, client, map_row, number):
        """Read the document back and compare what the account really holds."""
        answer = client.view(map_row.form_id, number=number, res_record=self)
        data = client.get_response_data(answer)
        if not data:
            self.write({"kingdee_sync_message": _(
                "Saved, but the read-back returned nothing: check the document in "
                "Kingdee.")})
            return
        status = (data.get("FDocumentStatus") or "").strip()
        read_number = str(data.get("FBillNo") or data.get("FNumber") or "").strip()
        values = {
            "kingdee_verified_at": fields.Datetime.now(),
            "kingdee_sync_message": _("Read back from Kingdee: %(number)s, status "
                                      "%(status)s.") % {"number": read_number, "status": status},
        }
        if status == "C":
            values["kingdee_sync_state"] = "audited"
        qty, amount = self._kingdee_bill_qty_amount()
        if qty or amount:
            values["kingdee_pushed_qty"] = qty
            values["kingdee_pushed_amount"] = amount
        self.write(values)

    def _kingdee_mark_push_failed(self, error):
        """Record a failed push and schedule the next attempt."""
        self.ensure_one()
        attempts = (self.kingdee_push_attempts or 0) + 1
        delay = RETRY_DELAYS[min(attempts, len(RETRY_DELAYS)) - 1]
        self.write({
            "kingdee_sync_state": "error",
            "kingdee_last_sync_at": fields.Datetime.now(),
            "kingdee_sync_message": str(error),
            "kingdee_push_attempts": attempts,
            "kingdee_next_retry_at": fields.Datetime.now() + timedelta(minutes=delay),
        })
        self._kingdee_post_message(
            _("Push to Kingdee failed (attempt %(count)s): %(error)s") % {
                "count": attempts, "error": error}, error=True)

    def _kingdee_post_message(self, body, error=False):
        """Leave a trace on the document when it carries a chatter."""
        self.ensure_one()
        if not hasattr(self, "message_post"):
            return
        try:
            self.message_post(body=body, message_type="comment",
                              subtype_xmlid="mail.mt_note")
        except Exception:  # noqa: BLE001 - the trace must never fail the push
            _logger.debug("Unable to post the Kingdee message on %s", self.display_name)

    def _kingdee_push_notification(self, summary):
        details = "\n".join(summary["details"])
        if not summary["failed"]:
            return self._kingdee_notify(
                _("Kingdee"),
                _("%(count)s document(s) pushed to Kingdee.") % {"count": summary["success"]},
            )
        return self._kingdee_notify(
            _("Kingdee"),
            _("%(done)s pushed, %(failed)s failed.\n%(details)s") % {
                "done": summary["success"], "failed": summary["failed"], "details": details},
            kind="danger", sticky=True,
        )

    # ------------------------------------------------------------------
    # Automatic push
    # ------------------------------------------------------------------
    def _kingdee_defer_push(self):
        """Push after the current transaction is committed.

        A validated transfer must never be rolled back because the account is
        unavailable, and a rolled back transfer must never leave a document in the
        account: the push therefore runs in its own transaction, opened once this one
        commits.
        """
        records = self.filtered(lambda record: record.kingdee_sync_state in KINGDEE_PENDING_STATES)
        if not records:
            return False
        model_name = self._name
        ids = records.ids
        registry = self.env.registry

        def _run():
            try:
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env[model_name].browse(ids)._kingdee_push_records()
            except Exception:  # noqa: BLE001 - never break the caller
                _logger.exception("Deferred Kingdee push failed for %s %s",
                                  model_name, ids)

        self.env.cr.postcommit.add(_run)
        return True

    def _kingdee_auto_push(self):
        """Defer the push of the documents whose kind is configured to push."""
        records = self.browse()
        for record in self:
            try:
                map_row = record._kingdee_bill_map()
            except UserError:
                continue
            account = record._kd_account()
            if not map_row.auto_push:
                continue
            if account and not account.auto_push_bills:
                continue
            records |= record
        return records._kingdee_defer_push()

    def action_kingdee_check(self):
        """Report what a push would do, calling nothing (button of the form)."""
        self.ensure_one()
        try:
            self._kingdee_bill_check_ready()
        except UserError as err:
            return self._kingdee_notify(_("Kingdee"), str(err), kind="danger", sticky=True)
        map_row = self._kingdee_bill_map()
        return self._kingdee_notify(
            _("Kingdee"),
            _("%(document)s is ready for %(object)s (bill type %(type)s).") % {
                "document": self.display_name,
                "object": map_row.form_id,
                "type": map_row.bill_type_number,
            },
        )

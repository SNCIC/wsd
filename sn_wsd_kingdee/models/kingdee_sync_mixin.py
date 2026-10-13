# -*- coding: utf-8 -*-
"""Shared skeleton of the Odoo records synchronized with Kingdee.

A concrete model only declares **what** is sent (the Kingdee business object and
the field mapping); the state fields, the actions, the per record error
isolation, the notifications and the sync log binding come from here.

Hooks to implement on the concrete model:

``_kingdee_form_id``
    Kingdee business object identifier, e.g. ``"BD_MATERIAL"``.
``_kingdee_number()``
    Number (``FNumber``) identifying the record in Kingdee.
``_kingdee_payload(client)``
    ``Save`` payload: the field mapping, nested per Kingdee entity.
``_kingdee_apply_readback(data)``
    Optional; stores extra values returned by a read-back.

See ``docs/kingdee-接入SOP.md`` for the procedure that produces those two
methods.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CLIENT_MODEL = "sn.wsd.kingdee.client"
SYNC_LOG_MODEL = "sn.wsd.kingdee.sync.log"


class SnWsdKingdeeSyncMixin(models.AbstractModel):
    """Kingdee synchronization skeleton (state, actions, log, notifications)."""

    _name = "sn.wsd.kingdee.sync.mixin"
    _description = "Kingdee Synchronized Record"

    # Kingdee business object identifier; the concrete model sets it.
    _kingdee_form_id = None

    kingdee_number = fields.Char(
        string="Kingdee Number",
        copy=False,
        index=True,
        help="Number (FNumber) of this record in Kingdee. While it is empty the model "
             "derives one from the Odoo data: the internal reference for a product, "
             "the reference for a partner.",
    )
    kingdee_name = fields.Char(
        string="Kingdee Name",
        copy=False,
        readonly=True,
        help="Name (FName) as returned by Kingdee.",
    )
    kingdee_master_id = fields.Char(string="Kingdee Master ID", copy=False, readonly=True)
    kingdee_sync_state = fields.Selection(
        selection=[
            ("not_synced", "Not Synchronized"),
            ("saved", "Saved"),
            ("submitted", "Submitted"),
            ("audited", "Audited"),
            ("error", "Error"),
        ],
        string="Kingdee Status",
        default="not_synced",
        copy=False,
        readonly=True,
    )
    kingdee_last_sync_at = fields.Datetime(
        string="Kingdee Last Sync", copy=False, readonly=True,
    )
    kingdee_sync_message = fields.Text(
        string="Kingdee Message", copy=False, readonly=True,
    )
    kingdee_log_ids = fields.One2many(
        SYNC_LOG_MODEL,
        "res_id",
        string="Kingdee Logs",
        domain=lambda self: [("res_model", "=", self._name)],
        readonly=True,
    )

    _kingdee_number_unique = models.Constraint(
        "UNIQUE(kingdee_number)",
        "The Kingdee number must be unique.",
    )

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    def _kingdee_number(self):
        """Return the number (``FNumber``) identifying this record in Kingdee.

        ``kingdee_number`` wins; the concrete model decides what to derive from
        the Odoo data when it is empty.
        """
        self.ensure_one()
        return (self.kingdee_number or "").strip()

    def _kingdee_payload(self, client):
        """Return the ``Save`` payload (field mapping, nested per entity)."""
        raise NotImplementedError("_kingdee_payload() must be implemented")

    def _kingdee_apply_readback(self, data):
        """Store extra values returned by a read-back (optional hook)."""
        return None

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def _kingdee_mark_done(self, state, message, number=None, master_id=None, name=None):
        values = {
            "kingdee_sync_state": state,
            "kingdee_last_sync_at": fields.Datetime.now(),
            "kingdee_sync_message": message,
        }
        if number:
            values["kingdee_number"] = number
        if master_id:
            values["kingdee_master_id"] = str(master_id)
        if name:
            values["kingdee_name"] = name
        self.write(values)

    def _kingdee_mark_failed(self, error):
        self.write({
            "kingdee_sync_state": "error",
            "kingdee_last_sync_at": fields.Datetime.now(),
            "kingdee_sync_message": str(error),
        })

    @api.model
    def _kingdee_notify(self, title, message, kind="success", sticky=False):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": kind,
                "title": title,
                "message": message,
                "sticky": sticky,
            },
        }

    def _kingdee_notify_result(self, label, success, failures):
        if not failures:
            return self._kingdee_notify(
                _("Kingdee"),
                _("%(label)s: %(count)s record(s) processed.") % {"label": label, "count": success},
            )
        details = "\n".join(failures[:5])
        if len(failures) > 5:
            details += "\n..."
        return self._kingdee_notify(
            _("Kingdee"),
            _("%(label)s: %(done)s succeeded, %(failed)s failed.\n%(details)s") % {
                "label": label, "done": success, "failed": len(failures), "details": details,
            },
            kind="danger",
            sticky=True,
        )

    def _kingdee_run(self, label, worker):
        """Run ``worker(record)`` on every record of the recordset.

        Each record runs inside its own savepoint so that a rejection from
        Kingdee (or a constraint error) cannot poison the whole batch. Failures
        are reported through a notification instead of an exception: the
        ``kingdee_sync_state`` written for the other records must survive.
        """
        success, failures = 0, []
        for record in self:
            try:
                with self.env.cr.savepoint():
                    worker(record)
            except Exception as err:  # noqa: BLE001 - reported to the user, not raised
                message = str(err)
                _logger.warning(
                    "Kingdee %s failed for %s: %s", label, record.display_name, message,
                )
                failures.append(
                    _("%(name)s: %(message)s") % {"name": record.display_name, "message": message}
                )
                try:
                    with self.env.cr.savepoint():
                        record._kingdee_mark_failed(message)
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "Unable to flag the Kingdee error on %s", record.display_name,
                    )
            else:
                success += 1
        return self._kingdee_notify_result(label, success, failures)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _kingdee_prepare_save(self):
        """Return ``(number, model)`` ready for ``client.save()``.

        The payload is built by the concrete model through ``_kingdee_payload()``,
        the identification and the pre-flight checks are shared.
        """
        self.ensure_one()
        client = self.env[CLIENT_MODEL]
        if not client.get_default_org("create"):
            raise UserError(_(
                "Configure the default Kingdee organization in Settings (Kingdee) "
                "before synchronizing records."
            ))
        number = self._kingdee_number()
        if not number:
            raise UserError(_(
                "%s has no Kingdee number and none could be derived from its Odoo "
                "data, it cannot be identified in Kingdee."
            ) % self.display_name)
        return number, self._kingdee_payload(client)

    def action_kingdee_save(self):
        """Create or update the record in Kingdee."""
        client = self.env[CLIENT_MODEL]

        def worker(record):
            number, model = record._kingdee_prepare_save()
            payload = client.save(record._kingdee_form_id, model, res_record=record)
            result = client.get_result(payload)
            name = model.get("FName") if isinstance(model, dict) else None
            record._kingdee_mark_done(
                "saved", _("Saved to Kingdee."),
                number=number, master_id=result.get("Id"), name=name,
            )

        return self._kingdee_run(_("Save to Kingdee"), worker)

    def action_kingdee_submit(self):
        return self._kingdee_bill_action("Submit", "submitted", _("Submitted in Kingdee."))

    def action_kingdee_audit(self):
        return self._kingdee_bill_action("Audit", "audited", _("Audited in Kingdee."))

    def action_kingdee_unaudit(self):
        return self._kingdee_bill_action("UnAudit", "saved", _("Un-audited in Kingdee."))

    def _kingdee_bill_action(self, api_name, state, message):
        client = self.env[CLIENT_MODEL]

        def worker(record):
            number = record._kingdee_number()
            if not number:
                raise UserError(_("The record has no Kingdee number to identify it in Kingdee."))
            client.bill_action(api_name, record._kingdee_form_id, numbers=[number], res_record=record)
            record._kingdee_mark_done(state, message, number=number)

        return self._kingdee_run(_("Kingdee %s") % api_name, worker)

    def action_kingdee_pull(self):
        """Refresh the values stored on the record from Kingdee."""
        client = self.env[CLIENT_MODEL]

        def worker(record):
            number = record._kingdee_number()
            if not number:
                raise UserError(_("The record has no Kingdee number to identify it in Kingdee."))
            payload = client.view(record._kingdee_form_id, number=number, res_record=record)
            result = client.get_result(payload)
            inner = result.get("Result") if isinstance(result.get("Result"), dict) else {}
            data = client.get_response_data(payload)
            master_id = result.get("Id") or inner.get("Id")
            record._kingdee_mark_done(
                "saved", _("Refreshed from Kingdee."),
                number=(data.get("FNumber") or number),
                master_id=master_id,
                name=data.get("FName"),
            )
            record._kingdee_apply_readback(data)

        return self._kingdee_run(_("Refresh from Kingdee"), worker)

    def action_kingdee_delete(self):
        """Delete the record in Kingdee and forget the link here.

        Meant for the test data of an integration trial (see the SOP): the Odoo
        record keeps its values so it can still be inspected, only the Kingdee
        state is reset.
        """
        client = self.env[CLIENT_MODEL]

        def worker(record):
            number = record._kingdee_number()
            if not number:
                raise UserError(_("The record has no Kingdee number to identify it in Kingdee."))
            client.bill_action("Delete", record._kingdee_form_id, numbers=[number], res_record=record)
            record.write({
                "kingdee_sync_state": "not_synced",
                "kingdee_last_sync_at": fields.Datetime.now(),
                "kingdee_sync_message": _("Deleted in Kingdee."),
                "kingdee_master_id": False,
                "kingdee_name": False,
            })

        return self._kingdee_run(_("Delete in Kingdee"), worker)

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

# FDocumentStatus of a Kingdee record -> synchronization state. The five values of
# the account are Z (draft), A (created), B (under review), C (audited) and D
# (re-audited); anything but B and C is a record that simply exists in Kingdee.
KINGDEE_DOCUMENT_STATE = {
    "B": "submitted",
    "C": "audited",
}

# FForbidStatus of a record: A (enabled) or B (disabled).
KINGDEE_FORBIDDEN_STATUS = "B"

# States of a record that still has to be sent to Kingdee: one that was never saved
# there, and one whose last attempt failed.
KINGDEE_PENDING_STATES = ("not_synced", "error")


class SnWsdKingdeeSyncMixin(models.AbstractModel):
    """Kingdee synchronization skeleton (state, actions, log, notifications)."""

    _name = "sn.wsd.kingdee.sync.mixin"
    _description = "Kingdee Synchronized Record"

    # Kingdee business object identifier; the concrete model sets it.
    _kingdee_form_id = None

    # Inbound declaration. A model that can also be read from Kingdee sets these
    # two; the skeleton of ``_kingdee_import_records()`` needs nothing else.
    # FieldKeys of the query, in the BillQuery notation (``FCategoryID.FNumber``).
    _kingdee_query_fields = ()
    # Kingdee key -> Odoo field, for the values such a row carries.
    _kingdee_value_map = {}
    # Odoo field that identifies a record beside ``kingdee_number``: the internal
    # reference for a product, the reference for a partner.
    _kingdee_number_field = "default_code"

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

    def _kingdee_check_ready(self):
        """Refuse early when a value the account requires is not configured.

        Optional hook: raise a ``UserError`` with an actionable message instead of
        letting Kingdee answer with its own. An account may require fields the
        metadata does not mark as mandatory, so this is where that knowledge goes.
        """
        return None

    def _kingdee_import_extra_values(self, data):
        """Extra Odoo values a read row carries, on top of ``_kingdee_value_map``.

        Optional hook. ``self`` is the record being written, or an empty recordset
        when the record is new to Odoo, so a hook can tell the two apart.
        """
        return {}

    def _kingdee_sync_state(self, data):
        """Synchronization state matching the FDocumentStatus of a read record."""
        return KINGDEE_DOCUMENT_STATE.get(data.get("FDocumentStatus"), "saved")

    def _kingdee_is_forbidden(self, data):
        """Whether the record is disabled (FForbidStatus) in Kingdee."""
        return data.get("FForbidStatus") == KINGDEE_FORBIDDEN_STATUS

    def _kingdee_can_store(self, field_name, value):
        """Whether the account value can be stored on the Odoo field.

        Odoo raises on a value a Selection does not list and Kingdee is free to add
        a code, so an unknown one is reported and skipped instead of failing the
        whole record.
        """
        field = self._fields[field_name]
        if field.type != "selection":
            return True
        if value in dict(field.get_description(self.env)["selection"]):
            return True
        _logger.warning(
            "Kingdee sent %s=%r for %s, which is not one of its options: not stored.",
            field_name, value, self._name,
        )
        return False

    # ------------------------------------------------------------------
    # Inbound: reading the answer of Kingdee
    # ------------------------------------------------------------------
    @staticmethod
    def _kingdee_text(value):
        """Text of one value of a Kingdee answer.

        A ``View`` answer returns a translated field as a locale list
        (``[{"Key": 2052, "Value": "..."}]``) and a reference as a mapping, a query
        answer returns plain strings; the three shapes are normalised here so the
        callers only ever deal with text.
        """
        if value is None or value is False:
            return ""
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("Value") not in (None, ""):
                    return str(item["Value"]).strip()
            return ""
        if isinstance(value, dict):
            for key in ("Value", "FNumber", "Number"):
                if value.get(key) not in (None, ""):
                    return str(value[key]).strip()
            return ""
        return str(value).strip()

    @classmethod
    def _kingdee_mappings(cls, data):
        """Yield every mapping of a nested Kingdee answer, outermost first.

        ``View`` holds the values nested per entity (``SubHeadEntity``, ...), so a
        field has to be searched at any depth. Walking breadth first means the root
        wins, which is where the header fields are.
        """
        queue = [data] if isinstance(data, dict) else []
        while queue:
            node = queue.pop(0)
            yield node
            for value in node.values():
                if isinstance(value, dict):
                    queue.append(value)
                elif isinstance(value, list):
                    queue.extend(item for item in value if isinstance(item, dict))

    @classmethod
    def _kingdee_nested_value(cls, data, key):
        """Value of ``key`` in a ``View`` answer (values nested per entity).

        ``key`` uses the query notation: the first segment names the field, an
        optional second one the property to read on it (``FCategoryID.FNumber``).
        """
        field, _, prop = key.partition(".")
        for mapping in cls._kingdee_mappings(data):
            if field not in mapping:
                continue
            value = mapping[field]
            if not prop:
                return value
            if isinstance(value, dict):
                return value.get(prop)
        return None

    @classmethod
    def _kingdee_row_value(cls, row, key):
        """Value of ``key`` in a query row.

        ``BillQuery`` keys a row with the ``FieldKeys`` exactly as they were sent
        (``FCategoryID.FNumber``), and ``query_rows()`` gives the positional rows of
        ``ExecuteBillQuery`` the same shape. Nothing is ever guessed from the bare
        field name: an unexpected answer shape yields an empty value rather than the
        value of another field (``FNumber`` is also the last segment of the
        reference keys, so a bare name would be ambiguous).
        """
        return row.get(key)

    @classmethod
    def _kingdee_data_from_row(cls, row):
        """Normalise a query row to the ``_kingdee_query_fields`` key shape."""
        return {
            key: cls._kingdee_text(cls._kingdee_row_value(row, key))
            for key in cls._kingdee_query_fields
        }

    @classmethod
    def _kingdee_data_from_view(cls, data):
        """Normalise a ``View`` answer to the same key shape."""
        return {
            key: cls._kingdee_text(cls._kingdee_nested_value(data, key))
            for key in cls._kingdee_query_fields
        }

    @api.model
    def _kingdee_base_values(self, data):
        """Odoo values of the mapped fields a read row carries.

        The mapped fields are the ones the payload derives its values from, so a
        record imported here can be pushed back unchanged.
        """
        values = {}
        for key, field_name in self._kingdee_value_map.items():
            if field_name not in self._fields:
                # A field another module owns is written only when it is there, so
                # this integration also works on a bare database.
                continue
            value = data.get(key)
            if value and self._kingdee_can_store(field_name, value):
                values[field_name] = value
        return values

    def _kingdee_apply_readback(self, data):
        """Store what a ``View`` of this record answered.

        Called by ``action_kingdee_pull()``, which already stored the number, the
        name and the master id: this adds the field values and the real status, so
        "Refresh from Kingdee" refreshes the record itself and not only its
        synchronization state.
        """
        self.ensure_one()
        flat = self._kingdee_data_from_view(data)
        values = self._kingdee_base_values(flat)
        values.update(self._kingdee_import_extra_values(flat))
        values["kingdee_sync_state"] = self._kingdee_sync_state(flat)
        self.write(values)

    # ------------------------------------------------------------------
    # Inbound: import (Kingdee to Odoo)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_find_record(self, number):
        """Record already linked to the Kingdee record ``number``.

        The link is ``kingdee_number``. A record that only carries the number on its
        own reference field is adopted, which is how an existing catalogue gets
        linked. A record whose reference collides with a Kingdee number already used
        by another one is a conflict: importing it would create a second record, so
        it is refused instead.
        """
        record = self.search([("kingdee_number", "=", number)], limit=1)
        if record:
            return record
        record = self.search([(self._kingdee_number_field, "=", number)], limit=1)
        if not record or not record.kingdee_number:
            return record
        raise UserError(_(
            "The reference %(number)s is used by '%(record)s', which is already linked "
            "to the Kingdee number %(linked)s: importing %(number)s would create a "
            "second record."
        ) % {
            "number": number,
            "record": record.name,
            "linked": record.kingdee_number,
        })

    @api.model
    def _kingdee_import_row(self, row, update_existing=True, create_missing=True,
                            include_disabled=False, dry_run=False):
        """Create or update one record from a Kingdee row.

        Returns ``"created"``, ``"updated"`` or ``"skipped"`` (a record the caller
        asked not to touch). With ``dry_run`` the decision is returned and nothing is
        written, which is what a preview reports. The name of an existing record is
        left alone: it is pushed to Kingdee by the payload, so Odoo owns it, and the
        Kingdee name is kept on ``kingdee_name``.
        """
        data = self._kingdee_data_from_row(row)
        number = data.get("FNumber")
        if not number:
            raise UserError(_("Kingdee returned a record without a number."))
        forbidden = self._kingdee_is_forbidden(data)
        if forbidden and not include_disabled:
            return "skipped"
        record = self._kingdee_find_record(number)
        if record and not update_existing:
            return "skipped"
        if not record and not create_missing:
            return "skipped"
        if dry_run:
            # Nothing has been written before this point, so the decision alone is
            # the whole answer and no record has to be touched.
            return "updated" if record else "created"
        values = record._kingdee_base_values(data)
        values.update(record._kingdee_import_extra_values(data))
        values["kingdee_sync_state"] = self._kingdee_sync_state(data)
        values["kingdee_last_sync_at"] = fields.Datetime.now()
        values["kingdee_sync_message"] = (
            _("Imported from Kingdee, where the record is disabled.")
            if forbidden else _("Imported from Kingdee.")
        )
        name = data.get("FName")
        if name:
            values["kingdee_name"] = name
        if record:
            if not record.kingdee_number:
                # The record was adopted through its reference: record the link now,
                # otherwise nothing would ever tie the two together.
                values["kingdee_number"] = number
            record.write(values)
            return "updated"
        values["kingdee_number"] = number
        values["kingdee_name"] = name or number
        values[self._kingdee_number_field] = number
        values["name"] = name or number
        self.create(values)
        return "created"

    @api.model
    def _kingdee_import_records(self, filter_string="", limit=0, update_existing=True,
                                create_missing=True, include_disabled=False,
                                dry_run=False):
        """Read the Kingdee records and create or update the matching Odoo ones.

        Every record runs inside its own savepoint: a row Kingdee or Odoo refuses is
        reported and does not stop the run, the same isolation ``_kingdee_run()``
        gives to the outbound actions.

        :param str filter_string: Kingdee ``FilterString``, e.g. ``FDocumentStatus = 'C'``.
        :param int limit: highest number of records read (0 reads them all).
        :param bool dry_run: report what the run would do without writing anything.
            A preview classifies as if both write switches were on, so its counts
            describe a full import.
        :return dict: counters ``read`` / ``created`` / ``updated`` / ``skipped`` /
            ``failed``, and the first failures under ``errors``.
        """
        if dry_run:
            update_existing = create_missing = True
        client = self.env[CLIENT_MODEL]
        summary = {"read": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0,
                   "errors": []}
        for row in client.iter_bill_query(
            self._kingdee_form_id,
            ",".join(self._kingdee_query_fields),
            filter_string=(filter_string or "").strip(),
            order_string="FNumber",
        ):
            if limit and summary["read"] >= limit:
                break
            summary["read"] += 1
            number = self._kingdee_text(self._kingdee_row_value(row, "FNumber"))
            try:
                with self.env.cr.savepoint():
                    outcome = self._kingdee_import_row(
                        row,
                        update_existing=update_existing,
                        create_missing=create_missing,
                        include_disabled=include_disabled,
                        dry_run=dry_run,
                    )
            except Exception as err:  # noqa: BLE001 - reported, the run must go on
                summary["failed"] += 1
                _logger.warning(
                    "Kingdee import failed for %s %s: %s", self._name, number or "?", err,
                )
                if len(summary["errors"]) < 5:
                    summary["errors"].append(_("%(number)s: %(message)s") % {
                        "number": number or "?", "message": err,
                    })
                continue
            summary[outcome] += 1
        return summary

    @api.model
    def _kingdee_import_notification(self, summary, dry_run=False):
        """Notification reporting the outcome of an import or of a preview run."""
        # ``_description`` is the English class attribute: the translated model name
        # is the one on ir.model.
        model = self.env["ir.model"]._get(self._name)
        counts = {
            "entity": model.name if model else self._description,
            "created": summary["created"],
            "updated": summary["updated"],
            "skipped": summary["skipped"],
        }
        if dry_run:
            done = _("Preview %(entity)s: %(created)s to create, %(updated)s to update, "
                     "%(skipped)s skipped.")
            failed = _("Preview %(entity)s: %(created)s to create, %(updated)s to update, "
                       "%(skipped)s skipped, %(failed)s failed.\n%(details)s")
        else:
            done = _("Import %(entity)s from Kingdee: %(created)s created, %(updated)s "
                     "updated, %(skipped)s skipped.")
            failed = _("Import %(entity)s from Kingdee: %(created)s created, %(updated)s "
                       "updated, %(skipped)s skipped, %(failed)s failed.\n%(details)s")
        if not summary["failed"]:
            return self._kingdee_notify(_("Kingdee"), done % counts)
        details = "\n".join(summary["errors"])
        return self._kingdee_notify(
            _("Kingdee"),
            failed % dict(counts, failed=summary["failed"], details=details),
            kind="danger",
            sticky=True,
        )

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
        self._kingdee_check_ready()
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

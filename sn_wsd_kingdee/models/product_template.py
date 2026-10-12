# -*- coding: utf-8 -*-

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Kingdee business object used for materials (basic data).
MATERIAL_FORM_ID = "BD_MATERIAL"

# Number of already linked materials refreshed by the scheduled job.
CRON_BATCH_SIZE = 50


class ProductTemplate(models.Model):
    _inherit = "product.template"

    kingdee_number = fields.Char(
        string="Kingdee Number",
        copy=False,
        index=True,
        help="Material number (FNumber) in Kingdee. The internal reference is used when empty.",
    )
    kingdee_name = fields.Char(
        string="Kingdee Name", copy=False, readonly=True,
        help="Material name (FName) as returned by Kingdee.",
    )
    kingdee_material_group = fields.Char(
        string="Kingdee Material Group", copy=False,
        help="Optional material group number (FMaterialGroup) applied when saving to Kingdee.",
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
        "sn.wsd.kingdee.sync.log",
        "res_id",
        string="Kingdee Logs",
        domain=[("res_model", "=", "product.template")],
        readonly=True,
    )

    _kingdee_number_unique = models.Constraint(
        "UNIQUE(kingdee_number)",
        "The Kingdee number must be unique across products.",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _kingdee_material_number(self):
        self.ensure_one()
        return (self.kingdee_number or self.default_code or "").strip()

    def _kingdee_prepare_save(self):
        """Return the material number and the Kingdee ``Model`` mapping to save."""
        self.ensure_one()
        client = self.env["sn.wsd.kingdee.client"]
        create_org = client.get_default_org("create")
        if not create_org:
            raise UserError(_(
                "Configure the default Kingdee organization in Settings "
                "(Kingdee > Material Defaults) before synchronizing materials."
            ))
        number = self._kingdee_material_number()
        if not number:
            raise UserError(_(
                "Product %s has neither an internal reference nor a Kingdee number, "
                "it cannot be identified in Kingdee."
            ) % self.display_name)
        model = {
            "FCreateOrgId": {"FNumber": create_org},
            "FUserOrgId": {"FNumber": client.get_default_org("use")},
            "FNumber": number,
            "FName": (self.name or "").strip() or number,
        }
        if self.kingdee_material_group:
            model["FMaterialGroup"] = {"FNumber": self.kingdee_material_group}
        return number, model

    def _kingdee_mark_done(self, state, message, number=None, master_id=None, name=None):
        vals = {
            "kingdee_sync_state": state,
            "kingdee_last_sync_at": fields.Datetime.now(),
            "kingdee_sync_message": message,
        }
        if number:
            vals["kingdee_number"] = number
        if master_id:
            vals["kingdee_master_id"] = str(master_id)
        if name:
            vals["kingdee_name"] = name
        self.write(vals)

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
        """Run ``worker(product)`` on every record.

        Each record runs inside its own savepoint so that a rejection from
        Kingdee (or a constraint error) cannot poison the whole batch. Failures
        are reported through a notification instead of an exception: the
        ``kingdee_sync_state`` written for the other records must survive.
        """
        success, failures = 0, []
        for product in self:
            try:
                with self.env.cr.savepoint():
                    worker(product)
            except Exception as err:  # noqa: BLE001 - reported to the user, not raised
                message = str(err)
                _logger.warning(
                    "Kingdee %s failed for %s: %s", label, product.display_name, message,
                )
                failures.append(
                    _("%(name)s: %(message)s") % {"name": product.display_name, "message": message}
                )
                try:
                    with self.env.cr.savepoint():
                        product._kingdee_mark_failed(message)
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "Unable to flag the Kingdee error on %s", product.display_name,
                    )
            else:
                success += 1
        return self._kingdee_notify_result(label, success, failures)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_kingdee_save(self):
        """Create or update the material in Kingdee."""
        client = self.env["sn.wsd.kingdee.client"]

        def worker(product):
            number, model = product._kingdee_prepare_save()
            payload = client.save(MATERIAL_FORM_ID, model, res_record=product)
            result = client.get_result(payload)
            product._kingdee_mark_done(
                "saved",
                _("Material saved to Kingdee."),
                number=number,
                master_id=result.get("Id"),
                name=(product.name or "").strip(),
            )

        return self._kingdee_run(_("Save to Kingdee"), worker)

    def action_kingdee_submit(self):
        return self._kingdee_bill_action("Submit", "submitted", _("Material submitted in Kingdee."))

    def action_kingdee_audit(self):
        return self._kingdee_bill_action("Audit", "audited", _("Material audited in Kingdee."))

    def action_kingdee_unaudit(self):
        return self._kingdee_bill_action("UnAudit", "saved", _("Material un-audited in Kingdee."))

    def _kingdee_bill_action(self, api_name, state, message):
        client = self.env["sn.wsd.kingdee.client"]

        def worker(product):
            number = product._kingdee_material_number()
            if not number:
                raise UserError(_("The product has no material number to identify it in Kingdee."))
            client.bill_action(api_name, MATERIAL_FORM_ID, numbers=[number], res_record=product)
            product._kingdee_mark_done(state, message, number=number)

        return self._kingdee_run(_("Kingdee %s") % api_name, worker)

    def action_kingdee_pull(self):
        """Refresh the material data stored on the product from Kingdee."""
        client = self.env["sn.wsd.kingdee.client"]

        def worker(product):
            number = product._kingdee_material_number()
            if not number:
                raise UserError(_("The product has no material number to identify it in Kingdee."))
            payload = client.view(MATERIAL_FORM_ID, number=number, res_record=product)
            result = client.get_result(payload)
            inner = result.get("Result") if isinstance(result.get("Result"), dict) else {}
            data = client.get_response_data(payload)
            master_id = result.get("Id") or inner.get("Id")
            product._kingdee_mark_done(
                "saved",
                _("Material refreshed from Kingdee."),
                number=(data.get("FNumber") or number),
                master_id=master_id,
                name=data.get("FName"),
            )

        return self._kingdee_run(_("Refresh from Kingdee"), worker)

    # ------------------------------------------------------------------
    # Scheduled job
    # ------------------------------------------------------------------
    @api.model
    def _cron_kingdee_pull_materials(self):
        """Refresh the materials already linked to Kingdee, oldest sync first."""
        client = self.env["sn.wsd.kingdee.client"]
        if not client.is_enabled():
            _logger.info("Kingdee material refresh skipped: the integration is disabled.")
            return False
        products = self.search(
            [("kingdee_number", "!=", False)],
            limit=CRON_BATCH_SIZE,
            order="kingdee_last_sync_at asc, id asc",
        )
        if not products:
            _logger.info("Kingdee material refresh skipped: no linked material found.")
            return False
        products.action_kingdee_pull()
        return True

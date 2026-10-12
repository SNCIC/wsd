# -*- coding: utf-8 -*-

from odoo import _, api, fields, models


class SnWsdKingdeeSyncLog(models.Model):
    _name = "sn.wsd.kingdee.sync.log"
    _description = "Kingdee Sync Log"
    _rec_name = "api_name"
    _order = "id desc"

    api_name = fields.Char(string="API", required=True, readonly=True)
    form_id = fields.Char(string="Form ID", readonly=True, help="Kingdee business object identifier, e.g. BD_MATERIAL.")
    direction = fields.Selection(
        selection=[("out", "Odoo to Kingdee"), ("in", "Kingdee to Odoo")],
        string="Direction",
        required=True,
        default="out",
        readonly=True,
    )
    state = fields.Selection(
        selection=[("success", "Success"), ("error", "Error")],
        string="Status",
        required=True,
        default="success",
        readonly=True,
    )
    error_message = fields.Text(string="Error", readonly=True)
    request_payload = fields.Text(string="Request", readonly=True)
    response_payload = fields.Text(string="Response", readonly=True)
    duration_ms = fields.Integer(string="Duration (ms)", readonly=True)

    res_model = fields.Char(string="Related Model", index=True, readonly=True)
    res_id = fields.Many2oneReference(
        string="Related Record", index=True, model_field="res_model", readonly=True,
    )
    res_name = fields.Char(
        string="Related Record Name", compute="_compute_res_name", readonly=True,
    )

    user_id = fields.Many2one("res.users", string="User", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    @api.depends("res_model", "res_id")
    def _compute_res_name(self):
        for log in self:
            log.res_name = ""
            if not log.res_model or not log.res_id:
                continue
            try:
                related = log.env[log.res_model].sudo().browse(log.res_id).exists()
                log.res_name = related.display_name if related else ""
            except Exception:  # noqa: BLE001 - an unknown/abstract model must not break the log list
                continue

    def action_open_related_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.res_name or self.res_model,
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "target": "current",
        }

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    purchase_request_default_approver_id = fields.Many2one(
        related="company_id.purchase_request_default_approver_id",
        string="Default Purchase Request Approver",
        readonly=False,
        domain=lambda self: [
            (
                "group_ids",
                "in",
                self.env.ref("purchase_request.group_purchase_request_manager").id,
            )
        ],
    )

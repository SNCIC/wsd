from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    purchase_request_default_approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Default Purchase Request Approver",
        domain=lambda self: [
            (
                "group_ids",
                "in",
                self.env.ref("purchase_request.group_purchase_request_manager").id,
            )
        ],
        help="Default approver automatically assigned to new purchase requests.",
    )

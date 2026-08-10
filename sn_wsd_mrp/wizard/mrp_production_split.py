from odoo import api, fields, models, Command


class MrpProductionSplit(models.TransientModel):
    _inherit = 'mrp.production.split'

    @api.depends(
        'num_splits',
        'production_id.x_workshop_id',
        'production_id.x_production_line_id',
        'production_id.date_deadline',
    )
    def _compute_details(self):
        super()._compute_details()
        for wizard in self:
            production = wizard.production_id
            for detail in wizard.production_detailed_vals_ids:
                detail.x_workshop_id = production.x_workshop_id
                detail.x_production_line_id = production.x_production_line_id
                detail.date_deadline = production.date_deadline

    def action_split(self):
        productions = self.production_id._split_productions({
            self.production_id: [detail.quantity for detail in self.production_detailed_vals_ids],
        })
        for production, detail in zip(productions, self.production_detailed_vals_ids):
            production_line = detail.x_production_line_id
            workshop = detail.x_workshop_id or production_line.workshop_id
            production.write({
                'user_id': detail.user_id.id,
                'date_start': detail.date,
                'date_deadline': detail.date_deadline,
                'x_workshop_id': workshop.id,
                'x_production_line_id': production_line.id,
            })
        if self.production_split_multi_id:
            saved_production_split_multi_id = self.production_split_multi_id.id
            self.production_split_multi_id.production_ids = [Command.unlink(self.id)]
            action = self.env['ir.actions.actions']._for_xml_id('mrp.action_mrp_production_split_multi')
            action['res_id'] = saved_production_split_multi_id
            return action


class MrpProductionSplitLine(models.TransientModel):
    _inherit = 'mrp.production.split.line'

    company_id = fields.Many2one(
        related='mrp_production_split_id.production_id.company_id',
    )
    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        check_company=True,
    )
    x_production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='Production Line',
        check_company=True,
    )
    date_deadline = fields.Datetime(string='Expected Completion Date')

    @api.onchange('x_workshop_id')
    def _onchange_x_workshop_id(self):
        for detail in self:
            if (
                detail.x_workshop_id
                and detail.x_production_line_id
                and detail.x_production_line_id.workshop_id != detail.x_workshop_id
            ):
                detail.x_production_line_id = False

    @api.onchange('x_production_line_id')
    def _onchange_x_production_line_id(self):
        for detail in self:
            if detail.x_production_line_id:
                detail.x_workshop_id = detail.x_production_line_id.workshop_id

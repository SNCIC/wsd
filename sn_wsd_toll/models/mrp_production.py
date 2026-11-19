from odoo import api, fields, models


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    sn_toll_order_id = fields.Many2one(
        'sn.toll.order', string='Toll Manufacturing Order', copy=False,
        index=True, check_company=True,
    )
    sn_toll_partner_id = fields.Many2one(
        'res.partner', string='Toll Goods Owner', copy=False, index=True,
        check_company=True,
        help='Customer owning the material consumed and the finished goods '
             'produced by this manufacturing order.',
    )
    sn_is_toll = fields.Boolean(
        string='Toll Manufacturing', compute='_compute_sn_is_toll',
        store=True, index=True,
    )

    @api.depends('sn_toll_order_id', 'sn_toll_partner_id')
    def _compute_sn_is_toll(self):
        for production in self:
            production.sn_is_toll = bool(
                production.sn_toll_order_id or production.sn_toll_partner_id)

    @api.onchange('sn_toll_order_id')
    def _onchange_sn_toll_order_id(self):
        if self.sn_toll_order_id:
            self.sn_toll_partner_id = self.sn_toll_order_id.partner_id

    def pre_button_mark_done(self):
        # A toll manufacturing order settles an over-consumption with the
        # customer instead of blocking the completion: the loss is measured
        # against the theoretical consumption and invoiced or replaced
        # afterwards.
        if self.sn_is_toll:
            return super(
                MrpProduction, self.with_context(skip_consumption=True)
            ).pre_button_mark_done()
        return super().pre_button_mark_done()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('sn_toll_order_id') and not vals.get(
                    'sn_toll_partner_id'):
                order = self.env['sn.toll.order'].browse(
                    vals['sn_toll_order_id'])
                vals['sn_toll_partner_id'] = order.partner_id.id
            elif not vals.get('sn_toll_partner_id') and vals.get(
                    'sale_line_id'):
                # A manufacturing order launched from a toll sale order must
                # reserve the customer goods from the start: the owner is
                # written here, before the confirmation assigns the quants.
                line = self.env['sale.order.line'].browse(vals['sale_line_id'])
                if line.order_id.sn_is_toll:
                    vals['sn_toll_partner_id'] = line.order_id.partner_id.id
        return super().create(vals_list)

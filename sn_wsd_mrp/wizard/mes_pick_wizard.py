from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MesPickWizard(models.TransientModel):
    """Material picking dialog (领料弹窗), two modes:

    - normal pick: how many finished units to issue with this batch
      (架构设计 3.3 ``qty_this``); batches accumulate up to the order
      quantity.
    - supplement (补料, 2026-09-12 挑料口径取代按台数超领): pick the few
      BoM components actually needed, one quantity each, reason required.
      Off-the-books: never touches the net picked quantity or the plan cap.
    """
    _name = 'sn.wsd.mes.pick.wizard'
    _description = 'MES Material Picking Wizard'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True,
    )
    name = fields.Char(related='mes_order_id.name')
    production_id = fields.Many2one(
        'mrp.production', related='mes_order_id.production_id',
    )
    planned_qty = fields.Float(related='mes_order_id.planned_qty')
    picked_qty = fields.Float(related='mes_order_id.picked_qty')
    remaining_qty = fields.Float(
        string='Remaining Quantity', compute='_compute_remaining_qty',
    )
    mode = fields.Selection(
        [('normal', 'Normal Pick'), ('supplement', 'Supplement')],
        string='Mode', required=True, default='normal',
    )
    qty_this = fields.Float(string='Quantity To Pick')
    over_reason = fields.Text(
        string='Supplement Reason',
        help='Why is material needed (consumption make-up, shortage, ...)? '
             'Stored on the supplement picking.',
    )
    supplement_line_ids = fields.One2many(
        'sn.wsd.mes.pick.wizard.line', 'wizard_id', string='Supplement Lines',
    )
    bom_product_ids = fields.Many2many(
        'product.product', compute='_compute_bom_products',
        help='Components offered for supplements: the BoM lines of this '
             "order's side.",
    )

    @api.depends('mes_order_id')
    def _compute_remaining_qty(self):
        for wizard in self:
            wizard.remaining_qty = (
                wizard.mes_order_id.planned_qty - wizard.mes_order_id.picked_qty)

    @api.depends('mes_order_id')
    def _compute_bom_products(self):
        for wizard in self:
            bom = wizard.mes_order_id.production_id.bom_id
            lines = bom.bom_line_ids if bom else False
            if lines and wizard.mes_order_id.x_side:
                lines = lines.filtered(
                    lambda l: l.x_board_side == wizard.mes_order_id.x_side)
            wizard.bom_product_ids = lines.mapped('product_id') if lines else False

    @api.onchange('mes_order_id')
    def _onchange_mes_order_id(self):
        if self.mes_order_id:
            self.qty_this = (
                self.mes_order_id.planned_qty - self.mes_order_id.picked_qty)

    def action_pick(self):
        self.ensure_one()
        order = self.mes_order_id
        if order.state not in ('released', 'picked', 'in_progress'):
            raise UserError(_(
                'Only active MES orders (released, picked or in progress) '
                'can pick material (current: %s).', order.state))
        if self.mode == 'supplement':
            # 挑料补料（账外）：只发勾选的料×数量，原因必填
            if not (self.over_reason or '').strip():
                raise ValidationError(_('A supplement reason is required.'))
            if not self.supplement_line_ids:
                raise ValidationError(
                    _('Select at least one component to supplement.'))
            order.action_generate_over_picking(
                [{'product_id': line.product_id.id, 'qty': line.qty}
                 for line in self.supplement_line_ids],
                self.over_reason)
            return {'type': 'ir.actions.act_window_close'}
        if self.qty_this <= 0 or self.qty_this != int(self.qty_this):
            raise ValidationError(
                _('The picked quantity must be a positive whole number of units.'))
        if order.planned_qty - order.picked_qty <= 0.0001:
            raise UserError(_(
                'Nothing left to pick on MES order %(order)s.', order=order.name))
        if self.qty_this + order.picked_qty > order.planned_qty + 0.0001:
            raise ValidationError(_(
                'Over-picking: only %(remaining)s unit(s) remain on %(order)s.',
                remaining=order.planned_qty - order.picked_qty, order=order.name))
        order.action_generate_picking(qty_this=self.qty_this)
        return {'type': 'ir.actions.act_window_close'}


class MesPickWizardLine(models.TransientModel):
    _name = 'sn.wsd.mes.pick.wizard.line'
    _description = 'MES Supplement Wizard Line'

    wizard_id = fields.Many2one(
        'sn.wsd.mes.pick.wizard', required=True, ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product', string='Component', required=True,
        domain="[('id', 'in', parent.bom_product_ids)]",
        check_company=False,
    )
    product_uom_id = fields.Many2one(related='product_id.uom_id')
    # 默认 1：挑料组件加行时会保存父向导（multi_add 语义），默认 0 会被
    # “数量必须为正”约束当场拦下，导致加行报错、弹窗卡住
    qty = fields.Float(string='Quantity', required=True, default=1)

    @api.constrains('qty')
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(
                    _('Every supplement quantity must be positive.'))

from odoo import _, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    can_print_material_labels = fields.Boolean(
        string='Can Print Material Labels',
        compute='_compute_can_print_material_labels',
    )

    def _compute_can_print_material_labels(self):
        for picking in self:
            picking.can_print_material_labels = (
                picking.picking_type_code == 'incoming'
                and picking.state not in ('done', 'cancel')
                and any(
                    move.product_id and move.product_id.tracking == 'lot'
                    for move in picking.move_ids
                )
            )

    def action_open_material_label_wizard(self):
        self.ensure_one()
        if not self.can_print_material_labels:
            raise UserError(_('Material labels can only be printed for active receipts.'))
        view = self.env.ref(
            'sn_wsd_stock.view_incoming_material_label_wizard_form'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate and Print Material Labels'),
            'res_model': 'sn.wsd.incoming.material.label.wizard',
            'view_mode': 'form',
            'view_id': view.id,
            'target': 'new',
            'context': {'default_picking_id': self.id},
        }


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    supplier_batch_no = fields.Char(string='Supplier Batch', copy=False, index=True)
    material_sn_base = fields.Char(
        string='Material SN Base', copy=False, readonly=True, index=True,
    )
    material_sn_suffix = fields.Char(
        string='Material SN Suffix', copy=False, readonly=True,
    )
    material_label_printed = fields.Boolean(
        string='Material Label Printed', copy=False, readonly=True,
    )


class StockLot(models.Model):
    _inherit = 'stock.lot'

    material_sn_base = fields.Char(
        string='Material SN Base', copy=False, index=True, readonly=True,
    )
    material_sn_suffix = fields.Char(
        string='Material SN Suffix', copy=False, readonly=True,
    )
    supplier_code = fields.Char(string='Supplier Code', copy=False, readonly=True)
    supplier_name = fields.Char(string='Supplier Name', copy=False, readonly=True)
    supplier_batch_no = fields.Char(
        string='Supplier Batch', copy=False, readonly=True,
    )
    initial_quantity = fields.Float(
        string='Initial Quantity', copy=False, readonly=True, digits='Product Unit',
    )
    source_picking_id = fields.Many2one(
        'stock.picking', string='Source Receipt', copy=False, readonly=True,
        index=True, check_company=True,
    )
    source_move_line_id = fields.Many2one(
        'stock.move.line', string='Source Operation Line', copy=False,
        readonly=True, index=True, check_company=True,
    )
    label_print_count = fields.Integer(
        string='Label Print Count', default=0, copy=False, readonly=True,
    )

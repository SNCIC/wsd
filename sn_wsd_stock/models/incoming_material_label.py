from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    can_print_material_labels = fields.Boolean(
        string='Can Print Material Labels',
        compute='_compute_can_print_material_labels',
    )

    def _compute_can_print_material_labels(self):
        for picking in self:
            has_tracked = any(
                move.product_id and move.product_id.tracking == 'lot'
                for move in picking.move_ids
            )
            if picking.picking_type_id.sequence_code == 'sn.wsd.mes.picking.receipt':
                # 完工收货（finished-goods-material-sn）：含已完成单（补打）
                picking.can_print_material_labels = (
                    picking.state != 'cancel' and has_tracked)
            else:
                picking.can_print_material_labels = (
                    picking.picking_type_code == 'incoming'
                    and picking.state not in ('done', 'cancel')
                    and has_tracked)

    def action_open_material_label_wizard(self):
        self.ensure_one()
        if self.picking_type_id.sequence_code == 'sn.wsd.mes.picking.receipt':
            # 完工收货：一键生成/重打批级物料SN（无向导输入项）
            return self.action_print_finished_material_labels()
        if not self.can_print_material_labels:
            raise UserError(_('Material labels can only be printed for active receipts.'))
        context = dict(self.env.context)
        lot_id = context.get('active_lot_id')
        lot = self.env['stock.lot'].browse(lot_id).exists() if lot_id else self.env['stock.lot']
        if lot:
            if (
                lot.product_id.tracking != 'lot'
                or lot.source_picking_id != self
                or lot.company_id != self.company_id
            ):
                raise UserError(_('The selected material lot does not belong to this receipt.'))
            action = self.env.ref(
                'sn_wsd_stock.action_report_incoming_material_label_zpl'
            ).report_action(lot, config=False)
            action['close_on_report_download'] = True
            return action
        view = self.env.ref(
            'sn_wsd_stock.view_incoming_material_label_wizard_form'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate and Print Material Labels'),
            'res_model': 'sn.wsd.incoming.material.label.wizard',
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'default_move_line_id': context.get('active_move_line_id'),
            },
        }

    def button_validate(self):
        for picking in self:
            if picking.picking_type_code != 'incoming':
                continue
            unlabelled_lines = picking.move_line_ids.filtered(
                lambda line: (
                    line.product_id.tracking in ('lot', 'serial')
                    and line.quantity > 0
                    and not line.lot_id
                )
            )
            if unlabelled_lines:
                raise UserError(
                    _(
                        'Generate material labels before validating tracked '
                        'products: %(products)s',
                        products=', '.join(
                            unlabelled_lines.mapped('product_id.display_name')
                        ),
                    )
                )
        return super().button_validate()


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

    def _sync_material_lot_quantity(self):
        for line in self.filtered(
            lambda item: item.lot_id
            and item.lot_id.material_sn_base
            and item.product_id.tracking == 'lot'
        ):
            lot = line.lot_id
            quantity = line.product_uom_id._compute_quantity(
                line.quantity, line.product_id.uom_id,
            )
            lot_vals = {'initial_quantity': quantity}
            parts = (lot.name or '').split('$')
            if len(parts) >= 5 and parts[3].isdigit():
                parts[3] = str(int(quantity))
                new_name = '$'.join(parts)
                duplicate = self.env['stock.lot'].search([
                    ('id', '!=', lot.id),
                    ('name', '=', new_name),
                    ('product_id', '=', lot.product_id.id),
                    '|',
                    ('company_id', '=', False),
                    ('company_id', '=', lot.company_id.id),
                ], limit=1)
                if duplicate:
                    raise ValidationError(
                        _('The material SN already exists: %s', new_name)
                    )
                lot_vals.update({
                    'name': new_name,
                    'material_sn_base': new_name,
                })
            lot.write(lot_vals)
            line.write({
                'lot_name': lot.name,
                'material_sn_base': lot.material_sn_base,
            })

    def write(self, vals):
        result = super().write(vals)
        if 'quantity' in vals or 'qty_done' in vals:
            self._sync_material_lot_quantity()
        return result


class StockLot(models.Model):
    _inherit = 'stock.lot'

    arrival_batch_no = fields.Char(
        string='Arrival Batch',
        copy=False,
        readonly=True,
        index=True,
    )
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


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    supplier_batch_no = fields.Char(
        related='lot_id.supplier_batch_no',
        string='Supplier Batch',
        readonly=True,
    )
    arrival_batch_no = fields.Char(
        related='lot_id.arrival_batch_no',
        string='Arrival Batch',
        readonly=True,
    )

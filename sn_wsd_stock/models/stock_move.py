from collections import defaultdict

from odoo import api, fields, models


class StockMove(models.Model):
    """Columns of the reception detail reports.

    A purchase reception goes through up to three operations whose types the
    warehouse reception steps create: the receipt itself, the quality control
    and the storage transfer. The reception reports list one line per move of
    those operations; the document information the lines repeat is carried by
    related fields so that the list can print it once per document (see the
    merged cells list of ``sn_wsd_list``).
    """

    _inherit = 'stock.move'

    sn_reception_step = fields.Selection(
        selection=[
            ('receipt', 'Receipt'),
            ('qc', 'Quality Control'),
            ('storage', 'Storage'),
        ],
        string='Reception Step',
        compute='_compute_sn_reception_step',
        store=True,
        index=True,
        help='Step of the reception this operation belongs to, following the '
             'operation types of the warehouse reception. With a one-step '
             'reception the receipt is also the storage operation, so it '
             'shows up in both reports.',
    )
    sn_picking_date = fields.Datetime(
        related='picking_id.scheduled_date',
        string='Scheduled Date',
        readonly=True,
        store=True,
    )
    sn_validation_date = fields.Datetime(
        related='picking_id.date_done',
        string='Validation Date',
        readonly=True,
        store=True,
        help='Date the operation of the document was validated. Empty while '
             'the document is still open.',
    )
    sn_picking_partner_id = fields.Many2one(
        related='picking_id.partner_id',
        string='Vendor',
        readonly=True,
        store=True,
    )
    sn_picking_origin = fields.Char(
        related='picking_id.origin',
        string='Transfer Source',
        readonly=True,
        store=True,
    )
    sn_picking_state = fields.Selection(
        related='picking_id.state',
        string='Transfer Status',
        readonly=True,
        store=True,
    )
    sn_picking_user_id = fields.Many2one(
        related='picking_id.user_id',
        string='Responsible',
        readonly=True,
        store=True,
    )
    product_code = fields.Char(
        related='product_id.default_code',
        string='Material Code',
        readonly=True,
    )
    product_name = fields.Char(
        related='product_id.name',
        string='Material Name',
        readonly=True,
    )
    sn_lot_names = fields.Char(
        string='Batches',
        compute='_compute_sn_batch_names',
        help='Batches the operation lines of this move carry.',
    )
    sn_supplier_batch_no = fields.Char(
        string='Supplier Batch',
        compute='_compute_sn_batch_names',
        help='Supplier batches read on the operation lines of this move.',
    )

    @api.depends('picking_type_id', 'picking_type_id.warehouse_id.reception_steps')
    def _compute_sn_reception_step(self):
        for move in self:
            move.sn_reception_step = move._get_sn_reception_step()

    def _get_sn_reception_step(self):
        """Reception step the move belongs to.

        The quality control and storage operation types only exist once the
        warehouse reception is set to three or two steps, so their activity is
        what tells the steps apart. The quality control step has no operation
        on a one- or two-step reception, and the receipt of a one-step
        reception already reaches the stock: the receipt report lists it and
        the storage report adds it through the one-step fallback of its
        action.
        """
        self.ensure_one()
        picking_type = self.picking_type_id
        warehouse = picking_type.warehouse_id
        if not warehouse:
            return False
        qc_type = warehouse.qc_type_id
        if qc_type and qc_type.active and picking_type == qc_type:
            return 'qc'
        store_type = warehouse.store_type_id
        if store_type and store_type.active and picking_type == store_type:
            return 'storage'
        if picking_type == warehouse.in_type_id or picking_type.code == 'incoming':
            return 'receipt'
        return False

    @api.depends(
        'move_line_ids.lot_id',
        'move_line_ids.lot_name',
        'move_line_ids.supplier_batch_no',
    )
    def _compute_sn_batch_names(self):
        lots = defaultdict(set)
        supplier_batches = defaultdict(set)
        if self.ids:
            lines = self.env['stock.move.line'].search([('move_id', 'in', self.ids)])
            for line in lines:
                lot_name = line.lot_id.name or line.lot_name
                if lot_name:
                    lots[line.move_id.id].add(lot_name)
                if line.supplier_batch_no:
                    supplier_batches[line.move_id.id].add(line.supplier_batch_no)
        for move in self:
            move.sn_lot_names = ', '.join(sorted(lots.get(move.id, ()))) or False
            move.sn_supplier_batch_no = (
                ', '.join(sorted(supplier_batches.get(move.id, ()))) or False
            )

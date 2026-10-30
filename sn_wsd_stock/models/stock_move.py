from collections import defaultdict

from odoo import api, fields, models

# Kinds of operation a stock move belongs to, in the order the detail reports
# list them. The kind is read from the operation type of the transfer: the
# operation types are created with the warehouse (or lazily by the MES module)
# and have no xmlid, so a report cannot filter on a fixed record. The code of
# the operation type cannot tell them apart either: the other receipts, the
# vendor return and the receipt share the incoming code, the other deliveries
# and the delivery share the outgoing code, and the quality control, the
# storage and the MES operations share the internal one.
SN_OPERATION_KINDS = [
    ('receipt', 'Receipt'),
    ('consignment_in', 'Consignment Receipt'),
    ('qc', 'Quality Control'),
    ('storage', 'Storage'),
    ('other_in', 'Other Receipt'),
    ('other_out', 'Other Delivery'),
    ('vendor_return', 'Return to Vendor'),
    ('pick', 'Pick'),
    ('pack', 'Pack'),
    ('delivery', 'Delivery'),
    ('outsourcing_issue', 'Outsourcing Issue'),
    ('internal', 'Internal Transfer'),
    ('manufacture', 'Manufacturing'),
    ('pbm', 'Picking Before Manufacturing'),
    ('sam', 'Stock After Manufacturing'),
    ('mes_issue', 'Material Issue'),
    ('mes_return', 'Material Return'),
    ('mes_over_pick', 'Material Over-pick'),
    ('mes_fg_receipt', 'Finished Goods Receipt'),
]


class StockMove(models.Model):
    """Columns of the operation detail reports.

    Every operation type of a warehouse has its own detail report. A purchase
    reception goes through up to three operations whose types the warehouse
    reception steps create: the receipt itself, the quality control and the
    storage transfer. The other receipts and deliveries, the vendor returns,
    the pick, pack and delivery steps, the internal transfers, the
    manufacturing operations and the MES requisitions each have their own type
    too. The reports list one line per move of those operations; the document
    information the lines repeat is carried by related fields so that the list
    can print it once per document (see the merged cells list of
    ``sn_wsd_list``).
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
    sn_operation_kind = fields.Selection(
        selection=SN_OPERATION_KINDS,
        string='Operation Kind',
        compute='_compute_sn_operation_kind',
        store=True,
        index=True,
        help='Kind of operation this move belongs to, read on the operation '
             'type of its transfer. It drives the operation detail reports '
             'and tells the operations sharing an incoming, outgoing or '
             'internal code apart.',
    )
    sn_warehouse_id = fields.Many2one(
        'stock.warehouse',
        related='picking_type_id.warehouse_id',
        string='Operation Warehouse',
        readonly=True,
        store=True,
        help='Warehouse of the operation type of the move. The warehouse '
             'field of the move is the one the procurement routes read, not '
             'the one the operation belongs to.',
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
    sn_issue_type_id = fields.Many2one(
        related='picking_id.sn_issue_type_id',
        string='Issue Type',
        readonly=True,
        store=True,
    )
    sn_receive_type_id = fields.Many2one(
        related='picking_id.sn_receive_type_id',
        string='Receipt Type',
        readonly=True,
        store=True,
    )
    sn_issue_department_id = fields.Many2one(
        related='picking_id.sn_issue_department_id',
        string='Issuing Department',
        readonly=True,
        store=True,
    )
    sn_issue_employee_id = fields.Many2one(
        related='picking_id.sn_issue_employee_id',
        string='Issuing Employee',
        readonly=True,
        store=True,
    )
    sn_receive_department_id = fields.Many2one(
        related='picking_id.sn_receive_department_id',
        string='Receiving Department',
        readonly=True,
        store=True,
    )
    sn_receive_employee_id = fields.Many2one(
        related='picking_id.sn_receive_employee_id',
        string='Receiving Employee',
        readonly=True,
        store=True,
    )
    sn_mes_order_id = fields.Many2one(
        related='picking_id.x_mes_order_id',
        string='MES Order',
        readonly=True,
        store=True,
        index=True,
    )
    sn_production_id = fields.Many2one(
        'mrp.production',
        string='Production Order',
        compute='_compute_sn_production_id',
        store=True,
        index=True,
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

        Only the operation types of the reception are recognized: the other
        receipts (goods entering the stock without a purchase order) are also
        incoming transfers, but they are not part of a purchase reception and
        stay out of the three reports.
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
        if picking_type == warehouse.in_type_id:
            return 'receipt'
        return False

    @api.depends(
        'picking_type_id',
        'picking_type_id.warehouse_id',
        'picking_type_id.warehouse_id.in_type_id',
        'picking_type_id.warehouse_id.qc_type_id',
        'picking_type_id.warehouse_id.store_type_id',
        'picking_type_id.warehouse_id.pick_type_id',
        'picking_type_id.warehouse_id.pack_type_id',
        'picking_type_id.warehouse_id.out_type_id',
        'picking_type_id.warehouse_id.int_type_id',
        'picking_type_id.warehouse_id.other_in_type_id',
        'picking_type_id.warehouse_id.other_out_type_id',
        'picking_type_id.warehouse_id.sn_consignment_in_type_id',
        'picking_type_id.warehouse_id.sn_outsourcing_issue_type_id',
        'picking_type_id.warehouse_id.sn_unstored_return_type_id',
        'picking_type_id.warehouse_id.manu_type_id',
        'picking_type_id.warehouse_id.pbm_type_id',
        'picking_type_id.warehouse_id.sam_type_id',
        'picking_type_id.warehouse_id.picking_type_issue_id',
        'picking_type_id.warehouse_id.picking_type_return_id',
        'picking_type_id.warehouse_id.picking_type_over_pick_id',
        'picking_type_id.warehouse_id.picking_type_receipt_id',
        'production_id',
        'raw_material_production_id',
    )
    def _compute_sn_operation_kind(self):
        for move in self:
            move.sn_operation_kind = move._get_sn_operation_kind()

    def _get_sn_operation_kind(self):
        """Kind of operation the move belongs to.

        The kind is read by comparing the operation type of the transfer with
        the operation types of its warehouse, never on the code or the name of
        the type: several types share the incoming, outgoing and internal
        codes (other receipts, vendor returns, quality control, storage and the
        MES operations), so a code cannot tell them apart.

        A manufacturing move has no transfer: it is read on the production
        order it consumes for or produces. The activity of the operation type
        is not checked here, so the archived types still report their history;
        the reception step of the three reception reports keeps its own
        activity rule to preserve their behaviour.
        """
        self.ensure_one()
        if self.production_id or self.raw_material_production_id:
            return 'manufacture'
        picking_type = self.picking_type_id
        warehouse = picking_type.warehouse_id
        if not warehouse:
            return False
        operation_types = (
            (warehouse.in_type_id, 'receipt'),
            (warehouse.sn_consignment_in_type_id, 'consignment_in'),
            (warehouse.qc_type_id, 'qc'),
            (warehouse.store_type_id, 'storage'),
            (warehouse.other_in_type_id, 'other_in'),
            (warehouse.other_out_type_id, 'other_out'),
            (warehouse.sn_unstored_return_type_id, 'vendor_return'),
            (warehouse.pick_type_id, 'pick'),
            (warehouse.pack_type_id, 'pack'),
            (warehouse.out_type_id, 'delivery'),
            (warehouse.sn_outsourcing_issue_type_id, 'outsourcing_issue'),
            (warehouse.int_type_id, 'internal'),
            (warehouse.manu_type_id, 'manufacture'),
            (warehouse.pbm_type_id, 'pbm'),
            (warehouse.sam_type_id, 'sam'),
            (warehouse.picking_type_issue_id, 'mes_issue'),
            (warehouse.picking_type_return_id, 'mes_return'),
            (warehouse.picking_type_over_pick_id, 'mes_over_pick'),
            (warehouse.picking_type_receipt_id, 'mes_fg_receipt'),
        )
        for operation_type, kind in operation_types:
            if operation_type and picking_type == operation_type:
                return kind
        return False

    @api.depends('production_id', 'raw_material_production_id')
    def _compute_sn_production_id(self):
        for move in self:
            move.sn_production_id = (
                move.production_id or move.raw_material_production_id)

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

    @api.depends(
        'product_id', 'has_tracking', 'move_line_ids', 'state',
        'picking_id.picking_type_id',
    )
    def _compute_show_details_visible(self):
        """Show the detail button of the other operations as soon as confirmed.

        The standard computation shows it with the multi-location, package or
        owner groups, or on a tracked product, because a regular transfer fills
        its operation lines when it reserves. An other delivery never reserves
        (its destination is a virtual location) and an other receipt only does
        when its source is a virtual one: without the groups the button would
        be missing while its dialog is the only way to enter the batch, the
        package or the location of the goods.
        """
        super()._compute_show_details_visible()
        for move in self:
            picking = move.picking_id
            if (move.product_id and move.state != 'draft' and picking
                    and picking._sn_get_other_operation_kind()):
                move.show_details_visible = True

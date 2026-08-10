from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SnSmtPcbPanel(models.Model):
    """
    SMT PCB panel record model.

    Stores the relationship between a parent PCB panel and its board SN values.
    Supports F-001 panel creation and F-002 panel query integration.
    """
    _name = 'sn.smt.pcb.panel'
    _description = 'SMT PCB Panel'
    _order = 'create_date desc, id desc'

    # Main record fields.
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        index=True,
        ondelete='cascade',
        copy=False,
    )
    manufacturing_batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch',
        string='Manufacturing Batch',
        related='production_id.x_manufacturing_batch_id',
        store=True,
        readonly=True,
        index=True,
    )
    # Used to display panel records on the MRP form.
    production_name = fields.Char(
        string='MO Number',
        related='production_id.name',
        store=True,
        index=True,
    )
    product_no = fields.Char(
        string='Product No',
        required=True,
        index=True,
        help='Order number mapped to the manufacturing order number.'
    )
    quantity = fields.Integer(
        string='Panel Quantity',
        required=True,
        help='Number of boards in the panel. For example, 4 means one panel contains 4 boards.'
    )
    pcb_item_sn = fields.Char(
        string='PCB Item Code',
        index=True,
        copy=False,
        help='Internal reference of the PCB material item. Example: 3111001398.'
    )

    # Board links.
    board_ids = fields.One2many(
        'sn.smt.pcb.board',
        'panel_id',
        string='Board SN List',
        copy=True,
    )
    board_count = fields.Integer(
        string='Scanned Board Count',
        compute='_compute_board_count',
        store=True,
    )

    # State and audit fields.
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
    ], string='Status', default='draft')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    create_date = fields.Datetime(string='Create Date', index=True)
    write_date = fields.Datetime(string='Write Date')
    create_uid = fields.Many2one('res.users', string='Created By')
    write_uid = fields.Many2one('res.users', string='Updated By')

    @api.depends('board_ids')
    def _compute_board_count(self):
        for panel in self:
            panel.board_count = len(panel.board_ids)

    @api.constrains('quantity', 'board_ids')
    def _check_board_count(self):
        for panel in self:
            if panel.board_ids and len(panel.board_ids) > panel.quantity:
                raise ValidationError(_(
                    'Scanned board count (%d) cannot exceed panel quantity (%d).'
                ) % (len(panel.board_ids), panel.quantity))

    @api.constrains('quantity')
    def _check_quantity_positive(self):
        for panel in self:
            if panel.quantity < 1:
                raise ValidationError(_('Panel quantity must be positive.'))

    @api.model
    def _create_from_api(self, vals, production_id=None):
        """
        Create a panel record from API payload.

        :param vals: API parameter dictionary.
        :param production_id: Optional manufacturing order ID.
        :return: Created panel record.
        """
        binding_vals = vals.pop('bindings', [])
        pcb_item_sn = vals.get('pcb_item_sn', '').strip() or False
        if production_id:
            production = self.env['mrp.production'].browse(production_id).exists()
            if production:
                production._check_smt_pcb_board_capacity(len(binding_vals))

        # Create the panel header record.
        create_vals = {
            'product_no': vals.get('productNo', '').strip(),
            'quantity': vals.get('quantity', 1),
            'pcb_item_sn': pcb_item_sn,
            'state': 'confirmed',
        }
        if production_id:
            create_vals['production_id'] = production_id

        panel = self.create(create_vals)

        # Create linked board records.
        for binding in binding_vals:
            panel.board_ids.create({
                'panel_id': panel.id,
                'board_no': binding.get('boardNo', 1),
                'pro_sn': binding.get('proSn', '').strip(),
            })

        return panel

    def to_api_response(self):
        """Convert the record to the API response format."""
        self.ensure_one()
        return {
            'id': self.id,
            'productNo': self.product_no,
            'manufacturingBatchId': self.manufacturing_batch_id.id if self.manufacturing_batch_id else False,
            'manufacturingBatchNo': self.manufacturing_batch_id.name if self.manufacturing_batch_id else False,
            'productionId': self.production_id.id if self.production_id else False,
            'productionNo': self.production_id.name if self.production_id else False,
            'quantity': self.quantity,
            'pcbItemSn': self.pcb_item_sn,
            'bindings': [
                {
                    'boardNo': board.board_no,
                    'proSn': board.pro_sn,
                }
                for board in self.board_ids.sorted('board_no')
            ],
            'boardCount': self.board_count,
            'state': self.state,
        }

    def write(self, vals):
        """Update state when all boards have been scanned."""
        res = super().write(vals)
        # Automatically update state when all boards are scanned.
        for panel in self.filtered(lambda p: p.state == 'draft' and p.board_ids):
            if len(panel.board_ids) == panel.quantity:
                panel.state = 'confirmed'
        return res

    def action_open_board_list(self):
        """Open the board list."""
        self.ensure_one()
        return {
            'name': 'Board SN List',
            'type': 'ir.actions.act_window',
            'res_model': 'sn.smt.pcb.board',
            'view_mode': 'list',
            'domain': [('panel_id', '=', self.id)],
            'context': {'default_panel_id': self.id},
        }


class SnSmtPcbBoard(models.Model):
    """
    SMT PCB board record.

    Stores each board SN in a panel.
    """
    _name = 'sn.smt.pcb.board'
    _description = 'SMT PCB Board'
    _order = 'board_no asc, id asc'

    panel_id = fields.Many2one(
        'sn.smt.pcb.panel',
        string='Panel',
        index=True,
        required=True,
        ondelete='cascade',
    )
    board_no = fields.Integer(
        string='Board No',
        required=True,
        help='Board number in the panel, such as 1, 2, 3, or 4.'
    )
    pro_sn = fields.Char(
        string='Product SN',
        required=True,
        index=True,
        help='Product serial number of the board.'
    )
    state = fields.Selection(
        [
            ('active', 'Active'),
            ('scrapped', 'Scrapped'),
            ('voided', 'Voided'),
            ('replaced', 'Replaced'),
        ],
        string='Status',
        default='active',
        index=True,
        copy=False,
    )

    # Link to stock.lot.
    lot_id = fields.Many2one(
        'stock.lot',
        string='Stock Lot',
        copy=False,
    )

    # Audit fields.
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='panel_id.company_id',
        store=True,
    )
    create_date = fields.Datetime(string='Create Date')
    create_uid = fields.Many2one('res.users', string='Created By')

    @api.constrains('board_no')
    def _check_board_no_range(self):
        for board in self:
            if board.board_no < 1:
                raise ValidationError(_('Board number must be greater than 0.'))
            if board.panel_id and board.board_no > board.panel_id.quantity:
                raise ValidationError(_(
                    'Board number (%d) cannot exceed panel quantity (%d).'
                ) % (board.board_no, board.panel_id.quantity))

    @api.constrains('panel_id', 'pro_sn')
    def _check_unique_pro_sn_per_panel(self):
        for board in self:
            domain = [
                ('panel_id', '=', board.panel_id.id),
                ('pro_sn', '=', board.pro_sn),
                ('id', '!=', board.id),
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(_(
                    'Board SN %s already exists in this panel.'
                ) % board.pro_sn)

    @api.constrains('panel_id', 'pro_sn', 'state')
    def _check_unique_active_pro_sn_per_production(self):
        for board in self.filtered(lambda item: item.panel_id.production_id and item.pro_sn and item.state not in ('voided', 'replaced')):
            existing = self.search([
                ('id', '!=', board.id),
                ('panel_id.production_id', '=', board.panel_id.production_id.id),
                ('pro_sn', '=', board.pro_sn),
                '|',
                ('state', '=', False),
                ('state', 'not in', ['voided', 'replaced']),
            ], limit=1)
            if existing:
                raise ValidationError(_(
                    'Board SN %s is already bound to this manufacturing order.'
                ) % board.pro_sn)

    @api.constrains('panel_id', 'board_no')
    def _check_unique_board_no_per_panel(self):
        for board in self:
            domain = [
                ('panel_id', '=', board.panel_id.id),
                ('board_no', '=', board.board_no),
                ('id', '!=', board.id),
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(_(
                    'Board number %d already exists in this panel.'
                ) % board.board_no)

    @api.constrains('panel_id', 'state')
    def _check_production_board_capacity(self):
        productions = self.mapped('panel_id.production_id').filtered('x_has_smt_operations')
        for production in productions:
            production._check_smt_pcb_board_capacity(0)

    @api.model
    def _auto_bind_lot(self, records):
        """Automatically bind stock.lot records."""
        if not records:
            return
        for record in records:
            if record.pro_sn and not record.lot_id:
                lot = self.env['stock.lot'].search([
                    ('name', '=', record.pro_sn),
                ], limit=1)
                if lot:
                    record.lot_id = lot

    @api.model_create_multi
    def create(self, vals_list):
        """Create board records."""
        records = super().create(vals_list)
        self._auto_bind_lot(records)
        return records

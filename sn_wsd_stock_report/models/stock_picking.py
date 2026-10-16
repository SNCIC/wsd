from odoo import _, api, fields, models


class StockPicking(models.Model):
    """Tag every transfer with the reception step it performs.

    The three-step reception of a warehouse chains three operations
    (receipt -> quality control -> storage) whose operation types the warehouse
    itself creates, so no domain can name them. The step is read from the
    operation type of the transfer and searched back through the operation
    types of the warehouses, which lets the reports list one step apiece
    without hard-coding a warehouse.
    """

    _inherit = 'stock.picking'

    x_reception_step = fields.Selection(
        selection=[
            ('receipt', 'Receipt'),
            ('quality', 'Quality Control'),
            ('storage', 'Storage'),
            ('other', 'Other'),
        ],
        string='Reception Step',
        compute='_compute_x_reception_step',
        search='_search_x_reception_step',
        help='Step of the reception this transfer performs: the receipt of the '
             'vendor goods, the quality control that follows it on a three-step '
             'reception, or their storage into the warehouse stock. A transfer '
             'of any other operation reports no step.',
    )

    @api.depends('picking_type_id')
    def _compute_x_reception_step(self):
        for picking in self:
            picking_type = picking.picking_type_id
            if picking_type in picking._get_warehouse_reception_step_types('receipt'):
                picking.x_reception_step = 'receipt'
            elif picking_type in picking._get_warehouse_reception_step_types('quality'):
                picking.x_reception_step = 'quality'
            elif picking_type in picking._get_warehouse_reception_step_types('storage'):
                picking.x_reception_step = 'storage'
            else:
                picking.x_reception_step = 'other'

    def _get_warehouse_reception_step_types(self, step):
        """Operation types carrying one reception step in the picking's warehouse.

        The quality-control and storage operation types stay inactive while the
        reception of their warehouse is not configured with the matching number
        of steps, and an inactive operation type carries no transfer: filtering
        them out keeps a one-step or two-step reception from reporting a step it
        does not perform.
        """
        self.ensure_one()
        picking_type = self.picking_type_id
        if not picking_type:
            return self.env['stock.picking.type']
        warehouse = (
            picking_type.warehouse_id
            or picking_type.default_location_dest_id.warehouse_id
            or picking_type.default_location_src_id.warehouse_id
        )
        if not warehouse:
            return self.env['stock.picking.type']
        if step == 'receipt':
            return warehouse.in_type_id
        if step == 'quality':
            return warehouse.qc_type_id.filtered('active')
        if step == 'storage':
            return warehouse.store_type_id.filtered('active')
        return self.env['stock.picking.type']

    @api.model
    def _get_reception_step_type_ids(self, step):
        """Ids of the operation types carrying one reception step, any warehouse."""
        warehouses = self.env['stock.warehouse'].search([])
        if step == 'receipt':
            return set(warehouses.in_type_id.ids)
        if step == 'quality':
            return set(warehouses.qc_type_id.filtered('active').ids)
        if step == 'storage':
            return set(warehouses.store_type_id.filtered('active').ids)
        return set()

    @api.model
    def _search_x_reception_step(self, operator, value):
        """Search the transfers of one reception step.

        The operation types of the steps are made up per warehouse, so the step
        is resolved back into them at search time instead of being stored on
        every transfer.
        """
        if operator not in ('=', '!='):
            raise NotImplementedError(
                _('Reception Step only supports the = and != operators.'))
        steps = {value} if isinstance(value, str) else set(value)
        selected = set()
        for step in steps - {'other'}:
            selected |= self._get_reception_step_type_ids(step)
        if 'other' not in steps:
            if operator == '=':
                return [('picking_type_id', 'in', list(selected))]
            return [('picking_type_id', 'not in', list(selected))]
        known = set()
        for step in ('receipt', 'quality', 'storage'):
            known |= self._get_reception_step_type_ids(step)
        if operator == '=':
            return ['|', ('picking_type_id', 'in', list(selected)),
                    ('picking_type_id', 'not in', list(known))]
        return ['&', ('picking_type_id', 'not in', list(selected)),
                ('picking_type_id', 'in', list(known))]

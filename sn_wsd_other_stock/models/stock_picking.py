from odoo import api, fields, models


class StockPicking(models.Model):
    """Transfers made from the other receipt and delivery operations.

    The two operations have their own identifiers on the warehouse, so a
    transfer is stamped with the other kind it belongs to when it is created.
    The list menus and the reports then tell the other receipts and deliveries
    apart from the purchase receipts and the sales deliveries, which share the
    same ``incoming`` and ``outgoing`` codes.
    """

    _inherit = 'stock.picking'

    sn_other_operation = fields.Selection(
        selection=[
            ('other_in', 'Other Receipt'),
            ('other_out', 'Other Delivery'),
        ],
        string='Other Operation',
        compute='_compute_sn_other_operation',
        store=True,
        index=True,
        help='Other receipt or other delivery the transfer was created from, '
             'empty on the purchase receipts and the sales deliveries.',
    )

    @api.depends('picking_type_id')
    def _compute_sn_other_operation(self):
        for picking in self:
            picking_type = picking.picking_type_id
            warehouse = picking_type.warehouse_id
            if warehouse and picking_type == warehouse.other_in_type_id:
                picking.sn_other_operation = 'other_in'
            elif warehouse and picking_type == warehouse.other_out_type_id:
                picking.sn_other_operation = 'other_out'
            else:
                picking.sn_other_operation = False

    @api.model
    def default_get(self, fields_list):
        """Default the operation of the other receipt and delivery menus.

        The menus cannot know the operation type of the warehouse in their
        action, so they pass the kind in the context and the default type,
        source and destination locations are read from it.
        """
        res = super().default_get(fields_list)
        other_operation = self.env.context.get('sn_other_operation_default')
        if not other_operation or res.get('picking_type_id'):
            return res
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        if not warehouse:
            return res
        picking_type = (
            warehouse.other_in_type_id
            if other_operation == 'other_in'
            else warehouse.other_out_type_id
        )
        if not picking_type:
            return res
        res['picking_type_id'] = picking_type.id
        if 'location_id' in fields_list:
            res['location_id'] = picking_type.default_location_src_id.id
        if 'location_dest_id' in fields_list:
            res['location_dest_id'] = picking_type.default_location_dest_id.id
        return res

from odoo import api, fields, models


class StockPicking(models.Model):
    """Keep the delivery address editable, and say so when it changes late.

    The address of a transfer (``partner_id``: delivery address on a delivery,
    receive-from on a receipt, contact on an internal transfer) is opened up
    in every state, so an address forgotten before validation can still be
    corrected. A change made on a done or cancelled transfer is posted on the
    chatter: the document no longer matches what was signed, delivered or
    invoiced, and the note keeps that visible.
    """

    _inherit = 'stock.picking'

    def _get_unstored_return_picking_type(self):
        """Return operation used to send received goods back to the vendor.

        With a multi-step reception the goods go through the receipt, the
        quality control and the storage transfers. All three are returned
        through the dedicated vendor return operation: its lot options are
        disabled, so the goods not stored yet leave without a batch, while the
        goods already stored keep their batch, brought on the move line by the
        reservation, and the stock is decreased on that batch. A one-step
        reception creates the lots itself, so its return keeps the standard
        delivery operation.
        """
        self.ensure_one()
        warehouse = self.picking_type_id.warehouse_id
        if not warehouse or warehouse.reception_steps == 'one_step':
            return self.env['stock.picking.type']
        reception_types = (
            warehouse.in_type_id | warehouse.qc_type_id
            | warehouse.store_type_id)
        if self.picking_type_id not in reception_types:
            return self.env['stock.picking.type']
        return warehouse._ensure_unstored_return_type()

    def _get_vendor_return_location(self):
        """Vendor location the returned goods are sent back to."""
        self.ensure_one()
        supplier_location = self.partner_id.with_company(
            self.company_id).property_stock_supplier
        if supplier_location and supplier_location.usage == 'supplier':
            return supplier_location
        return self.env.ref('stock.stock_location_suppliers')

    def write(self, vals):
        if 'partner_id' not in vals or self.env.context.get(
                'sn_skip_picking_partner_audit'):
            return super().write(vals)
        late = self.filtered(lambda picking: picking.state in ('done', 'cancel'))
        previous = {picking.id: picking.partner_id.display_name for picking in late}
        result = super().write(vals)
        for picking in late:
            new_name = picking.partner_id.display_name or self.env._('None')
            if previous[picking.id] != new_name:
                picking.message_post(body=self.env._(
                    'Contact changed after validation by %(user)s: '
                    '%(old)s -> %(new)s',
                    user=self.env.user.display_name,
                    old=previous[picking.id] or self.env._('None'),
                    new=new_name,
                ))
        return result

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
        if not other_operation:
            return res
        if self.env.context.get('default_picking_type_id'):
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

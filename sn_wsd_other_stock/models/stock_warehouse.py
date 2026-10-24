from odoo import _, fields, models


class StockWarehouse(models.Model):
    """Other receipt and delivery operations.

    The other receipts bring goods into the stock without a purchase order and
    the other deliveries take them out without a sales order, the way the Kingdee
    other receipt and other delivery documents do. Both are regular transfers of
    their own operation type, so the confirm, assign and validate flow, the
    batches and the reporting work as on every other transfer.

    The operations are created with the warehouse, next to its receipt and
    delivery types, and are archived with it.
    """

    _inherit = 'stock.warehouse'

    other_in_type_id = fields.Many2one(
        'stock.picking.type',
        string='Other Receipt Type',
        check_company=True,
        copy=False,
        help='Operation type of the other receipts: goods entering the stock '
             'without a purchase order.',
    )
    other_out_type_id = fields.Many2one(
        'stock.picking.type',
        string='Other Delivery Type',
        check_company=True,
        copy=False,
        help='Operation type of the other deliveries: goods leaving the stock '
             'without a sales order.',
    )

    def _get_picking_type_update_values(self):
        values = super()._get_picking_type_update_values()
        values['other_in_type_id'] = {'active': self.active}
        values['other_out_type_id'] = {'active': self.active}
        return values

    def _get_picking_type_create_values(self, max_sequence):
        values, max_sequence = super()._get_picking_type_create_values(max_sequence)
        supplier_location = self.env.ref('stock.stock_location_suppliers')
        customer_location = self.env.ref('stock.stock_location_customers')
        barcode_prefix = self.code.replace(" ", "").upper()
        values['other_in_type_id'] = {
            'name': _('Other Receipts'),
            'code': 'incoming',
            'sequence_code': 'OIN',
            'sequence': max_sequence + 1,
            'default_location_src_id': supplier_location.id,
            'default_location_dest_id': self.lot_stock_id.id,
            'barcode': barcode_prefix + 'OIN',
            'company_id': self.company_id.id,
        }
        values['other_out_type_id'] = {
            'name': _('Other Deliveries'),
            'code': 'outgoing',
            'sequence_code': 'OOUT',
            'sequence': max_sequence + 2,
            'default_location_src_id': self.lot_stock_id.id,
            'default_location_dest_id': customer_location.id,
            'barcode': barcode_prefix + 'OOUT',
            'company_id': self.company_id.id,
        }
        return values, max_sequence + 2

    def _get_sequence_values(self, name=False, code=False):
        values = super()._get_sequence_values(name=name, code=code)
        name = name if name else self.name
        code = code if code else self.code
        values['other_in_type_id'] = {
            'name': _('%(name)s Sequence other receipts', name=name),
            'prefix': code + '/' + (self.other_in_type_id.sequence_code or 'OIN') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        values['other_out_type_id'] = {
            'name': _('%(name)s Sequence other deliveries', name=name),
            'prefix': code + '/' + (self.other_out_type_id.sequence_code or 'OOUT') + '/',
            'padding': 5,
            'company_id': self.company_id.id,
        }
        return values

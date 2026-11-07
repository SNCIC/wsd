from odoo import Command, api, models


class StockPicking(models.Model):
    """Fill the receipt of the buying company with what the delivery of the
    selling company just sent, so the goods are not received twice by hand."""

    _name = 'stock.picking'
    _inherit = ['stock.picking', 'sn.intercompany.sync.mixin']

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if not picking.sale_id or picking.picking_type_code not in ('outgoing', 'dropship'):
                continue
            agreement, direction, company = picking._sn_resolve('stock.picking')
            if agreement and not direction:
                continue
            if not company:
                continue
            if not agreement and not company.sudo().intercompany_sync_delivery_receipt:
                continue
            purchase_order = self.env['purchase.order'].sudo().search([
                ('name', '=', picking.sale_id.client_order_ref),
                ('company_id', '=', company.id),
            ], limit=1)
            receipts = purchase_order.picking_ids.filtered(
                lambda p: p.picking_type_code in ('incoming', 'dropship'))
            if not receipts:
                continue
            ProductMap = self.env['sn.intercompany.product.map']
            agreement = picking.sale_id.intercompany_agreement_id
            for move in picking.move_ids:
                if move.state != 'done':
                    continue
                target_product = move.product_id
                if target_product.company_id and target_product.company_id != company:
                    target_product, _mapping, _mode = ProductMap._sn_resolve_product(
                        target_product, company, agreement=agreement, create=False)
                if not target_product:
                    # The line was copied as text: there is nothing to receive.
                    continue
                receipt_move = self._find_corresponding_move(target_product, receipts)
                if not receipt_move:
                    continue
                receipt_move.write({
                    'move_line_ids': [
                        *[Command.delete(move_line.id) for move_line in receipt_move.move_line_ids],
                        *[Command.create(vals) for vals in self._prepare_move_lines(move, receipt_move)],
                    ],
                })
                receipt_move.move_line_ids._apply_putaway_strategy()
            picking._sn_log('update', target=receipts[:1],
                            detail='Receipt filled from the delivery.')
        return res

    @api.model
    def _find_corresponding_move(self, target_product, candidate_pickings):
        """Move of the receipt carrying what the delivery sends.

        The two companies hold different products for the same article, so the
        delivery move is compared through the product of the receipt, resolved
        beforehand for the buying company.
        """
        for move in candidate_pickings.move_ids:
            if move.product_id == target_product and not move.picked:
                return move
        return self.env['stock.move']

    @api.model
    def _prepare_move_lines(self, delivery_move, receipt_move):
        move_lines_vals = []
        for move_line in delivery_move.move_line_ids:
            vals = receipt_move._prepare_move_line_vals(quantity=0)
            if move_line.lot_id:
                vals['lot_name'] = move_line.lot_id.name
                if not move_line.lot_id.company_id:
                    vals['lot_id'] = move_line.lot_id.id
            vals['quantity'] = move_line.quantity
            vals['picked'] = True
            move_lines_vals.append(vals)
        return move_lines_vals

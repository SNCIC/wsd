from odoo import models


class StockPickingCodeRule(models.Model):
    """Coding-rule hook for stock.picking: when the picking's operation
    type matches a sn.code.rule, that rule generates the name instead of
    the native per-type ir.sequence. Pickings without a matching rule keep
    the native behavior untouched (design decision 5)."""

    _inherit = 'stock.picking'

    def create(self, vals_list):
        rule_model = self.env['sn.code.rule']
        for vals in vals_list:
            if vals.get('name', '/') != '/':
                continue  # explicit name wins
            picking_type_id = vals.get('picking_type_id')
            if not picking_type_id:
                continue
            # build a new() proxy to render against pre-create vals
            proxy = self.new({
                'picking_type_id': picking_type_id,
                'company_id': vals.get('company_id')
                    or self.env['stock.picking.type'].browse(
                        picking_type_id).company_id.id,
                'partner_id': vals.get('partner_id'),
                'origin': vals.get('origin'),
                'x_mes_order_id': vals.get('x_mes_order_id'),
            })
            rule = rule_model._find_rule(proxy)
            if rule:
                vals['name'] = rule.render(proxy)
        return super().create(vals_list)

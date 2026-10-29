from odoo import api, models

# Names of the inventory adjustment location, in the languages the databases
# may carry: the location is created by Odoo without a XML id and is translated
# when the database itself is translated.
INVENTORY_ADJUSTMENT_NAMES = (
    'Inventory adjustment',
    '库存调整',
)


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _sn_get_inventory_adjustment_location(self, company=None):
        """Return the inventory adjustment location of a company.

        Odoo creates that location without a XML id, and the other locations
        with an ``inventory`` usage (the scrap location, the virtual locations
        of the other operations) sort before it on ``complete_name``: looking
        the location up on the usage alone returns the wrong one. The location
        is therefore read from the default stock location of the products
        first, then matched on its name, and only falls back on the usage.
        """
        company = company or self.env.company
        domain = [
            ('usage', '=', 'inventory'),
            ('company_id', 'in', [company.id, False]),
        ]
        default_location_id = self.env['ir.default']._get(
            'product.template', 'property_stock_inventory',
            company_id=company.id)
        if default_location_id:
            location = self.browse(default_location_id).exists()
            if location and location.usage == 'inventory':
                return location
        location = self.search(
            domain + [('name', 'in', list(INVENTORY_ADJUSTMENT_NAMES))],
            limit=1)
        return location or self.search(domain, limit=1)

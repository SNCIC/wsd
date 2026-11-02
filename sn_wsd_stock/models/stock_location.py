from odoo import _, api, models

# Names of the inventory adjustment location, in the languages the databases
# may carry: the location is created by Odoo without a XML id and is translated
# when the database itself is translated.
INVENTORY_ADJUSTMENT_NAMES = (
    'Inventory adjustment',
    '库存调整',
)

# Virtual locations the inventory loss and the inventory gain operations end
# on. Both carry the inventory usage, like the inventory adjustment location,
# so the goods leaving to them (loss) or coming from them (gain) are valued by
# the accounting entry. The name of a location is not translatable: it is
# written in the language of the administrator creating it, so the English and
# the translated names are both matched when the location is looked up.
INVENTORY_LOSS_LOCATION_NAME = 'Inventory Loss'
INVENTORY_GAIN_LOCATION_NAME = 'Inventory Gain'


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

    @api.model
    def _sn_inventory_operation_location_names(self, kind):
        """Names the inventory loss or gain location may carry.

        The name of a location is not translatable: it is written in the
        language of the administrator who created the location, so the English
        name and its translation in every active language are matched. A user
        working in another language then finds the existing location instead
        of creating a second one.
        """
        english = (
            INVENTORY_LOSS_LOCATION_NAME
            if kind == 'loss'
            else INVENTORY_GAIN_LOCATION_NAME
        )
        names = {english}
        languages = self.env['res.lang'].search([('active', '=', True)])
        for code in languages.mapped('code'):
            names.add(self.with_context(lang=code).env._(english))
        return names

    @api.model
    def _sn_get_inventory_operation_location(self, kind, company=None):
        """Return the virtual location of the inventory loss or gain operation.

        The difference is booked on the stock valuation account of the
        location the goods move through, so each operation owns its location:
        the loss account of the loss operation and the gain account of the
        gain operation are the ones set on those locations. The location is
        looked up on its name first, so a database carrying it already (or an
        administrator having renamed it) keeps a single one; it is created
        otherwise, with the valuation account of the inventory adjustment
        location as a seed, because a location without account books no
        accounting entry at all.
        """
        company = company or self.env.company
        location = self.search([
            ('usage', '=', 'inventory'),
            ('name', 'in', list(
                self._sn_inventory_operation_location_names(kind))),
            ('company_id', 'in', [company.id, False]),
        ], limit=1)
        if location:
            return location
        values = {
            'name': _('Inventory Loss') if kind == 'loss' else _('Inventory Gain'),
            'usage': 'inventory',
            'company_id': company.id,
        }
        if 'valuation_account_id' in self._fields:
            adjustment_location = self._sn_get_inventory_adjustment_location(
                company)
            values['valuation_account_id'] = (
                adjustment_location.valuation_account_id.id)
        return self.create(values)

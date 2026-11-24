from odoo import api, fields, models


class StockLocation(models.Model):
    """Report location of the stock in/out balance report.

    The site keeps one Odoo warehouse per legal entity and models the real
    stores as internal locations below it (raw material store, finished goods
    store, line side store, receiving area, ...). The pick-light shelves below
    the stock area are storage slots of a store, not stores of their own.

    A location is therefore a report location when it is the stock area of a
    warehouse, a location directly below the warehouse view location, or a
    location directly below the stock area whose name does not look like a
    storage slot (a slot name carries a dash, e.g. ``Picklight-W5116-B3``).
    Every deeper location is reported on its closest report location, so the
    slots of a store stay inside it instead of showing up one row each.
    """

    _inherit = 'stock.location'

    sn_report_location_id = fields.Many2one(
        comodel_name='stock.location',
        string='Report Location',
        compute='_compute_sn_report_location_id',
        store=True,
        index=True,
        recursive=True,
        help="Location the movements of this location are reported on in the "
             "stock in/out balance report: the store the location belongs to.",
    )

    @api.depends(
        'usage',
        'location_id',
        'name',
        'location_id.sn_report_location_id',
    )
    def _compute_sn_report_location_id(self):
        warehouses = self.env['stock.warehouse'].search([])
        stock_area_ids = set(warehouses.lot_stock_id.ids)
        view_area_ids = set(warehouses.view_location_id.ids)
        for location in self:
            if location.usage != 'internal':
                location.sn_report_location_id = False
                continue
            parent = location.location_id
            if location.id in stock_area_ids:
                location.sn_report_location_id = location
            elif parent.id in view_area_ids:
                location.sn_report_location_id = location
            elif parent.id in stock_area_ids and '-' not in (location.name or ''):
                location.sn_report_location_id = location
            else:
                location.sn_report_location_id = (
                    parent.sn_report_location_id or location
                )

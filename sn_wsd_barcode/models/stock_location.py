# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class StockLocation(models.Model):
    _inherit = 'stock.location'
    _barcode_field = 'barcode'

    @api.model
    def _search(self, domain, *args, **kwargs):
        domain = self.env.company.nomenclature_id._preprocess_gs1_search_args(domain, ['location', 'location_dest'])
        return super()._search(domain, *args, **kwargs)

    @api.model
    def _get_fields_sn_wsd_barcode(self):
        return ['barcode', 'display_name', 'name', 'parent_path', 'usage']

    def get_counted_quant_data_records(self):
        self.ensure_one()
        return self.quant_ids.get_sn_wsd_barcode_data_records()

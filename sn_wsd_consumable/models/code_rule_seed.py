from odoo import api, models


class SnConsumableCodeSeed(models.AbstractModel):
    """Seeds the default coding rule for consumable individual SNs
    (mes-coding-rule batch 5): FL-YYYYMMDD-NNNN, counter reset daily.

    The seed is idempotent: it skips when any rule already targets the
    model, so a user-configured rule is never duplicated or overwritten.
    """

    _name = 'sn.consumable.code.seed'
    _description = 'Consumable Coding Rule Seeder'

    @api.model
    def _seed_consumable_sn_rule(self):
        Rule = self.env['sn.code.rule']
        model_id = self.env['ir.model']._get_id('sn.consumable.info')
        if not model_id or Rule.search_count([
                ('model_id', '=', model_id), ('picking_type_id', '=', False)]):
            return
        Rule.create({
            'name': 'Consumable SN Coding',
            'model_id': model_id,
            'target_field': 'sn',
            'separator': '-',
            'segment_ids': [
                (0, 0, {'segment_type': 'fixed', 'text_value': 'FL'}),
                (0, 0, {'segment_type': 'date',
                        'date_source': 'today', 'date_format': '%Y%m%d'}),
                (0, 0, {'segment_type': 'seq', 'padding': 4,
                        'period': 'day', 'seq_impl': 'engine'}),
            ],
        })

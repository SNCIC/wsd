from odoo import api, models


class SnToolingCodeSeed(models.AbstractModel):
    """Seeds the default coding rule for tooling individual SNs
    (mes-coding-rule batch 5): TG-YYYYMMDD-NNNN, counter reset daily.

    The seed is idempotent: it skips when any rule already targets the
    model, so a user-configured rule is never duplicated or overwritten.
    """

    _name = 'sn.tooling.code.seed'
    _description = 'Tooling Coding Rule Seeder'

    @api.model
    def _seed_tooling_sn_rule(self):
        Rule = self.env['sn.code.rule']
        model_id = self.env['ir.model']._get_id('sn.tooling')
        if not model_id or Rule.search_count([
                ('model_id', '=', model_id), ('picking_type_id', '=', False)]):
            return
        Rule.create({
            'name': 'Tooling SN Coding',
            'model_id': model_id,
            'target_field': 'sn',
            'separator': '-',
            'segment_ids': [
                (0, 0, {'segment_type': 'fixed', 'text_value': 'TG'}),
                (0, 0, {'segment_type': 'date',
                        'date_source': 'today', 'date_format': '%Y%m%d'}),
                (0, 0, {'segment_type': 'seq', 'padding': 4,
                        'period': 'day', 'seq_impl': 'engine'}),
            ],
        })

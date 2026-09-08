from odoo import api, fields, models

# One template per family (mes-coding-rule batch 4): fixed prefix +
# %Y%m date + '-' + engine counter reset monthly — matching the legacy
# ir.sequence prefixes (QI%(y)s%(month)s-...). The engine counter takes
# over the current value of the replaced sequence for the running month
# (pre-seeded counter rows below), then restarts at 1 on month change.
QUALITY_RULE_SEEDS = [
    # (model, rule name, prefix, sequence code)
    ('sn.wsd.quality.issue', 'Quality Issue Coding', 'QI',
     'sn.wsd.quality.issue'),
    ('sn.wsd.serial.freeze', 'SN Freeze Coding', 'FRZ',
     'sn.wsd.serial.freeze'),
    ('sn.wsd.quality.inspection.skip', 'Inspection Skip Coding', 'QSK',
     'sn.wsd.quality.inspection.skip'),
    ('sn.wsd.quality.inspection.sample', 'Inspection Sample Coding', 'QSP',
     'sn.wsd.quality.inspection.sample'),
]

# The FAI/IQC/IPQC/OQC prefixes all belong to sn.wsd.quality.inspection.
# The engine resolves one active rule per model (design decision 2), so
# this family is covered by a single rule whose prefix segment reads the
# record's inspection type (x_coding_prefix) and whose counter resets per
# type through the group field — one sequence per type, as before.
INSPECTION_TYPE_PREFIXES = ['FAI', 'IQC', 'IPQC', 'OQC']


class SnCodeRuleSeedQuality(models.AbstractModel):
    """Seeder for the quality-family coding rules (mes-coding-rule batch 4).

    Lives here instead of sn_wsd_code_rule because the engine module must
    stay free of business-model knowledge; each business module seeds its
    own documents.
    """

    _name = 'sn.code.rule.seed.quality'
    _description = 'Quality Coding Rule Seeder'

    @api.model
    def seed(self):
        """Create the quality coding rules once; idempotent."""
        rule_env = self.env['sn.code.rule']
        month_key = fields.Date.context_today(self).strftime('%Y%m')
        for model_name, rule_name, prefix, seq_code in QUALITY_RULE_SEEDS:
            model_id = self.env['ir.model']._get_id(model_name)
            if rule_env.search_count([
                    ('model_id', '=', model_id),
                    ('picking_type_id', '=', False)]):
                continue
            rule = rule_env.create({
                'name': rule_name,
                'model_id': model_id,
                'company_id': False,
                'target_field': 'name',
                'separator': '',
                'segment_ids': [
                    (0, 0, {'segment_type': 'fixed',
                            'text_value': prefix}),
                    (0, 0, {'segment_type': 'date',
                            'date_format': '%Y%m',
                            'date_source': 'today'}),
                    (0, 0, {'segment_type': 'fixed',
                            'text_value': '-'}),
                    (0, 0, {'segment_type': 'seq',
                            'padding': 5,
                            'period': 'month',
                            'seq_impl': 'engine'}),
                ],
            })
            self._carry_sequence_value(rule, month_key, seq_code)
        self._seed_inspection_rule(rule_env, month_key)

    @api.model
    def _legacy_next(self, sequence_code):
        """Current number of the replaced ir.sequence (1 when missing)."""
        sequence = self.env['ir.sequence'].sudo().search(
            [('code', '=', sequence_code)], limit=1)
        return sequence.number_next if sequence else 1

    @api.model
    def _carry_sequence_value(self, rule, month_key, sequence_code):
        """Pre-seed the current-month counter with the legacy sequence's
        current value so numbering continues seamlessly; a new month key
        starts back at the segment start value (1)."""
        seq_segment = rule.segment_ids.filtered(
            lambda segment: segment.segment_type == 'seq')
        self.env['sn.code.counter'].create({
            'segment_id': seq_segment.id,
            'key': month_key,
            'value': max(self._legacy_next(sequence_code) - 1, 0),
        })

    @api.model
    def _seed_inspection_rule(self, rule_env, month_key):
        model_id = self.env['ir.model']._get_id('sn.wsd.quality.inspection')
        if rule_env.search_count([
                ('model_id', '=', model_id),
                ('picking_type_id', '=', False)]):
            return
        rule = rule_env.create({
            'name': 'Quality Inspection Coding',
            'model_id': model_id,
            'company_id': False,
            'target_field': 'name',
            'separator': '',
            'segment_ids': [
                (0, 0, {'segment_type': 'field',
                        'field_path': 'x_coding_prefix',
                        'empty_policy': 'error'}),
                (0, 0, {'segment_type': 'date',
                        'date_format': '%Y%m',
                        'date_source': 'today'}),
                (0, 0, {'segment_type': 'fixed',
                        'text_value': '-'}),
                (0, 0, {'segment_type': 'seq',
                        'padding': 5,
                        'period': 'month',
                        'group_field_paths': 'x_coding_prefix',
                        'seq_impl': 'engine'}),
            ],
        })
        seq_segment = rule.segment_ids.filtered(
            lambda segment: segment.segment_type == 'seq')
        for prefix in INSPECTION_TYPE_PREFIXES:
            self.env['sn.code.counter'].create({
                'segment_id': seq_segment.id,
                'key': f'{month_key}|{prefix}',
                'value': max(self._legacy_next(
                    f'sn.wsd.quality.inspection.{prefix.lower()}') - 1, 0),
            })

from odoo import api, models

# One template replicated per document family (mes-coding-rule batch 4):
# fixed prefix + %Y%m%d date + engine counter, no reset — matching the
# legacy ir.sequence prefixes (REP%(y)s%(month)s%(day)s...) which never
# reset either. The counter start value carries the current value of the
# replaced ir.sequence so numbering continues seamlessly.
DEVICE_RULE_SEEDS = [
    # (model, rule name, prefix, target field, sequence code, padding)
    ('sn.wsd.device.repair.order', 'Repair Order Coding', 'REP', 'name',
     'sn.wsd.device.repair.order', 4),
    ('sn.wsd.device.cal.task', 'Calibration Task Coding', 'CAL', 'name',
     'sn.wsd.device.cal.task', 3),
    ('sn.wsd.device.check.task', 'Spot Check Task Coding', 'CKT', 'name',
     'sn.wsd.device.check.task', 3),
    ('sn.wsd.device.maint.task', 'Maintenance Task Coding', 'MT', 'name',
     'sn.wsd.device.maint.task', 3),
    ('sn.wsd.device.knowledge', 'Knowledge Coding', 'KB', 'kb_code',
     'sn.wsd.device.knowledge', 4),
    ('sn.wsd.device.oee.record', 'OEE Record Coding', 'OEE', 'name',
     'sn.wsd.device.oee.record', 3),
]


class SnCodeRuleSeedDevice(models.AbstractModel):
    """Seeder for the device-family coding rules (mes-coding-rule batch 4).

    Lives here instead of sn_wsd_code_rule because the engine module must
    stay free of business-model knowledge; each business module seeds its
    own documents.
    """

    _name = 'sn.code.rule.seed.device'
    _description = 'Device Coding Rule Seeder'

    @api.model
    def seed(self):
        """Create the six device coding rules once; idempotent."""
        rule_env = self.env['sn.code.rule']
        for model_name, rule_name, prefix, target_field, seq_code, padding \
                in DEVICE_RULE_SEEDS:
            model_id = self.env['ir.model']._get_id(model_name)
            if rule_env.search_count([
                    ('model_id', '=', model_id),
                    ('picking_type_id', '=', False)]):
                continue
            # Carry the current value of the replaced ir.sequence so the
            # engine counter continues where the sequence stopped.
            sequence = self.env['ir.sequence'].sudo().search(
                [('code', '=', seq_code)], limit=1)
            rule_env.create({
                'name': rule_name,
                'model_id': model_id,
                'company_id': False,
                'target_field': target_field,
                'separator': '',
                'segment_ids': [
                    (0, 0, {'segment_type': 'fixed',
                            'text_value': prefix}),
                    (0, 0, {'segment_type': 'date',
                            'date_format': '%Y%m%d',
                            'date_source': 'today'}),
                    (0, 0, {'segment_type': 'seq',
                            'padding': padding,
                            'period': 'none',
                            'seq_impl': 'engine',
                            'number_next': sequence.number_next
                            if sequence else 1}),
                ],
            })

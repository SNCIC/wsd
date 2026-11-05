from odoo import api, models


class SnCodeRule(models.Model):
    """Exception module's extension of the coding rule engine: hosts the
    seed of the ticket reference rule (mes-coding-rule batch 3)."""

    _inherit = 'sn.code.rule'

    @api.model
    def _seed_exception_rules(self):
        """Seed the exception ticket coding rule: EXC-<year>-<4 digit
        sequence reset yearly by the engine counter> (keeps the legacy
        EXC/<year>/ prefix semantics on the new engine). Idempotent: skips
        when the model already has a rule."""
        model_id = self.env['ir.model']._get_id('sn.wsd.exception.ticket')
        if not model_id:
            return
        if self.search_count([
                ('model_id', '=', model_id),
                ('picking_type_id', '=', False)]):
            return
        self.create({
            'name': 'Exception Ticket Coding',
            'model_id': model_id,
            'target_field': 'name',
            'separator': '-',
            'segment_ids': [
                (0, 0, {'segment_type': 'fixed', 'text_value': 'EXC'}),
                (0, 0, {'segment_type': 'date',
                        'date_format': '%Y', 'date_source': 'today'}),
                (0, 0, {'segment_type': 'seq', 'padding': 4,
                        'period': 'year', 'seq_impl': 'engine'}),
            ],
        })

"""Detection mapping engine configuration (31 testing tables).

Routes a MES test-result data point to a NQI mirror column:
(nqi model, nqi column) <- source kind + source key. Configuration
driven so new device project names are onboarded without code changes;
re-running the generation worker on a historical window backfills rows.
"""
from odoo import fields, models


class NqiFieldMapping(models.Model):
    _name = 'sn.wsd.nqi.field.mapping'
    _description = 'NQI Field Mapping'
    _rec_name = 'display_name'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    nqi_model_id = fields.Many2one(
        'ir.model', string='NQI Model', required=True, index=True,
        ondelete='cascade',
        domain="[('model', 'like', 'sn.wsd.nqi.%')]",
        help='Target mirror model (one of the testing tables).')
    nqi_model_name = fields.Char(
        string='NQI Model Name', related='nqi_model_id.model', store=True)
    nqi_field = fields.Char(
        string='NQI Column', required=True,
        help='Mirror field name (lower snake, e.g. starting_time).')
    source_kind = fields.Selection(
        [('detail_project', 'Test Detail Project Name'),
         ('payload_key', 'Result Payload Key'),
         ('result_attr', 'Result Header Attribute'),
         ('fixed', 'Fixed Value')],
        string='Source Kind', default='detail_project', required=True)
    source_key = fields.Char(
        string='Source Key', required=True,
        help='Detail project name / payload key / result attribute name, '
             'or the fixed value.')
    transform = fields.Char(
        string='Transform', help='Reserved for unit conversion rules.')
    active = fields.Boolean(string='Active', default=True, index=True)
    display_name = fields.Char(
        string='Display Name', compute='_compute_display_name')

    _mapping_uniq = models.Constraint(
        'unique(company_id, nqi_model_name, nqi_field, source_kind, '
        'source_key)',
        'A source key maps once per target column per company.',
    )

    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s.%s <- %s:%s' % (
                record.nqi_model_id.model if record.nqi_model_id else '?',
                record.nqi_field or '?',
                record.source_kind or '?',
                record.source_key or '?')

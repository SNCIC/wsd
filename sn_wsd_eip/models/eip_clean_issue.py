"""Structured problems of one cleansing pass (the readable twin of
``clean_note``).

The cleansing engine judges a wide-table row and, besides joining the
reasons into the free-text clean note, writes every problem as one row
here: kind, field, measured value and limits. The work-order overview
counts and drills down on these rows -- the note text has no contract
and no limits, the expansion interfaces judge per detail line.

Discipline: an issue belongs to the latest cleansing pass of its row.
Re-cleansing rebuilds the whole set; delivered rows are never re-judged
so their issues stay frozen with them. A failing conclusion (NG) is not
an issue -- the row's own ``conclusion`` column says it, uncleaned rows
included.
"""
from odoo import fields, models


class EipCleanIssue(models.Model):
    _name = 'sn.wsd.eip.clean.issue'
    _description = 'EIP Collection Clean Issue'
    _order = 'source_id, id'
    _check_company_auto = True
    # overview page: the row flags and the per-page problem read
    _source_kind_idx = models.Index('(source_id, kind)')

    source_id = fields.Many2one(
        'sn.wsd.eip.pass.record', string='Collection Row', required=True,
        ondelete='cascade', index=True, check_company=True)
    line_id = fields.Many2one(
        'sn.wsd.eip.pass.record.line', string='Detail Line',
        ondelete='cascade', index=True,
        help='Expansion interfaces (error detail / AC analog): the '
             'detail line the problem is about. Empty for row-level '
             'problems.')
    # stored related, never required: the row is inserted before the
    # related value is computed (same as the pass record line)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        related='source_id.company_id', store=True)
    kind = fields.Selection(
        selection=[
            ('missing', 'Missing Required'),
            ('limit', 'Out of Limit'),
            ('other', 'Other'),
        ],
        string='Kind', required=True, index=True)
    field_name = fields.Char(
        string='Value Field',
        help='Wide-table column the problem is about; empty when no '
             'single column is concerned.')
    type_code = fields.Char(
        string='Error Type',
        help='Type code of the detail line (D1..C2, IA..II1); empty '
             'for row-level problems.')
    actual_value = fields.Float(
        string='Actual Value', digits=(10, 3),
        help='Out of limit: the measured value that broke the rule.')
    lower_limit = fields.Float(string='Lower Limit', digits=(10, 3))
    upper_limit = fields.Float(string='Upper Limit', digits=(10, 3))
    message = fields.Char(
        string='Message', required=True,
        help='The same reason text the clean note carries for this '
             'problem.')


class EipPassRecordIssues(models.Model):
    _inherit = 'sn.wsd.eip.pass.record'

    issue_ids = fields.One2many(
        'sn.wsd.eip.clean.issue', 'source_id', string='Clean Issues')

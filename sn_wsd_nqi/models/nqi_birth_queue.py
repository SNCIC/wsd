"""Deferred birth queue: the station-pass transaction only enqueues one
bare row per create batch; the watermark worker dequeues and runs the
birth functions off the hot path (design decision 7, P3 taken to its
conclusion - the profiled in-transaction birth cost 2-4ms/pass in ORM
recompute coordination, the enqueue is a single bare INSERT).
"""
from odoo import fields, models


class NqiBirthQueue(models.Model):
    _name = 'sn.wsd.nqi.birth.queue'
    _description = 'NQI Birth Queue'
    _order = 'id asc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    source_model = fields.Char(string='Source Model', required=True,
                               index=True)
    source_ids = fields.Json(
        string='Source Record IDs', required=True,
        help='Event record ids of one source create batch.')
    fail_count = fields.Integer(string='Fail Count', default=0)
    error_text = fields.Text(string='Last Error', readonly=True)

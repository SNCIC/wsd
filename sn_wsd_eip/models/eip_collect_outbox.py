"""EIP collect outbox: delivery snapshots of cleansed collection rows.

One row = one record of the gateway ``data`` array. The cleansing
engine materialises payloads here (JSON shaped per the interface spec,
field names/precisions/date formats already applied); the endpoint only
claims FIFO and marks delivered. Re-cleansing of an undelivered row
supersedes its old snapshots; nothing is ever deleted.
"""
from odoo import api, fields, models


class EipCollectOutbox(models.Model):
    _name = 'sn.wsd.eip.collect.outbox'
    _description = 'EIP Collect Outbox'
    _order = 'id'
    _rec_name = 'test_code'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    source_id = fields.Many2one(
        'sn.wsd.eip.pass.record', string='Collection Row',
        ondelete='set null', index=True, check_company=True,
        help='Cleansed collection row this snapshot was built from; the '
             'snapshot columns stay self-contained if the row itself is '
             'ever removed.')
    info_type_code = fields.Char(
        string='Info Type Code', required=True, index=True)
    family = fields.Selection(
        selection=[
            ('meter', 'Electricity Meter'),
            ('collector', 'Collection Device'),
        ],
        string='Spec Family', required=True, index=True)
    test_code = fields.Char(string='Test Code', index=True)
    payload = fields.Json(
        string='Payload',
        help='The exact data[] record shipped to the gateway: spec field '
             'names, types, precisions and date formats already applied.')
    state = fields.Selection(
        selection=[
            ('qualified', 'Qualified'),
            ('delivered', 'Delivered'),
            ('superseded', 'Superseded'),
        ],
        string='State', required=True, default='qualified', index=True,
        help='Qualified: waiting for the gateway to fetch it. Delivered: '
             'fetched, frozen forever. Superseded: replaced by a newer '
             'snapshot of the same source (re-cleansing), never '
             'delivered.')
    delivered_time = fields.Datetime(
        string='Delivered Time', readonly=True,
        help='When the gateway fetched this snapshot.')

    @api.model
    def _eip_claim(self, code, amount):
        """Atomically take up to ``amount`` qualified snapshots of one
        interface code, FIFO, flipping them to delivered inside the same
        statement (concurrent gateway fetches can never double-claim),
        then freeze the source collection rows. Returns the claimed
        rows ordered by id."""
        # raw SQL claim: flush this transaction's pending writes first
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sn_wsd_eip_collect_outbox o "
            "SET state = 'delivered', "
            "    delivered_time = (now() AT TIME ZONE 'UTC') "
            "WHERE o.id IN ("
            "  SELECT id FROM sn_wsd_eip_collect_outbox"
            "  WHERE state = 'qualified' AND info_type_code = %s"
            "  ORDER BY id LIMIT %s"
            "  FOR UPDATE SKIP LOCKED) "
            "RETURNING id",
            (code, amount))
        ids = sorted(row[0] for row in self.env.cr.fetchall())
        # the UPDATE bypassed the ORM: drop the model cache
        self.invalidate_model()
        claimed = self.browse(ids)
        claimed._eip_freeze_sources()
        return claimed

    def _eip_freeze_sources(self):
        """Mark the source collection rows delivered and stamp
        upload_time (fire-and-forget delivery per the spec: the gateway
        receiving the response is the end of the story)."""
        sources = self.mapped('source_id').filtered(
            lambda row: row and row.state != 'delivered')
        if sources:
            sources.sudo().write({
                'state': 'delivered',
                'upload_time': fields.Datetime.now(),
            })

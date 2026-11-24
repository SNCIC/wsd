import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EipPushQueue(models.Model):
    """To-push list of the push engine: one row per pushed document
    that still has work to do. The scheduled worker claims rows
    atomically and pushes one document per row; a document cannot hold
    two active rows at once (partial unique index)."""
    _name = 'sn.wsd.eip.push.queue'
    _description = 'EIP Push Queue'
    _order = 'id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    config_id = fields.Many2one(
        'sn.wsd.eip.config', string='Integration Config', index=True,
        ondelete='set null', readonly=True,
        help='Config known when the row was queued; the worker resolves '
             'the current config of the document company.')
    model_name = fields.Char(string='Document Model', required=True)
    res_id = fields.Integer(string='Document ID', required=True, index=True)
    document_ref = fields.Char(
        string='Document', readonly=True,
        help='Human-readable key of the document (order number).')
    state = fields.Selection(
        [('pending', 'Pending'), ('pushing', 'Pushing'),
         ('done', 'Done'), ('failed', 'Failed')],
        string='State', required=True, default='pending', index=True)
    retry_count = fields.Integer(
        string='Retries', default=0,
        help='Automatic retries already used by this row.')
    next_attempt_at = fields.Datetime(
        string='Next Attempt', readonly=True,
        help='A pending row is claimed only after this instant.')
    last_error = fields.Text(string='Last Error', readonly=True)
    log_id = fields.Many2one(
        'sn.wsd.eip.push.log', string='Last Push Log', readonly=True,
        ondelete='set null')

    def init(self):
        # One active row per document; finished rows keep the history,
        # so the uniqueness only spans the pending/pushing rows.
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "eip_push_queue_active_uniq ON sn_wsd_eip_push_queue "
            "(model_name, res_id) "
            "WHERE state IN ('pending', 'pushing')")

    def _eip_document(self):
        self.ensure_one()
        return self.env[self.model_name].browse(self.res_id)

    def _process(self, config):
        """Push the document of this row (worker). Transport and
        platform failures never raise; user-facing guards do, and are
        turned into a failed row."""
        self.ensure_one()
        document = self._eip_document()
        if not document.exists():
            self.write({'state': 'done',
                        'last_error': _('Document deleted.')})
            return
        if (document.push_state == 'pushed' and document.eip_synced
                and not self._eip_document_is_dirty(document, config)):
            # pushed meanwhile (manual button) and unchanged since: no
            # request needed
            self.write({'state': 'done'})
            return
        try:
            result = document._eip_push_one()
        except UserError as error:
            self.write({'state': 'failed', 'last_error': str(error)})
            return
        self.write({
            'log_id': result.get('log_id') or False,
            'last_error': result.get('error') or False,
        })
        if result['success']:
            self.write({'state': 'done'})
            if self._eip_document_is_dirty(document, config):
                # edited while the request was in flight: keep a row so
                # the change is pushed too
                document._eip_enqueue(sync_only=False)
            return
        if not result.get('retryable'):
            self.write({'state': 'failed'})
            return  # the document is failed too; a human acts next
        retry_limit = config.retry_times if config else 0
        if self.retry_count < retry_limit:
            self.write({
                'state': 'pending',
                'retry_count': self.retry_count + 1,
                'next_attempt_at': fields.Datetime.now()
                + timedelta(minutes=config.retry_interval_min or 0),
            })
            document.write({'push_state': 'to_push'})
        else:
            self.write({'state': 'failed'})

    @staticmethod
    def _eip_document_is_dirty(document, config):
        """True when the current values differ from the snapshot of the
        last successful push."""
        try:
            current = document._eip_values(config)
        except UserError:
            return True
        return current != json.loads(document.eip_snapshot or '{}')


class EipPushWorker(models.AbstractModel):
    """Scheduled-job entry of the push queue."""
    _name = 'sn.wsd.eip.push.worker'
    _description = 'EIP Push Queue Worker'

    @api.model
    def _eip_claim(self, config, limit):
        """Atomically take up to ``limit`` pending rows of the config's
        company: claimed rows flip to pushing inside the same statement,
        so a concurrent run can never take them too. Returns the rows
        ordered by id."""
        # the claim is raw SQL: flush this transaction's own pending
        # writes first so the SELECT sees them
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sn_wsd_eip_push_queue q SET state = 'pushing' "
            "WHERE q.id IN ("
            "  SELECT id FROM sn_wsd_eip_push_queue"
            "  WHERE state = 'pending' AND company_id = %s"
            "    AND (next_attempt_at IS NULL"
            "         OR next_attempt_at <= (now() AT TIME ZONE 'UTC'))"
            "  ORDER BY id LIMIT %s"
            "  FOR UPDATE SKIP LOCKED) "
            "RETURNING id",
            (config.company_id.id, limit))
        ids = sorted(row[0] for row in self.env.cr.fetchall())
        # the UPDATE bypassed the ORM: drop the model cache (an empty
        # recordset's invalidate_recordset is a no-op, use the model)
        self.env['sn.wsd.eip.push.queue'].invalidate_model()
        return self.env['sn.wsd.eip.push.queue'].browse(ids)

    @api.model
    def run_push(self):
        """One batch per active integration config."""
        Queue = self.env['sn.wsd.eip.push.queue']
        for config in self.env['sn.wsd.eip.config'].sudo().search(
                [('active', '=', True)]):
            try:
                entries = self._eip_claim(
                    config, max(config.push_batch_size or 50, 1))
                for entry in entries:
                    try:
                        entry._process(config)
                    except Exception:  # noqa: BLE001 - one row must not stop the batch
                        _logger.exception(
                            'EIP push queue entry %s failed', entry)
                        entry.write({'state': 'failed',
                                     'last_error': _('Processing error; '
                                                     'see server log.')})
                        self.env['sn.wsd.eip.push.queue'].invalidate_model()
            except Exception:  # noqa: BLE001 - one config must not block the next
                _logger.exception('EIP push queue run failed for config %s',
                                  config)


class EipPushPreview(models.TransientModel):
    """Preview of the payload a document would send right now: the
    three header fields and the JSON body, nothing sent."""
    _name = 'sn.wsd.eip.push.preview'
    _description = 'EIP Push Payload Preview'

    document_ref = fields.Char(string='Document', readonly=True)
    interface_name = fields.Char(string='Interface', readonly=True)
    operatetype = fields.Char(string='Operation Type', readonly=True)
    headers_text = fields.Text(string='Request Headers', readonly=True)
    body_text = fields.Text(string='Request Body', readonly=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        model_name = self.env.context.get('active_model')
        document = self.env[model_name].browse(
            self.env.context.get('active_id'))
        if not document.exists():
            raise UserError(_('Open the preview from a pushed document.'))
        if not hasattr(document, '_eip_build_body'):
            raise UserError(_(
                'The model %s is not pushed to EIP.', model_name))
        config = document._eip_push_config()
        interface = document._eip_push_interface()
        operatetype = document._eip_operatetype()
        literal = (interface.operatetype_add
                   if operatetype == 'add'
                   else interface.operatetype_update)
        values.update({
            'document_ref': document._eip_document_ref(),
            'interface_name': '%s (%s)' % (interface.name, interface.path),
            'operatetype': literal,
            'headers_text': json.dumps(
                {'orisys': '0', 'transno': '<generated per call>',
                 'operatetype': literal}, ensure_ascii=False, indent=2),
            'body_text': json.dumps(
                document._eip_build_body(operatetype, config),
                ensure_ascii=False, indent=2),
        })
        return values

"""Push center core: state-machine closure, zero-conversion payload,
transport stub and push log.

The payload is built by field reflection: mirror field name upper-
cased = NQI column name (nqi_write_date maps back to WRITE_DATE).
Anchor m2o fields and bookkeeping columns stay out of the payload, so
adding a mirror column needs no push-code change (design decision 10).
"""
import json
import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# envelope + infrastructure columns carried by every mirror row;
# anchor m2o columns (*_id) are excluded by field type
_NQI_SKIPPED_COLUMNS = {
    'id', 'company_id', 'create_uid', 'create_date', 'write_uid',
    'write_date', '__last_update', 'display_name', 'message_follower_ids',
    'message_ids', 'activity_ids', 'message_main_attachment_id',
    'missing_fields', 'missing_count', 'push_state', 'access_url',
}


class NqiStagingMixinPush(models.AbstractModel):
    _inherit = 'sn.wsd.nqi.staging.mixin'
    _description = 'NQI Staging Envelope (push)'

    def write(self, vals):
        # pushed rows are frozen: trace-only
        if self.filtered(lambda r: r.push_state == 'pushed'):
            raise UserError(_('Pushed rows are read-only.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda r: r.push_state == 'pushed'):
            raise UserError(_('Pushed rows cannot be deleted.'))
        return super().unlink()

    def action_withdraw(self):
        for record in self:
            if record.push_state not in ('to_push', 'failed'):
                raise UserError(_('Only to-push or failed rows can be '
                                  'withdrawn.'))
        self.write({'push_state': 'draft'})

    def _nqi_payload(self):
        """Mirror row -> NQI JSON dict (column names upper-cased)."""
        self.ensure_one()
        payload = {}
        for name, field in self._fields.items():
            if not field.store or name in _NQI_SKIPPED_COLUMNS:
                continue
            if field.type == 'many2one':
                continue  # anchors and dictionary pointers stay out
            value = self[name]
            if name == 'nqi_write_date':
                value = value or fields.Datetime.now().strftime(
                    DATETIME_FORMAT)
                payload['WRITE_DATE'] = value
                continue
            payload[name.upper()] = value or ''
        return payload

    def action_preview_payload(self):
        self.ensure_one()
        payload = json.dumps(self._nqi_payload(), ensure_ascii=False,
                             indent=2)
        if len(payload) > 2000:
            payload = payload[:2000] + '\n...'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('NQI payload preview'),
                'message': payload,
                'sticky': True,
            },
        }

    def action_export_json(self):
        """Download this row's payload as a JSON file (transition export
        until the push API spec lands)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/nqi/export/%s?ids=%s' % (self._name, self.id),
            'target': 'self',
        }


class NqiPushLog(models.Model):
    _name = 'sn.wsd.nqi.push.log'
    _description = 'NQI Push Log'
    _order = 'id desc'
    _rec_name = 'model_name'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    model_name = fields.Char(string='Model', required=True, index=True)
    row_ids = fields.Text(
        string='Row IDs', required=True,
        help='Comma-separated mirror row ids of the batch.')
    payload = fields.Text(string='Payload')
    state = fields.Selection(
        [('pending', 'Pending'), ('success', 'Success'),
         ('failed', 'Failed'), ('skipped', 'Skipped')],
        string='State', default='pending', required=True, index=True)
    error_text = fields.Text(string='Error')
    retry_count = fields.Integer(string='Retry Count', default=0)
    pushed_at = fields.Datetime(string='Pushed At', readonly=True)

    def action_retry(self):
        worker = self.env['sn.wsd.nqi.worker'].sudo()
        for log in self:
            ids = [int(x) for x in log.row_ids.split(',') if x.strip()]
            rows = self.env[log.model_name].sudo().browse(ids).filtered(
                lambda r, _ids=ids: r.push_state == 'to_push')
            if rows:
                log.retry_count += 1
                worker._push_rows(rows, log)
        return True


class NqiTransportStub(models.AbstractModel):
    _name = 'sn.wsd.nqi.transport'
    _description = 'NQI Push Transport (stub)'

    @api.model
    def send(self, config, batch):
        """Send one batch of payloads. The interface spec arrives later:
        implement this method (base_url / auth_type / token / timeout /
        retry come from the config row) - nothing else changes."""
        raise NotImplementedError(
            'NQI push transport is not configured yet.')


class NqiWorkerPush(models.AbstractModel):
    _inherit = 'sn.wsd.nqi.worker'

    @api.model
    def run_push(self, model_name='sn.wsd.nqi.fit.meter.info',
                 batch_size=500):
        """Claim to_push rows atomically and hand them to the transport."""
        config_model = self.env['sn.wsd.nqi.config'].sudo()
        config = config_model.search(
            [('company_id', 'in', self.env.companies.ids)], limit=1)
        if not config or not config.api_base_url:
            return 'no push API configured - rows stay pending'
        if not self._try_lock('nqi_push'):
            return 'push already running'
        try:
            rows = self.env[model_name].sudo().search(
                [('push_state', '=', 'to_push'),
                 ('company_id', 'in', self.env.companies.ids)],
                order='id asc', limit=batch_size)
            if not rows:
                return 'nothing to push'
            claimed = self._claim(rows)
            if not claimed:
                return 'nothing left to claim'
            log = self.env['sn.wsd.nqi.push.log'].sudo().create({
                'company_id': claimed[0].company_id.id,
                'model_name': model_name,
                'row_ids': ','.join(str(i) for i in claimed.ids),
                'payload': json.dumps(
                    [row._nqi_payload() for row in claimed],
                    ensure_ascii=False),
                'state': 'pending',
            })
            self._push_rows(claimed, log)
            return 'push batch %s: %s' % (log.id, log.state)
        finally:
            self._unlock('nqi_push')

    def _claim(self, rows):
        """Atomic ownership flip: only rows still to_push move on."""
        rows.flush_model(['push_state'])
        self.env.cr.execute(
            'UPDATE %s SET push_state = \'pushing\' '
            'WHERE id IN %%s AND push_state = \'to_push\' '
            'RETURNING id' % rows._table,
            (tuple(rows.ids),))
        ids = [r[0] for r in self.env.cr.fetchall()]
        rows.invalidate_recordset(['push_state'])
        return rows.browse(ids)

    def _push_rows(self, rows, log):
        try:
            config = self.env['sn.wsd.nqi.config'].sudo().search(
                [('company_id', '=', rows[0].company_id.id)], limit=1)
            self.env['sn.wsd.nqi.transport'].send(
                config, [row._nqi_payload() for row in rows])
        except Exception as exc:  # noqa: BLE001 -- log and keep rows
            log.write({
                'state': 'failed',
                'error_text': str(exc),
            })
            rows.write({'push_state': 'failed'})
            _logger.warning('NQI push batch %s failed: %s', log.id, exc)
            return False
        log.write({'state': 'success', 'pushed_at': fields.Datetime.now()})
        rows.write({'push_state': 'pushed'})
        return True

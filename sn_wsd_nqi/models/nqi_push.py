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
        # pushed rows are frozen: trace-only (the gateway callback is
        # the one system path allowed to touch them, via context flag)
        if not self.env.context.get('nqi_system_write'):
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
            if field.type in ('many2one', 'one2many', 'many2many'):
                continue  # anchors, dictionary pointers and chatter rels
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
    callback_flag = fields.Selection(
        [('1', 'Success'), ('0', 'Failure')], string='Callback Flag',
        readonly=True, index=True)
    callback_msg = fields.Text(string='Callback Message', readonly=True)
    callback_at = fields.Datetime(string='Callback At', readonly=True)

    @api.model
    def process_callback(self, notice_no, return_flag, return_msg=''):
        """Apply an asynchronous gateway callback (by notice number).

        Success stamps the rows as platform-processed (HANDLE_FLAG 1);
        failure flags them abnormal (HANDLE_FLAG 3) and reopens them as
        failed so the withdraw-fix-repush flow applies.
        """
        log = self.search([('id', '=', int(notice_no))], limit=1)
        if not log:
            raise UserError(_('Unknown notice number %s.', notice_no))
        now = fields.Datetime.now()
        log.write({
            'callback_flag': return_flag,
            'callback_msg': return_msg or '',
            'callback_at': now,
        })
        model = self.env[log.model_name].sudo().with_context(
            nqi_system_write=True)
        rows = model.browse(
            [int(x) for x in log.row_ids.split(',') if x.strip()])
        handle_date = now.strftime('%Y-%m-%d %H:%M:%S')
        if str(return_flag) == '1':
            rows.write({'handle_flag': '1', 'handle_date': handle_date})
        else:
            rows.write({
                'push_state': 'failed',
                'handle_flag': '3',
                'handle_date': handle_date,
            })
        return True

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
    _description = 'NQI Push Transport'

    # gateway upload interface (NQI 数据上传接口 V1):
    #   POST {base_url}/interface/nqi/uploadData
    #   {"serviceName", "methodName": "getData", "noticeNo",
    #    "data": [{"table", "recond": [row dicts]}]}
    # note the spec's literal key "recond" (not "record") and the
    # ~1000-rows-per-request cap; responses are async - successes and
    # failures come back later via a noticeNo-keyed callback.
    UPLOAD_PATH = '/interface/nqi/uploadData'
    ROWS_PER_REQUEST = 900

    SERVICE_BY_GROUP = {
        'rd': 'rdService',
        'pr': 'prService',
        'pt': 'ptService',
        'fit': 'ptService',
        'mt': 'ptService',
        'tt': 'ptService',
        'ot': 'ptService',
        'sp': 'spService',
        'et': 'etService',
        'pub': 'etService',
    }

    MODEL_TABLE = {
        'sn.wsd.nqi.et.achievement': 'ET_ACHIEVEMENT_INFO',
        'sn.wsd.nqi.et.as.agreement': 'ET_AS_AGREEMENT_INFO',
        'sn.wsd.nqi.et.as.mgt': 'ET_AS_MGT_INFO',
        'sn.wsd.nqi.et.capacity': 'ET_CAPACITY_INFO',
        'sn.wsd.nqi.et.device': 'ET_DEVICE_INFO',
        'sn.wsd.nqi.et.person': 'ET_PERSON_INFO',
        'sn.wsd.nqi.et.qi': 'ET_QI_INFO',
        'sn.wsd.nqi.et.rb': 'ET_RB_INFO',
        'sn.wsd.nqi.et.staff': 'ET_STAFF_INFO',
        'sn.wsd.nqi.et.standard.setting': 'ET_STANDARD_SETTING_INFO',
        'sn.wsd.nqi.et.supplier.score': 'ET_SUPPLYER_SCORE_INFO',
        'sn.wsd.nqi.fit.component.bind': 'FIT_METER_COMPONENT_BIND',
        'sn.wsd.nqi.fit.meter.info': 'FIT_METER_INFO',
        'sn.wsd.nqi.fit.meter.mounting': 'FIT_METER_MOUNTING_MAKE',
        'sn.wsd.nqi.fit.pcb.mounting': 'FIT_PCB_MOUNTING_MAKE',
        'sn.wsd.nqi.fit.pcb.serial.bind': 'FIT_PCB_SERIAL_BIND',
        'sn.wsd.nqi.pr.arrive.batch': 'PR_COMPONENT_ARRIVE_BATCH',
        'sn.wsd.nqi.pr.bidding.change': 'PR_BIDDING_CHANGE_RECOND',
        'sn.wsd.nqi.pr.bidding.info': 'PR_BIDDING_INFO',
        'sn.wsd.nqi.pr.purchase.plan': 'PR_COMPONENT_PURCHASE_PLAN',
        'sn.wsd.nqi.pr.test.result': 'PR_COMPONENT_TEST_RESULT',
        'sn.wsd.nqi.pr.unqualified': 'PR_UNQUALIFIED_CONTROL',
        'sn.wsd.nqi.pt.env.temp.hum': 'PT_ENV_TEMP_HUM',
        'sn.wsd.nqi.pt.plan': 'PT_PRODUCTION_PLAN',
        'sn.wsd.nqi.pt.plan.detail': 'PT_PRODUCTION_DETAIL_PLAN',
        'sn.wsd.nqi.pt.procedure': 'PT_PRODUCTION_PROCEDURE',
        'sn.wsd.nqi.pt.process': 'PT_PRODUCTION_PROCESS',
        'sn.wsd.nqi.pt.unqualified': 'PT_UNQUALIFIED_CONTROL',
        'sn.wsd.nqi.pub.file': 'PUB_FILE_INFO',
        'sn.wsd.nqi.rd.component.change': 'RD_COMPONENT_CHANGE_RECORD',
        'sn.wsd.nqi.rd.component.list': 'RD_COMPONENT_DETAIL_LIST',
        'sn.wsd.nqi.rd.product.detail': 'RD_PRODUCT_DETAIL',
        'sn.wsd.nqi.rd.product.info': 'RD_PRODUCT_INFO',
        'sn.wsd.nqi.rd.product.test.report': 'RD_PRODUCT_TEST_REPORT',
        'sn.wsd.nqi.rd.project': 'RD_PROJECT',
        'sn.wsd.nqi.rd.project.change': 'RD_PROJECT_CHANGE_RECOND',
        'sn.wsd.nqi.rd.project.detail': 'RD_PROJECT_DETAIL',
        'sn.wsd.nqi.sp.box.bind': 'SP_BOX_METER_BIND',
        'sn.wsd.nqi.sp.meter.recall': 'SP_METER_RECALL',
        'sn.wsd.nqi.sp.spot.check': 'SP_SPOT_CHECK_RECORD',
        'sn.wsd.nqi.sp.supply.batch': 'SP_SUPPLY_BATCH',
        'sn.wsd.nqi.sp.supply.test': 'SP_SUPPLY_TEST',
    }

    @api.model
    def _table_for(self, model_name):
        if model_name in self.MODEL_TABLE:
            return self.MODEL_TABLE[model_name]
        # testing tables follow the mechanical rule
        suffix = model_name.replace('sn.wsd.nqi.', '')
        return suffix.upper().replace('.', '_') + '_CONC'

    @api.model
    def _service_for(self, model_name):
        # sn.wsd.nqi.<group>.<entity...>
        group = model_name.split('.', 3)[3].split('.')[0]
        return self.SERVICE_BY_GROUP.get(group, 'ptService')

    @api.model
    def build_request(self, notice_no, payloads_by_model):
        """Assemble the gateway request body.

        ``payloads_by_model``: {model_name: [payload dict, ...]}.
        Every row gets a batch-unique ID and its NOTICE_NO stamped.
        """
        data = []
        for model_name, rows in sorted(payloads_by_model.items()):
            if not rows:
                continue
            table_rows = []
            for index, row in enumerate(rows, start=1):
                record = {'ID': str(index)}
                record.update(row)
                record['NOTICE_NO'] = str(notice_no)
                table_rows.append(record)
            data.append({
                'table': self._table_for(model_name),
                'recond': table_rows,  # literal spec key
            })
        if not data:
            return None
        return {
            'serviceName': self._service_for(
                next(iter(payloads_by_model))),
            'methodName': 'getData',
            'noticeNo': str(notice_no),
            'data': data,
        }

    @api.model
    def _post(self, config, body):
        import requests
        url = config.api_base_url.rstrip('/') + self.UPLOAD_PATH
        headers = {'Content-Type': 'application/json'}
        if config.auth_type == 'bearer' and config.api_token:
            headers['Authorization'] = 'Bearer %s' % config.api_token
        elif config.auth_type == 'api_key' and config.api_token:
            headers['X-API-Key'] = config.api_token
        response = requests.post(
            url, json=body, headers=headers, timeout=config.timeout_sec)
        response.raise_for_status()
        result = response.json()
        if str(result.get('return_flag')) != '1':
            raise UserError(_(
                'Gateway rejected the batch: %s',
                result.get('return_msg', 'unknown error')))
        return result

    @api.model
    def send(self, config, rows_by_model, notice_no):
        """Upload rows in ~1000-record requests; returns request count.

        rows_by_model: {model_name: [recordset rows]} - payloads are
        built here so every request carries fresh WRITE_DATE values.
        """
        payloads = {
            model: [row._nqi_payload() for row in rows]
            for model, rows in rows_by_model.items() if rows}
        if not payloads:
            return 0
        # flatten for chunking, then regroup per request
        flat = [(model, row) for model, rows in payloads.items()
                for row in rows]
        requests_count = 0
        for start in range(0, len(flat), self.ROWS_PER_REQUEST):
            chunk = flat[start:start + self.ROWS_PER_REQUEST]
            grouped = {}
            for model, row in chunk:
                grouped.setdefault(model, []).append(row)
            body = self.build_request(notice_no, grouped)
            self._post(config, body)
            requests_count += 1
        return requests_count


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
                config, {rows._name: rows}, log.id)
        except Exception as exc:  # noqa: BLE001 -- log and keep rows
            log.write({
                'state': 'failed',
                'error_text': str(exc),
            })
            rows.write({'push_state': 'failed'})
            _logger.warning('NQI push batch %s failed: %s', log.id, exc)
            return False
        log.write({'state': 'success', 'pushed_at': fields.Datetime.now()})
        # notice_no carries the batch id for the async gateway callback
        rows.write({'push_state': 'pushed', 'notice_no': str(log.id)})
        return True

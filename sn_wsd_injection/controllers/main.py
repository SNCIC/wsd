import time

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


class SnInjApi(http.Controller):
    """注塑数采接口：数采网关/注塑机 JSON POST，无会话认证（与 sn_wsd_api 设备接口一致），
    每次调用写入设备接口日志 sn.wsd.api.request.log。"""

    def _handle(self, endpoint, method_name, model):
        start = time.time()
        try:
            payload = request.get_json_data()
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict):
            return request.make_json_response({'code': 400, 'message': 'invalid json body', 'data': False}, status=400)
        env = request.env(su=True)
        env = env(context=dict(env.context, lang='zh_CN', tz='Asia/Shanghai'))
        code, message, data = 200, 'OK', False
        try:
            data = getattr(env[model], method_name)(payload)
            request.env.cr.commit()
        except (UserError, ValidationError) as err:
            request.env.cr.rollback()
            code, message = 422, str(err)
        except Exception as err:  # noqa: BLE001
            request.env.cr.rollback()
            code, message = 500, str(err)
        env['sn.wsd.api.request.log'].create({
            'endpoint': endpoint, 'workcenter_code': payload.get('machine'),
            'result_code': str(code), 'result_message': message, 'payload': payload,
            'response': data if isinstance(data, (list, dict)) else False,
            'duration_ms': int((time.time() - start) * 1000),
        })
        request.env.cr.commit()
        return request.make_json_response({'code': code, 'message': message, 'data': data}, status=code)

    @http.route('/api/injection/shot', type='http', auth='public', methods=['POST'], csrf=False)
    def shot(self, **kwargs):
        """逐模次参数：{"machine":"ZS-01","mold":"MJ-…","shot_no":1,"cycle_time":18.2,…} 或 {"shots":[…]}"""
        return self._handle('/api/injection/shot', 'api_upload', 'sn.inj.shot')

    @http.route('/api/injection/status', type='http', auth='public', methods=['POST'], csrf=False)
    def status(self, **kwargs):
        """机台状态/计数：{"machine":"ZS-01","state":"running","counter":123456,"time":"…"} 或 {"events":[…]}"""
        return self._handle('/api/injection/status', 'api_status', 'sn.inj.machine.event')


class SnInjTerminal(http.Controller):
    """机台工位屏：显示当前模具/工单与生效工艺卡（大字号，触摸屏/工控机浏览器直接打开）。"""

    @http.route(['/injection/terminal', '/injection/terminal/<string:code>'], type='http', auth='user')
    def terminal(self, code=None, **kwargs):
        env = request.env
        machines = env['sn.inj.machine'].search([])
        machine = machines.filtered(lambda m: m.code == code)[:1] if code else machines[:1]
        plan = machine.current_plan_id
        card = plan.card_id or (machine.current_mold_id and env['sn.inj.process.card'].search(
            [('mold_id', '=', machine.current_mold_id.id), ('state', '=', 'active')], limit=1))
        groups = []
        if card:
            labels = dict(card.line_ids._fields['category'].selection)
            for cat in labels:
                lines = card.line_ids.filtered(lambda l: l.category == cat)
                if lines:
                    groups.append({'label': labels[cat], 'lines': lines})
        return request.render('sn_wsd_injection.terminal_page', {
            'machines': machines, 'machine': machine, 'plan': plan, 'card': card, 'groups': groups,
            'mold': machine.current_mold_id,
        })

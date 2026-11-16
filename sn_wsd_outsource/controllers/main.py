import time

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


class SnOutApi(http.Controller):
    """代工厂进度回报接口：代工厂 ERP/表单 JSON POST，按代工厂密钥校验，调用写入设备接口日志。"""

    @http.route('/api/outsource/progress', type='http', auth='public', methods=['POST'], csrf=False)
    def progress(self, **kwargs):
        """{"token":"代工厂密钥","order":"DG2611-0003","produced_qty":5200,"shots":5200,"good_qty":5150,
        "stage":"mass","note":"…","reporter":"…"}"""
        start = time.time()
        try:
            payload = request.get_json_data()
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict):
            return request.make_json_response({'code': 400, 'message': '请求体须为 JSON 对象', 'data': False}, status=400)
        env = request.env(su=True)
        env = env(context=dict(env.context, lang='zh_CN', tz='Asia/Shanghai'))
        code, message, data = 200, 'OK', False
        try:
            data = env['sn.out.progress'].api_report(payload)
            request.env.cr.commit()
        except (UserError, ValidationError) as err:
            request.env.cr.rollback()
            code, message = 422, str(err)
        except Exception as err:  # noqa: BLE001
            request.env.cr.rollback()
            code, message = 500, str(err)
        safe = {k: v for k, v in payload.items() if k != 'token'}
        env['sn.wsd.api.request.log'].create({
            'endpoint': '/api/outsource/progress', 'workcenter_code': payload.get('order'),
            'result_code': str(code), 'result_message': message, 'payload': safe,
            'response': data if isinstance(data, (list, dict)) else False,
            'duration_ms': int((time.time() - start) * 1000),
        })
        request.env.cr.commit()
        return request.make_json_response({'code': code, 'message': message, 'data': data}, status=code)

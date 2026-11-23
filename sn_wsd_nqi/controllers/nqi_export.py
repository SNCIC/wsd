"""JSON export endpoint: the transition outlet until the push API spec
lands (and an audit tool afterwards)."""
import json

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


class NqiExportController(http.Controller):

    @http.route('/nqi/export/<model_name>', type='http', auth='user')
    def export_json(self, model_name, ids=None, **kwargs):
        if not model_name.startswith('sn.wsd.nqi.'):
            raise AccessError(_('Unknown NQI model.'))
        if not request.env.user.has_group('sn_wsd_nqi.group_user'):
            raise AccessError(_('NQI user group required.'))
        model = request.env[model_name].sudo()
        domain = [('company_id', 'in', request.env.companies.ids)]
        if ids:
            domain.append(('id', 'in', [int(x) for x in ids.split(',')]))
        else:
            domain.append(('push_state', 'in', ('draft', 'to_push')))
        rows = model.search(domain, order='id asc', limit=5000)
        if not rows:
            raise UserError(_('Nothing to export.'))
        payload = json.dumps(
            [row._nqi_payload() for row in rows], ensure_ascii=False,
            indent=2)
        filename = '%s.json' % model_name.replace('.', '_')
        return request.make_response(
            payload,
            headers=[
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Content-Disposition', 'attachment; filename="%s"'
                 % filename),
            ])

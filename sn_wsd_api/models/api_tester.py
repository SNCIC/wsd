import json
import time
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


DEFAULT_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}
MAX_RESPONSE_BODY_LENGTH = 1024 * 1024
SCAN_PASS_ALIAS_REJECTION_BODY = {
    'M_DATA_AUTH': '1',
    'serial_number': 'SN0001',
    'workcenterCode': 'ST-001',
    'operatorCode': 'EMP001',
    'testResult': 'OK',
}
STRICT_ENDPOINT_DEFAULT_BODIES = {
    'workorder_scan_pass': {
        'M_DATA_AUTH': '1',
        'M_SN': 'SN0001',
        'M_WORK_STATIONSN': 'ST-001',
        'M_MO_NUMBER': 'MES-ORDER-TEST-001',
        'M_EMP': 'admin',
        'M_COLLABORATION_EMP': '',
        'M_TEST_RESULT': 'OK',
        'M_TEST_DETAIL': [
            {
                'item_name': 'Voltage',
                'low_limit': '0',
                'up_limit': '10',
                'item_value': '5',
                'item_result': 'OK',
            },
            {
                'item_name': 'Current',
                'low_limit': '0',
                'up_limit': '2',
                'item_value': '1',
                'item_result': 'OK',
            },
        ],
        'M_STR2': '',
        'M_PARAMETER_PLAN': '',
        'M_PROGRAM_NUM': '',
        'M_TEST_PLAN': '',
        'M_SOFTWARE_NUM': '',
        'M_SOFTWARE_NAME': '',
        'M_ADDRESS': '',
        'M_MAIN_ID': '',
        'M_MODULE_ID': '',
        'M_LEADSEAL_ID': '',
        'M_CODE_ID': '',
        'M_TOOLING': 'TOOL-001',
        'M_DEVICE_SN': 'DEV-001',
        'M_BOX_SN': '',
        'M_SECOND_SN': '',
        'M_STR1': '',
        'M_STR5': '',
        'M_STR7': '',
        'M_STR3': '',
        'M_STR4': '',
        'M_STR6': '',
        'M_STR8': '',
        'M_STR9': '',
        'M_STR10': '',
        'M_PACK_LEFT_SEAL': '',
        'M_PACK_LEFT_SEAL_RF': '',
        'M_PACK_RIGHT_SEAL': '',
        'M_PACK_RIGHT_SEAL_RF': '',
        'M_PACK_DOOR_SEAL': '',
        'M_PACK_DOOR_SEAL_RF': '',
        'M_PACK_NAMEPLATE_RF': '',
        'M_PACK_MODULE': '',
        'M_PACK_MAC': '',
        'M_PACK_TOP': '',
        'M_PACK_LEFT': '',
        'M_PACK_RIGHT': '',
        'M_PACK_BACK': '',
    },
    'panels_add': {
        'productNo': 'MO20260525123589',
        'quantity': 4,
        'pcbItemSn': '3111001398',
        'bindings': [
            {
                'boardNo': '1',
                'proSn': 'W23350859A01S012624553250',
            },
            {
                'boardNo': '2',
                'proSn': 'W23350859A01S012624553252',
            },
            {
                'boardNo': '3',
                'proSn': 'W23350859A01S012624553253',
            },
            {
                'boardNo': '4',
                'proSn': 'W23350859A01S012624553251',
            },
        ],
    },
    'panels_query': {
        'proSn': 'W23350859A01S012624553252',
    },
    'laser_print_requests': {
        'workOrderNo': 'MES-ORDER-TEST-001',
        'quantity': 10,
        'drawingNo': 'DWG-2026-A01',
        'operator': 'OP001',
    },
    'aoi_results': {
        'productSn': 'M0022S012623487760',
        'logCode': 'W2315EM0022S012623487760',
        'machineName': '\u624b\u63d23\u7ebf\u53cc\u9762AOI',
        'type': '\u63a5\u53e3',
        'retestResult': '\u5931\u6570',
        'stationResult': 'OK',
        'stationInfo': 'OK:\u8fc7\u7ad9\u6210\u529f \u5f53\u524d\u5de5\u5e8f[DIP-AOI\u5de5\u5e8f]\u5df2\u8fc7\u7ad9\u6570\u91cf[2040]##1&...',
        'testTime': '2026-06-10T17:13:08',
        'retestTime': '2026-06-10T17:15:24',
        'createTime': '2026-06-10T17:13:08',
        'fileName': 'LCAO1-3',
        'programName': 'DIP-AOI-001',
        'smallBoardNo': 'SB20260610-001',
        'totalParts': 2504,
        'errorParts': 0,
        'confirmedDefectParts': 0,
        'face': 'A',
        'operator': '2504',
        'defectDetails': [
            {
                'partId': 'R101',
                'position': 'X=12.5,Y=34.2',
                'defectCode': 'LCAO1-3',
                'defectName': '\u53cd\u4ef6',
                'confirmedResult': '\u786e\u8ba4\u4e0d\u826f',
                'imagePath': '/aoi/images/M0022S012623487760_R101.jpg',
            },
        ],
    },
}


class SnWsdApiEndpoint(models.Model):
    _name = 'sn.wsd.api.endpoint'
    _description = 'WSD API Endpoint'
    _order = 'category, sequence, id'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    category = fields.Selection(
        selection=[
            ('auth', 'Auth'),
            ('panel', 'Panel'),
            ('manufacturing', 'Manufacturing'),
            ('execution', 'Production Execution'),
            ('traceability', 'Traceability'),
            ('laser', 'Laser'),
            ('aoi', 'AOI'),
        ],
        string='Category',
        required=True,
        default='execution',
    )
    sequence = fields.Integer(default=10)
    method = fields.Selection(
        selection=[
            ('POST', 'POST'),
        ],
        string='Method',
        required=True,
        default='POST',
    )
    path = fields.Char(string='Path', required=True)
    description = fields.Text(string='Description', translate=True)
    default_headers = fields.Text(string='Default Headers JSON', default=lambda self: self._default_headers_text())
    default_body = fields.Text(string='Default Request Body', default='{}')
    is_mutating = fields.Boolean(string='May Change Data')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
    )
    test_case_ids = fields.One2many('sn.wsd.api.test.case', 'endpoint_id')
    test_case_count = fields.Integer(compute='_compute_test_case_count')

    _code_company_unique = models.Constraint(
        'UNIQUE(code, company_id)',
        'The endpoint code must be unique per company.',
    )
    _path_method_company_unique = models.Constraint(
        'UNIQUE(path, method, company_id)',
        'The endpoint path and method must be unique per company.',
    )

    @api.model
    def _default_headers_text(self):
        return json.dumps(DEFAULT_HEADERS, indent=2, ensure_ascii=False)

    @api.model
    def _sync_strict_endpoint_defaults(self):
        for code, body in STRICT_ENDPOINT_DEFAULT_BODIES.items():
            endpoints = self.search([('code', '=', code)])
            default_body = json.dumps(body, indent=2, ensure_ascii=False)
            endpoints.write({
                'default_body': default_body,
            })
            self.env['sn.wsd.api.test.case'].search([
                ('endpoint_id', 'in', endpoints.ids),
                ('is_default_case', '=', True),
            ]).write({'request_body': default_body})
        self.env['ir.model.data'].sudo().search([
            ('module', '=', 'sn_wsd_api'),
            ('model', '=', 'sn.wsd.api.endpoint'),
            ('name', 'in', [
                'endpoint_panels_add',
                'endpoint_panels_query',
                'endpoint_laser_print_requests',
                'endpoint_aoi_results',
                'endpoint_workorder_scan_pass',
            ]),
        ]).write({'noupdate': False})
        return True

    @api.constrains('path')
    def _check_path(self):
        for endpoint in self:
            if not endpoint.path or not endpoint.path.startswith('/api/v1/'):
                raise ValidationError(_('The endpoint path must start with /api/v1/.'))

    def _prepare_default_case_values(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        default_label = _('Default')
        return {
            'name': f'{self.name} - {default_label}',
            'endpoint_id': self.id,
            'method': self.method,
            'path': self.path,
            'base_url': base_url,
            'headers_json': self.default_headers or self._default_headers_text(),
            'request_body': self.default_body or '{}',
            'is_default_case': True,
            'user_id': self.env.user.id,
            'company_id': self.env.company.id,
        }

    def _get_or_create_default_case(self):
        self.ensure_one()
        case = self.env['sn.wsd.api.test.case'].search([
            ('endpoint_id', '=', self.id),
            ('user_id', '=', self.env.user.id),
            ('company_id', '=', self.env.company.id),
            ('is_default_case', '=', True),
        ], limit=1)
        if not case:
            case = self.env['sn.wsd.api.test.case'].create(self._prepare_default_case_values())
        elif case.name and case.name.endswith(' - Default'):
            case.name = self._prepare_default_case_values()['name']
        return case

    def action_open_default_test_case(self):
        self.ensure_one()
        case = self._get_or_create_default_case()
        return {
            'type': 'ir.actions.act_window',
            'name': case.name,
            'res_model': 'sn.wsd.api.test.case',
            'view_mode': 'form',
            'res_id': case.id,
            'target': 'current',
        }

    def action_view_test_cases(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('API Test Cases'),
            'res_model': 'sn.wsd.api.test.case',
            'view_mode': 'list,form',
            'domain': [('endpoint_id', '=', self.id)],
            'context': {
                'default_endpoint_id': self.id,
                'default_method': self.method,
                'default_path': self.path,
                'default_headers_json': self.default_headers,
                'default_request_body': self.default_body,
            },
        }

    @api.depends('test_case_ids')
    def _compute_test_case_count(self):
        grouped = self.env['sn.wsd.api.test.case']._read_group(
            [('endpoint_id', 'in', self.ids)],
            ['endpoint_id'],
            ['__count'],
        )
        counts = {endpoint.id: count for endpoint, count in grouped}
        for endpoint in self:
            endpoint.test_case_count = counts.get(endpoint.id, 0)


class SnWsdApiTestCase(models.Model):
    _name = 'sn.wsd.api.test.case'
    _description = 'WSD API Test Case'
    _order = 'endpoint_id, name, id'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, translate=True)
    endpoint_id = fields.Many2one(
        'sn.wsd.api.endpoint',
        string='Endpoint',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    category = fields.Selection(string='Category', related='endpoint_id.category', store=True)
    method = fields.Selection(
        selection=[
            ('POST', 'POST'),
        ],
        string='Method',
        required=True,
        default='POST',
    )
    path = fields.Char(string='Path', required=True)
    base_url = fields.Char(string='Base URL', required=True)
    headers_json = fields.Text(string='Headers JSON', default=lambda self: self.env['sn.wsd.api.endpoint']._default_headers_text())
    request_body = fields.Text(string='Request Body', default='{}')
    is_default_case = fields.Boolean(string='Is Default Case')
    active = fields.Boolean(default=True)
    user_id = fields.Many2one(
        'res.users',
        string='Owner',
        required=True,
        default=lambda self: self.env.user,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
    )
    run_ids = fields.One2many('sn.wsd.api.test.run', 'case_id', readonly=True)
    run_count = fields.Integer(compute='_compute_run_count')
    last_status_code = fields.Integer(readonly=True)
    last_elapsed_ms = fields.Integer(readonly=True)
    last_response_body = fields.Text(readonly=True)
    last_error_message = fields.Text(readonly=True)
    last_run_at = fields.Datetime(readonly=True)
    last_run_by_id = fields.Many2one('res.users', readonly=True)

    @api.onchange('endpoint_id')
    def _onchange_endpoint_id(self):
        for case in self:
            endpoint = case.endpoint_id
            if endpoint:
                case.method = endpoint.method
                case.path = endpoint.path
                case.headers_json = endpoint.default_headers or endpoint._default_headers_text()
                case.request_body = endpoint.default_body or '{}'
                if not case.base_url:
                    case.base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''

    @api.constrains('path')
    def _check_path(self):
        for case in self:
            if not case.path or not case.path.startswith('/api/v1/'):
                raise ValidationError(_('The request path must start with /api/v1/.'))

    @api.constrains('base_url')
    def _check_base_url(self):
        for case in self:
            case._validate_base_url()

    @api.depends('run_ids')
    def _compute_run_count(self):
        grouped = self.env['sn.wsd.api.test.run']._read_group(
            [('case_id', 'in', self.ids)],
            ['case_id'],
            ['__count'],
        )
        counts = {case.id: count for case, count in grouped}
        for case in self:
            case.run_count = counts.get(case.id, 0)

    def _json_loads_or_error(self, raw_text, field_label):
        self.ensure_one()
        try:
            return json.loads(raw_text or '{}')
        except ValueError as error:
            raise UserError(_('%s is not valid JSON: %s', field_label, error)) from error

    def _pretty_json_text(self, raw_text, field_label):
        parsed = self._json_loads_or_error(raw_text, field_label)
        return json.dumps(parsed, indent=2, ensure_ascii=False)

    def _validate_base_url(self):
        self.ensure_one()
        parsed = urlparse(self.base_url or '')
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValidationError(_('Base URL must be a valid HTTP or HTTPS URL.'))

        current_base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        current_host = urlparse(current_base_url).netloc
        allowed_hosts = {
            host.strip()
            for host in (self.env['ir.config_parameter'].sudo().get_param('sn_wsd_api_tester.allowed_hosts') or '').split(',')
            if host.strip()
        }
        if current_host:
            allowed_hosts.add(current_host)
        if parsed.netloc not in allowed_hosts:
            raise ValidationError(_('Base URL host is not allowed for API testing.'))

    def _make_request_url(self):
        self.ensure_one()
        self._validate_base_url()
        endpoint_path = self.path.strip()
        if not endpoint_path.startswith('/api/v1/'):
            raise UserError(_('Only /api/v1/ endpoints can be tested.'))
        return urljoin(self.base_url.rstrip('/') + '/', endpoint_path.lstrip('/'))

    def _truncate_response_body(self, text):
        if len(text) <= MAX_RESPONSE_BODY_LENGTH:
            return text
        return text[:MAX_RESPONSE_BODY_LENGTH] + '\n...[truncated]'

    def _send_http_request(self):
        self.ensure_one()
        headers = self._json_loads_or_error(self.headers_json, _('Headers JSON'))
        if not isinstance(headers, dict):
            raise UserError(_('Headers JSON must be a JSON object.'))
        body = self._json_loads_or_error(self.request_body, _('Request Body'))
        if not isinstance(body, dict):
            raise UserError(_('Request Body must be a JSON object.'))

        url = self._make_request_url()
        start = time.perf_counter()
        try:
            response = requests.request(
                method=self.method,
                url=url,
                headers=headers,
                data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                timeout=30,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            response_text = response.text or ''
            try:
                response_body = json.dumps(response.json(), indent=2, ensure_ascii=False)
            except ValueError:
                response_body = response_text
            return {
                'url': url,
                'status_code': response.status_code,
                'elapsed_ms': elapsed_ms,
                'response_body': self._truncate_response_body(response_body),
                'error_message': False,
            }
        except requests.RequestException as error:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {
                'url': url,
                'status_code': 0,
                'elapsed_ms': elapsed_ms,
                'response_body': '',
                'error_message': str(error),
            }

    def action_send_request(self):
        self.ensure_one()
        result = self._send_http_request()
        run_values = {
            'case_id': self.id,
            'endpoint_id': self.endpoint_id.id,
            'method': self.method,
            'url': result['url'],
            'headers_json': self.headers_json,
            'request_body': self.request_body,
            'status_code': result['status_code'],
            'elapsed_ms': result['elapsed_ms'],
            'response_body': result['response_body'],
            'error_message': result['error_message'],
            'run_at': fields.Datetime.now(),
            'run_by_id': self.env.user.id,
            'company_id': self.env.company.id,
        }
        self.env['sn.wsd.api.test.run'].create(run_values)
        self.write({
            'last_status_code': result['status_code'],
            'last_elapsed_ms': result['elapsed_ms'],
            'last_response_body': result['response_body'],
            'last_error_message': result['error_message'],
            'last_run_at': run_values['run_at'],
            'last_run_by_id': self.env.user.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_pretty_format_json(self):
        self.ensure_one()
        self.write({
            'headers_json': self._pretty_json_text(self.headers_json, _('Headers JSON')),
            'request_body': self._pretty_json_text(self.request_body, _('Request Body')),
        })
        return True

    def action_reset_from_endpoint(self):
        self.ensure_one()
        endpoint = self.endpoint_id
        self.write({
            'method': endpoint.method,
            'path': endpoint.path,
            'headers_json': endpoint.default_headers or endpoint._default_headers_text(),
            'request_body': endpoint.default_body or '{}',
        })
        return True

    def action_use_scan_pass_alias_rejection_body(self):
        self.ensure_one()
        if self.endpoint_id.code != 'workorder_scan_pass':
            raise UserError(_('This helper is only available for the Scan Pass endpoint.'))
        self.write({
            'request_body': json.dumps(SCAN_PASS_ALIAS_REJECTION_BODY, indent=2, ensure_ascii=False),
        })
        return True

    def action_duplicate_case(self):
        self.ensure_one()
        new_case = self.copy({
            'name': _('%s Copy', self.name),
            'is_default_case': False,
            'last_status_code': 0,
            'last_elapsed_ms': 0,
            'last_response_body': False,
            'last_error_message': False,
            'last_run_at': False,
            'last_run_by_id': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': new_case.name,
            'res_model': 'sn.wsd.api.test.case',
            'view_mode': 'form',
            'res_id': new_case.id,
            'target': 'current',
        }

    def action_view_runs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('API Test Runs'),
            'res_model': 'sn.wsd.api.test.run',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }


class SnWsdApiTestRun(models.Model):
    _name = 'sn.wsd.api.test.run'
    _description = 'WSD API Test Run'
    _order = 'run_at desc, id desc'
    _check_company_auto = True

    case_id = fields.Many2one(
        'sn.wsd.api.test.case',
        string='Test Case',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    endpoint_id = fields.Many2one(
        'sn.wsd.api.endpoint',
        string='Endpoint',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    method = fields.Selection(
        selection=[
            ('POST', 'POST'),
        ],
        string='Method',
        required=True,
    )
    url = fields.Char(string='URL', required=True)
    headers_json = fields.Text(string='Headers JSON', readonly=True)
    request_body = fields.Text(string='Request Body', readonly=True)
    status_code = fields.Integer(string='Status Code', readonly=True)
    elapsed_ms = fields.Integer(string='Elapsed MS', readonly=True)
    response_body = fields.Text(string='Response Body', readonly=True)
    error_message = fields.Text(string='Error Message', readonly=True)
    run_at = fields.Datetime(string='Run At', readonly=True)
    run_by_id = fields.Many2one('res.users', string='Run By', readonly=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
    )

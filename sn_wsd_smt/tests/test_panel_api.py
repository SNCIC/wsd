import json

from odoo.tests import HttpCase, TransactionCase, tagged


class PanelApiFixture:
    """Shared panel-API environment (service tests + HTTP wire tests)."""

    @classmethod
    def _setup_fixture(cls):
        cls.company = cls.env.company
        # M_DATA_AUTH resolves companies through company_registry
        cls.company.company_registry = 'HQ'
        cls.product = cls.env['product.product'].create({
            'name': 'P-PNL', 'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'default_code': 'DWG-PNL', 'x_board_side': 'single'})
        cls.production = cls.env['mrp.production'].create({
            'product_id': cls.product.id, 'product_qty': 100,
            'company_id': cls.company.id})
        cls.service = cls.env['sn.smt.pcb.panel.api']

    @classmethod
    def _make_identities(cls, *names):
        Identity = cls.env['sn.wsd.serial.identity']
        for name in names:
            Identity.get_or_create(name, cls.company, origin_type='laser')

    def _add_payload(self, *sns):
        return {
            'M_DATA_AUTH': 'HQ',
            'productNo': self.production.name,
            'quantity': len(sns),
            'bindings': [
                {'boardNo': str(index), 'proSn': sn}
                for index, sn in enumerate(sns, start=1)
            ],
        }


@tagged('post_install', '-at_install')
class TestPanelApiService(PanelApiFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()
        cls._make_identities('PNL-SVC-1', 'PNL-SVC-2')

    def test_01_organization_gates(self):
        result = self.service.api_panel_add(self._add_payload('PNL-SVC-1', 'PNL-SVC-2') | {'M_DATA_AUTH': ''})
        self.assertEqual(result['code'], 400)
        self.assertIn('Organization', result['message'])
        result = self.service.api_panel_add(self._add_payload('PNL-SVC-1', 'PNL-SVC-2') | {'M_DATA_AUTH': 'GHOST-ORG'})
        self.assertEqual(result['code'], 404)
        self.assertIn('Organization', result['message'])
        result = self.service.api_panel_query({'proSn': 'PNL-SVC-1'})
        self.assertEqual(result['code'], 400)

    def test_02_add_and_query(self):
        result = self.service.api_panel_add(
            self._add_payload('PNL-SVC-1', 'PNL-SVC-2'))
        self.assertEqual(result['code'], 200)
        panel = self.env['sn.smt.pcb.panel'].search([
            ('production_id', '=', self.production.id)])
        self.assertEqual(panel.company_id, self.company)
        self.assertEqual(panel.board_ids.mapped('pro_sn'),
                         ['PNL-SVC-1', 'PNL-SVC-2'])
        # any board SN brings back the whole panel
        result = self.service.api_panel_query(
            {'M_DATA_AUTH': 'HQ', 'proSn': 'PNL-SVC-2'})
        self.assertEqual(result['code'], 200)
        self.assertEqual(result['data']['total'], 1)
        self.assertEqual(result['data']['panels'][0]['productionNo'],
                         self.production.name)
        self.assertEqual(len(result['data']['panels'][0]['bindings']), 2)


@tagged('post_install', '-at_install')
class TestPanelApiHttp(PanelApiFixture, HttpCase):
    """Controller wire format: plain JSON POST, no authentication, old
    paths gone."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_fixture()
        cls._make_identities('PNL-HTTP-1', 'PNL-HTTP-2')

    def _post(self, path, body):
        return self.url_open(
            path, data=body, headers={'Content-Type': 'application/json'})

    def test_20_wire(self):
        # happy path without any credentials
        res = self._post('/api/v1/panels/add', json.dumps(
            self._add_payload('PNL-HTTP-1', 'PNL-HTTP-2')))
        body = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body['code'], 200)
        # query by any member board SN
        res = self._post('/api/v1/panels/query', json.dumps(
            {'M_DATA_AUTH': 'HQ', 'proSn': 'PNL-HTTP-1'}))
        body = res.json()
        self.assertEqual(body['code'], 200)
        self.assertEqual(body['data']['total'], 1)
        self.assertEqual(len(body['data']['panels'][0]['bindings']), 2)
        # missing organization -> uniform 400
        res = self._post('/api/v1/panels/add', json.dumps(
            {'productNo': 'X', 'bindings': []}))
        self.assertEqual(res.json()['code'], 400)

    def test_21_legacy_paths_gone(self):
        res = self._post('/api/smt/panel/add', '{}')
        self.assertEqual(res.status_code, 404)
        res = self._post('/api/smt/panel/query', '{}')
        self.assertEqual(res.status_code, 404)
        res = self.url_open('/api/smt/panel/1', method='GET')
        self.assertEqual(res.status_code, 404)
        res = self.url_open('/api/smt/panel/1', method='DELETE')
        self.assertEqual(res.status_code, 404)

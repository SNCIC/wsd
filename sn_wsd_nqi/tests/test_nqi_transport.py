import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestNqiTransport(TransactionCase):

    def _product(self, code):
        return self.env['sn.wsd.nqi.rd.product.info'].create({
            'product_code': code,
            'product_type': 'T',
            'product_name': 'N %s' % code,
            'product_categid': '101',
            'product_design_basis': 'GB',
        })

    def test_build_request_shape(self):
        transport = self.env['sn.wsd.nqi.transport']
        body = transport.build_request('77', {
            'sn.wsd.nqi.fit.meter.info': [
                {'SERIAL_NO': 'S1', 'STATUS': '1'}],
            'sn.wsd.nqi.mt.aoi': [{'PCB_CODE': 'P1'}],
        })
        self.assertEqual(body['methodName'], 'getData')
        self.assertEqual(body['noticeNo'], '77')
        self.assertEqual(body['serviceName'], 'ptService')
        tables = {block['table'] for block in body['data']}
        self.assertEqual(tables, {'FIT_METER_INFO', 'MT_AOI_CONC'})
        for block in body['data']:
            self.assertIn('recond', block)  # literal spec key
            for row in block['recond']:
                self.assertEqual(row['NOTICE_NO'], '77')
                self.assertIn('ID', row)

    def test_service_routing(self):
        transport = self.env['sn.wsd.nqi.transport']
        checks = {
            'sn.wsd.nqi.rd.product.info': 'rdService',
            'sn.wsd.nqi.pr.bidding.info': 'prService',
            'sn.wsd.nqi.pt.plan': 'ptService',
            'sn.wsd.nqi.fit.meter.info': 'ptService',
            'sn.wsd.nqi.mt.basicerr': 'ptService',
            'sn.wsd.nqi.sp.supply.batch': 'spService',
            'sn.wsd.nqi.et.device': 'etService',
        }
        for model, service in checks.items():
            self.assertEqual(transport._service_for(model), service)

    def _fake_gateway(self, flag):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                received.append((self.path, body))
                payload = json.dumps(
                    {'return_flag': flag,
                     'return_msg': 'ok'}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(
            target=server.serve_forever, daemon=True).start()
        return server, received

    def _config(self, server):
        config = self.env['sn.wsd.nqi.config'].search([
            ('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            config = self.env['sn.wsd.nqi.config'].create({
                'company_id': self.env.company.id,
                'enterprise_code': '11059',
            })
        config.write({
            'api_base_url': 'http://127.0.0.1:%d' % server.server_port,
            'auth_type': 'none',
        })
        return config

    def test_send_posts_gateway_body(self):
        server, received = self._fake_gateway('1')
        try:
            rows = self._product('TR-1') + self._product('TR-2')
            count = self.env['sn.wsd.nqi.transport'].send(
                self._config(server),
                {'sn.wsd.nqi.rd.product.info': rows}, '55')
            self.assertEqual(count, 1)
            self.assertEqual(len(received), 1)
            path, body = received[0]
            self.assertEqual(path, '/interface/nqi/uploadData')
            self.assertEqual(body['serviceName'], 'rdService')
            self.assertEqual(body['noticeNo'], '55')
            self.assertEqual(body['data'][0]['table'], 'RD_PRODUCT_INFO')
            self.assertEqual(len(body['data'][0]['recond']), 2)
            self.assertEqual(
                body['data'][0]['recond'][0]['PRODUCT_CODE'], 'TR-1')
        finally:
            server.shutdown()

    def test_send_rejects_failure_flag(self):
        server, received = self._fake_gateway('0')
        try:
            rows = self._product('TR-3')
            with self.assertRaises(UserError):
                self.env['sn.wsd.nqi.transport'].send(
                    self._config(server),
                    {'sn.wsd.nqi.rd.product.info': rows}, '56')
        finally:
            server.shutdown()

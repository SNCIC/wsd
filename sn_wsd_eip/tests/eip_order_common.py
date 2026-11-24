"""Shared fixtures of the eip-order-push tests: an in-thread fake EIP
platform (the repository has no ``requests_mock``) plus a ready-to-use
integration config. Same approach as ``sn_wsd_nqi``'s fake gateway."""

import collections
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from odoo.tests import TransactionCase


def eip_envelope(data=None, status='00000', message='ok', successful=True,
                 **extra):
    """Build a response body shaped like the spec samples; ``extra`` keys
    land in ``resultValue`` (e.g. a flat ``pageCount``)."""
    result_value = {'status': status, 'message': message, 'data': data}
    result_value.update(extra)
    return {
        'successful': successful,
        'type': '',
        'resultHint': '',
        'resultValue': result_value,
        'errorPage': '',
    }


class _FakeEipHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode('utf-8'))
        except ValueError:
            body = None
        server = self.server.eip_server
        server.requests.append({
            'path': self.path,
            'headers': {key.lower(): value
                        for key, value in self.headers.items()},
            'json': body,
            'raw': raw,
        })
        http_status, payload, delay = server.next_response()
        if delay:
            time.sleep(delay)
        if isinstance(payload, bytes):
            data = payload
        else:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(http_status)
            self.send_header('Content-Type', 'application/json;charset=UTF-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            # the client already gave up (timeout scenarios)
            pass

    def log_message(self, *args):
        pass


class _FakeEipHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # a client that timed out closes its socket first: not an error
        pass


class FakeEipServer:
    """Stands in for the EIP platform inside the test process.

    Responses are queued with :meth:`enqueue` and served in order; a
    request arriving with an empty queue gets a plain success. Every
    received request (path, lower-cased headers, parsed JSON, raw
    bytes) is appended to ``requests``.
    """

    def __init__(self):
        self.requests = []
        self._responses = collections.deque()
        self._httpd = None
        self._thread = None
        self.url = ''

    def enqueue(self, payload=None, http_status=200, delay=0.0):
        if payload is None:
            payload = eip_envelope()
        self._responses.append((http_status, payload, delay))

    def next_response(self):
        if self._responses:
            return self._responses.popleft()
        return 200, eip_envelope(), 0.0

    @property
    def calls(self):
        return len(self.requests)

    def start(self):
        self._httpd = _FakeEipHttpServer(('127.0.0.1', 0), _FakeEipHandler)
        self._httpd.eip_server = self
        self.url = 'http://127.0.0.1:%s' % self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._thread.join(timeout=5)
            self._httpd = None


class EipOrderCase(TransactionCase):
    """Base class of the order-push tests: pins the language, starts the
    fake platform and creates one integration config per test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = FakeEipServer()
        cls.server.start()
        cls.addClassCleanup(cls.server.stop)

    def setUp(self):
        super().setUp()
        # The DB admin speaks zh_CN while the assertions expect the
        # English source strings: pin the language for the test.
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.transport = self.env['sn.wsd.eip.transport']
        self.config = self.make_config()

    def make_config(self, **values):
        values.setdefault('supplier_code', 'SUP-1')
        values.setdefault('supplier_name', 'Supplier One')
        values.setdefault('base_url', self.server.url)
        return self.env['sn.wsd.eip.config'].create(values)

    def interface(self, code):
        return self.env['sn.wsd.eip.interface']._eip_interface(code)

    def last_request(self):
        return self.server.requests[-1]

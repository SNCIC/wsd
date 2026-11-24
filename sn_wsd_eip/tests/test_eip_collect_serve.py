"""Serving logic of the gateway fetch (ORM level).

The HTTP wire contract lives in ``test_eip_collect_wire``; the happy
path cannot run over HTTP inside a test because fixtures stay
uncommitted while the endpoint runs in its own transaction, so the
claim/deliver semantics are covered here against the same model methods
the controller calls.
"""

from odoo import fields
from odoo.tests import TransactionCase


class TestEipCollectServe(TransactionCase):
    """FIFO claim, delivery freeze and protocol guards of the outbox."""

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.Interface = self.env['sn.wsd.eip.collect.interface']
        self.Outbox = self.env['sn.wsd.eip.collect.outbox']
        self.PassRecord = self.env['sn.wsd.eip.pass.record']
        self.company = self.Interface._eip_main_company()
        self.config = self._ensure_config()
        self.supplier = self.config.supplier_code
        self.counter = 0

    def _ensure_config(self):
        """Serve needs the supplier identity: reuse the company config
        when the database already has one."""
        config = self.env['sn.wsd.eip.config'].search([
            ('company_id', '=', self.company.id),
            ('active', '=', True),
        ], limit=1)
        if config:
            return config
        return self.env['sn.wsd.eip.config'].create({
            'company_id': self.company.id,
            'supplier_code': 'SUP-1',
            'supplier_name': 'Supplier One',
            'base_url': 'http://127.0.0.1:9',
        })

    def _next_code(self):
        self.counter += 1
        return '%s' % self.counter

    def _source(self, **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', '1002')
        vals.setdefault('test_code', '1002-T%s' % self.counter)
        vals.setdefault('conclusion', 0)
        vals.setdefault('check_time', fields.Datetime.now())
        return self.PassRecord.create(vals)

    def _outbox(self, source, payload, **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('source_id', source.id)
        vals.setdefault('info_type_code', source.info_type_code)
        vals.setdefault('family', 'meter')
        vals.setdefault('test_code', source.test_code)
        vals.setdefault('payload', payload)
        return self.Outbox.create(vals)

    def test_10_serve_delivers_fifo(self):
        source1 = self._source()
        source2 = self._source()
        self._outbox(source1, {'TEST_CODE': 'T1'})
        self._outbox(source2, {'TEST_CODE': 'T2'})
        result = self.Interface._eip_serve('1002', 10)
        self.assertEqual(result['supplier_code'], self.supplier)
        self.assertEqual(result['data'], [{'TEST_CODE': 'T1'},
                                          {'TEST_CODE': 'T2'}])
        outbox_rows = self.Outbox.search([('info_type_code', '=', '1002')])
        self.assertEqual(set(outbox_rows.mapped('state')), {'delivered'})
        self.assertTrue(all(outbox_rows.mapped('delivered_time')))
        self.assertEqual(source1.state, 'delivered')
        self.assertEqual(source2.state, 'delivered')
        self.assertTrue(source1.upload_time and source2.upload_time)

    def test_20_amount_limits_the_claim(self):
        source1 = self._source()
        source2 = self._source()
        self._outbox(source1, {'N': 1})
        self._outbox(source2, {'N': 2})
        result = self.Interface._eip_serve('1002', 1)
        self.assertEqual(result['data'], [{'N': 1}])
        self.assertEqual(source2.state, 'pending')
        result = self.Interface._eip_serve('1002', 10)
        self.assertEqual(result['data'], [{'N': 2}])
        self.assertEqual(source2.state, 'delivered')

    def test_30_claim_never_repeats(self):
        source = self._source()
        self._outbox(source, {'N': 1})
        first = self.Interface._eip_serve('1002', 10)
        self.assertEqual(len(first['data']), 1)
        second = self.Interface._eip_serve('1002', 10)
        self.assertEqual(second['data'], [])

    def test_40_interface_guards(self):
        source = self._source()
        self._outbox(source, {'N': 1})
        # unknown code
        with self.assertRaises(Exception):
            self.Interface._eip_serve('9999', 10)
        # disabled code
        interface = self.Interface._eip_collect_interface('1002')
        interface.active = False
        with self.assertRaises(Exception):
            self.Interface._eip_serve('1002', 10)
        interface.active = True
        # nothing was claimed by the failed serves
        self.assertEqual(source.state, 'pending')

    def test_50_code_isolates_families(self):
        """A fetch of one code never returns rows of another interface:
        the 1xxx/2xxx namespaces are disjoint, family follows the code."""
        meter_source = self._source()
        collector_source = self._source(info_type_code='2002',
                                        test_code='2002-T1')
        self._outbox(meter_source, {'N': 1})
        self._outbox(collector_source, {'N': 2})
        result = self.Interface._eip_serve('1002', 10)
        self.assertEqual(result['data'], [{'N': 1}])
        self.assertEqual(collector_source.state, 'pending')

    def test_60_expansion_rows_freeze_the_source_once(self):
        """1007/1011 style expansion: several snapshots share one source;
        the delivery freeze writes the source exactly once."""
        source = self._source()
        self._outbox(source, {'TYPE': 'D1'})
        self._outbox(source, {'TYPE': 'D2'})
        result = self.Interface._eip_serve('1002', 10)
        self.assertEqual(len(result['data']), 2)
        self.assertEqual(source.state, 'delivered')
        self.assertTrue(source.upload_time)

    def test_70_delivered_source_stays_frozen_on_redelivery(self):
        """An already-delivered source is not rewritten by a second
        snapshot claim (upload_time keeps the first delivery stamp)."""
        source = self._source()
        self._outbox(source, {'TYPE': 'D1'})
        self.Interface._eip_serve('1002', 10)
        first_stamp = source.upload_time
        extra = self._outbox(source, {'TYPE': 'D2'})
        self.Interface._eip_serve('1002', 10)
        self.assertEqual(source.upload_time, first_stamp)
        self.assertEqual(extra.state, 'delivered')

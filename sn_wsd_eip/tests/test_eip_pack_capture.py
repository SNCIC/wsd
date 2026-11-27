"""Packing-storage capture from the nameplate SN bindings: the create
hook, the idempotent capture, the skipped unmapped SNs and the
by-work-order backfill wizard."""

from odoo.exceptions import UserError
from odoo.tests import tagged

from .eip_test_common import EipCaptureCase


@tagged('post_install', '-at_install')
class TestEipPackCapture(EipCaptureCase):

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.order = self._make_order_online()
        self.wcs = self._wcs()
        # the machine passed once: its latest pass carries the MES order
        self.machine = self._pass(self.order, self.wcs['a'], '210000000001', 'ok')
        self.Pack = self.env['sn.wsd.eip.pack.record']
        self.Binding = self.env['sn.wsd.serial.binding']
        # seeded/demo pack rows may exist: the assertions of this
        # class scope to its own nameplate range
        self._scope = [('nameplate_code', 'like', '2600000000')]

    def _map_meter(self):
        self.env['sn.wsd.eip.material.mapping'].create({
            'company_id': self.company.id,
            'material_code': 'DWG-EIP',
            'eip_material_code': 'D1',
            'subclass_id': self.env.ref('sn_wsd_eip.subclass_30002').id,
        })

    def _bind(self, nameplate):
        identity = self.env['sn.wsd.serial.identity'].get_or_create(
            nameplate, self.company, origin_type='external')
        return self.Binding.create({
            'serial_identity_id': identity.id,
            'bound_serial_identity_id': self.machine.id,
            'binding_type': 'nameplate',
            'source': 'api',
        })

    def test_10_unmapped_product_is_skipped(self):
        """No spec family mapping for the product: the binding creates
        no row (1090 vs 2090 cannot be decided) -- nothing is invented."""
        self._bind('260000000001')
        self.assertFalse(self.Pack.search(self._scope))

    def test_20_binding_creates_one_pending_row(self):
        self._map_meter()
        binding = self._bind('260000000001')
        row = self.Pack.search(self._scope)
        self.assertEqual(len(row), 1)
        self.assertEqual(row.binding_id, binding)
        self.assertEqual(row.info_type_code, '1090')
        self.assertEqual(row.nameplate_code, '260000000001')
        self.assertEqual(row.serial_identity_id, self.machine)
        self.assertEqual(row.production_order_no,
                         self.order.production_id.name)
        self.assertEqual(row.work_order_no, self.order.name)
        self.assertEqual(row.model_code, 'DDS102 220V 5(60)A')
        self.assertEqual((row.number, row.unit, row.state),
                         (1, '只', 'pending'))
        payload = row._eip_pack_payloads()[0]
        self.assertEqual(payload['INFO_TYPE_CODE'], '1090')
        self.assertEqual(payload['NAMEPLATE_CODE'], '260000000001')
        self.assertEqual(payload['STORAGE_TIME'],
                         row.storage_date.strftime('%Y-%m-%d'))

    def test_30_capture_is_idempotent(self):
        self._map_meter()
        binding = self._bind('260000000001')
        # the same binding captured again (backfill on top of the hook)
        self.assertFalse(self.Pack._eip_capture_from_bindings(binding))
        # a swapped nameplate is a new binding -> a second row
        self._bind('260000000002')
        self.assertEqual(self.Pack.search_count(self._scope), 2)

    def test_40_wizard_backfills_by_work_order(self):
        # bound while the product was unmapped: skipped by the hook
        self._bind('260000000001')
        self.assertEqual(self.Pack.search_count(self._scope), 0)
        with self.assertRaises(UserError):
            self.env['sn.wsd.eip.pack.capture.wizard'].create({
                'work_order_no': 'NO-SUCH-ORDER',
            }).action_capture()
        self._map_meter()
        wizard = self.env['sn.wsd.eip.pack.capture.wizard'].create({
            'work_order_no': self.order.name,
        })
        action = wizard.action_capture()
        self.assertEqual(self.Pack.search_count(self._scope), 1)
        self.assertEqual(action['domain'], [('id', 'in',
                                            self.Pack.search(
                                                self._scope).ids)])
        # a second run has nothing left to capture
        with self.assertRaises(UserError):
            self.env['sn.wsd.eip.pack.capture.wizard'].create({
                'work_order_no': self.order.name,
            }).action_capture()

from datetime import datetime

from odoo import fields
from odoo.tests import freeze_time, tagged

from . import eip_test_common


@tagged('post_install', '-at_install')
class TestEipExtract(eip_test_common.EipCaptureCase):
    """Buckets 2 (zone packets) and 3 (aging window): nearest-packet
    joins on the device chain, late-packet recompute, delivered freeze,
    and the built-in aging window rebuild."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # rewire the route for extraction tests: A = reflow (1009, entry),
        # B = aging (1011, exit); C stays unmapped and unused
        Mapping = cls.env['sn.wsd.eip.operation.mapping']
        Mapping.search([('info_code', '=', '1003')]).unlink()
        Mapping.create({'operation_id': cls.op_a.id, 'info_code': '1009'})
        cls.reflow_equipment = cls.env['sn.wsd.device.equipment'].create({
            'code': 'RF-ZONE-01', 'name': 'Reflow Zone Oven'})
        cls.aging_equipment = cls.env['sn.wsd.device.equipment'].create({
            'code': 'AGE-ZONE-01', 'name': 'Aging Room 1'})
        cls.aging_other = cls.env['sn.wsd.device.equipment'].create({
            'code': 'AGE-ZONE-02', 'name': 'Aging Room 2'})

    def _zone_mapping(self, eip_field, zone_name, code='1009'):
        return self.env['sn.wsd.eip.value.mapping'].create({
            'info_type_code': code,
            'eip_field': eip_field,
            'source_kind': 'device_zone',
            'source_key': zone_name,
        })

    def _push_reflow_packet(self, device_sn, collect_time, zones):
        return self.env['sn.wsd.device.reflow.record'].create({
            'device_sn': device_sn,
            'collect_time': collect_time,
            'zone_line_ids': [
                (0, 0, {'zone_name': name, 'temperature': value})
                for name, value in zones.items()],
        })

    def _push_aging_point(self, device_sn, collect_time, temperature):
        return self.env['sn.wsd.device.aging.record'].create({
            'device_sn': device_sn,
            'collect_time': collect_time,
            'temperature': temperature,
        })

    def _setup_order_wcs(self):
        order = self._make_order_online()
        wcs = self._wcs()
        Bridge = self.env['sn.wsd.workcenter.equipment']
        Bridge.create({'workcenter_id': wcs['a'].id,
                       'equipment_id': self.reflow_equipment.id})
        Bridge.create({'workcenter_id': wcs['b'].id,
                       'equipment_id': self.aging_equipment.id})
        return order, wcs

    # ------------------------------------------------------------------
    # bucket 2: zone packets
    # ------------------------------------------------------------------
    def test_10_zone_extraction(self):
        order, wcs = self._setup_order_wcs()
        self._zone_mapping('welding_zone', 'Z6')
        self._zone_mapping('warming_zone', 'Z1')
        self._zone_mapping('warming_zone', 'Z2')
        self._zone_mapping('cooling_zone', 'C1')
        # stale packet first, the covering packet later (nearest wins)
        self._push_reflow_packet('RF-ZONE-01', datetime(2026, 11, 2, 6, 0),
                                 {'Z6': 999.0})
        self._push_reflow_packet(
            'RF-ZONE-01', datetime(2026, 11, 2, 7, 0),
            {'Z6': 247.3, 'Z1': 100.0, 'Z2': 120.0, 'C1': 30.0})
        # a packet of another device must not leak in
        self._push_reflow_packet('RF-ZONE-99', datetime(2026, 11, 2, 7, 30),
                                 {'Z6': 111.0})
        with freeze_time(datetime(2026, 11, 2, 12, 0)):
            self._pass(order, wcs['a'], 'SN-EXT-001', 'ok')
        row = self._rows('SN-EXT-001')
        self.assertEqual(row.welding_zone, 247.3)
        # same field fed by several zones: max (cooling: min)
        self.assertEqual(row.warming_zone, 120.0)
        self.assertEqual(row.cooling_zone, 30.0)
        self.assertFalse(row.preheating_area)
        self.assertTrue(row.values_extracted)

    def test_11_zone_without_mapping_stays_empty(self):
        order, wcs = self._setup_order_wcs()
        self._push_reflow_packet('RF-ZONE-01', datetime(2026, 11, 2, 7, 0),
                                 {'Z6': 247.3})
        with freeze_time(datetime(2026, 11, 2, 12, 0)):
            self._pass(order, wcs['a'], 'SN-EXT-002', 'ok')
        row = self._rows('SN-EXT-002')
        self.assertFalse(row.welding_zone)
        self.assertFalse(row.values_extracted)

    def test_12_zone_late_packet_recompute_overwrite(self):
        order, wcs = self._setup_order_wcs()
        self._zone_mapping('welding_zone', 'Z6')
        self._push_reflow_packet('RF-ZONE-01', datetime(2026, 11, 2, 7, 0),
                                 {'Z6': 247.3})
        with freeze_time(datetime(2026, 11, 2, 12, 0)):
            self._pass(order, wcs['a'], 'SN-EXT-003', 'ok')
        row = self._rows('SN-EXT-003')
        self.assertEqual(row.welding_zone, 247.3)
        # the covering packet arrives after the pass: a later rerun takes
        # the now-nearest packet and overwrites (bucket 2 semantics)
        self._push_reflow_packet('RF-ZONE-01', datetime(2026, 11, 2, 11, 30),
                                 {'Z6': 250.1})
        row._apply_value_extraction()
        self.assertEqual(row.welding_zone, 250.1)

    def test_13_zone_delivered_frozen(self):
        order, wcs = self._setup_order_wcs()
        self._zone_mapping('welding_zone', 'Z6')
        self._push_reflow_packet('RF-ZONE-01', datetime(2026, 11, 2, 7, 0),
                                 {'Z6': 247.3})
        with freeze_time(datetime(2026, 11, 2, 12, 0)):
            self._pass(order, wcs['a'], 'SN-EXT-004', 'ok')
        row = self._rows('SN-EXT-004')
        row.state = 'delivered'
        self._push_reflow_packet('RF-ZONE-01', datetime(2026, 11, 2, 11, 30),
                                 {'Z6': 250.1})
        row._apply_value_extraction()
        self.assertEqual(row.welding_zone, 247.3)

    # ------------------------------------------------------------------
    # bucket 3: aging window points (walk A first: the route is linear
    # and skip-station is strict)
    # ------------------------------------------------------------------
    def _walk_to_aging(self, order, wcs, sn_name):
        with freeze_time(datetime(2026, 11, 2, 8, 0)):
            self._pass(order, wcs['a'], sn_name, 'ok')
            serial = order.scan_enter(sn_name, wcs['b'])
        return serial

    def _aging_row(self, sn_name):
        return self._rows(sn_name).filtered(
            lambda r: r.info_type_code == '1011')

    def test_20_aging_window_points(self):
        order, wcs = self._setup_order_wcs()
        self._push_aging_point('AGE-ZONE-01',
                               datetime(2026, 11, 2, 9, 0), 70.0)
        self._push_aging_point('AGE-ZONE-01',
                               datetime(2026, 11, 2, 11, 0), 72.0)
        # other room's points must not leak into the window
        self._push_aging_point('AGE-ZONE-02',
                               datetime(2026, 11, 2, 10, 0), 99.0)
        serial = self._walk_to_aging(order, wcs, 'SN-EXT-010')
        with freeze_time(datetime(2026, 11, 2, 16, 0)):
            order.leave_station(serial, 'ok')
        row = self._aging_row('SN-EXT-010')
        self.assertTrue(row)
        points = row.line_ids.filtered(
            lambda line: line.line_type == 'aging_point')
        self.assertEqual(len(points), 2)
        self.assertEqual(
            [p.point_time for p in points],
            [fields.Datetime.to_datetime(datetime(2026, 11, 2, 9, 0)),
             fields.Datetime.to_datetime(datetime(2026, 11, 2, 11, 0))])
        self.assertEqual(row.agingroom_temperature, 71.0)
        self.assertTrue(row.values_extracted)

    def test_21_aging_rebuild_idempotent_and_extending(self):
        order, wcs = self._setup_order_wcs()
        self._push_aging_point('AGE-ZONE-01',
                               datetime(2026, 11, 2, 9, 0), 70.0)
        serial = self._walk_to_aging(order, wcs, 'SN-EXT-011')
        with freeze_time(datetime(2026, 11, 2, 16, 0)):
            order.leave_station(serial, 'ok')
        row = self._aging_row('SN-EXT-011')
        self.assertEqual(len(row.line_ids), 1)
        self.assertEqual(row.agingroom_temperature, 70.0)
        # late points arrive: the rebuild takes the fuller window without
        # accumulating duplicates (delete-then-recreate)
        self._push_aging_point('AGE-ZONE-01',
                               datetime(2026, 11, 2, 15, 0), 74.0)
        row._apply_value_extraction()
        self.assertEqual(len(row.line_ids), 2)
        self.assertEqual(row.agingroom_temperature, 72.0)
        row._apply_value_extraction()
        self.assertEqual(len(row.line_ids), 2)

    def test_22_aging_no_points(self):
        order, wcs = self._setup_order_wcs()
        serial = self._walk_to_aging(order, wcs, 'SN-EXT-012')
        with freeze_time(datetime(2026, 11, 2, 16, 0)):
            order.leave_station(serial, 'ok')
        row = self._aging_row('SN-EXT-012')
        self.assertTrue(row)
        self.assertFalse(row.line_ids)
        self.assertEqual(row.agingroom_temperature, 0.0)

    def test_23_aging_delivered_frozen(self):
        order, wcs = self._setup_order_wcs()
        self._push_aging_point('AGE-ZONE-01',
                               datetime(2026, 11, 2, 9, 0), 70.0)
        serial = self._walk_to_aging(order, wcs, 'SN-EXT-013')
        with freeze_time(datetime(2026, 11, 2, 16, 0)):
            order.leave_station(serial, 'ok')
        row = self._aging_row('SN-EXT-013')
        row.state = 'delivered'
        self._push_aging_point('AGE-ZONE-01',
                               datetime(2026, 11, 2, 15, 0), 74.0)
        row._apply_value_extraction()
        self.assertEqual(len(row.line_ids), 1)
        self.assertEqual(row.agingroom_temperature, 70.0)

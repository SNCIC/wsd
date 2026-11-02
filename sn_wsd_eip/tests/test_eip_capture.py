from . import eip_test_common


class TestEipCapture(eip_test_common.EipCaptureCase):
    """Phase-1 capture: rows are born in the pass transaction with the
    common EIP fields; scrap and unmapped operations produce nothing."""

    def test_10_ok_pass_row_and_fields(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], 'SN-EIP-001', 'ok')
        rows = self._rows('SN-EIP-001')
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.info_type_code, '1003')
        self.assertEqual(row.conclusion, 0)
        self.assertEqual(row.pcb_code, 'SN-EIP-001')
        self.assertEqual(row.test_name, 'EIP-FCT')
        self.assertEqual(row.work_order_no, order.name)
        self.assertEqual(row.production_order_no,
                         order.production_id.name)
        self.assertEqual(row.model_code, 'DDS102 220V 5(60)A')
        self.assertTrue(row.test_code.startswith('1003-'))
        self.assertTrue(row.check_time)
        self.assertEqual(row.state, 'pending')
        self.assertFalse(row.upload_time)
        self.assertEqual(row.standard_version, 2)
        # terminal channel: no report device, chain falls back to the
        # work-center code
        self.assertEqual(row.device_no, wcs['a'].code)

    def test_11_ng_pass(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], 'SN-EIP-002', 'ng')
        row = self._rows('SN-EIP-002')
        self.assertEqual(len(row), 1)
        self.assertEqual(row.conclusion, 1)

    def test_20_retest_two_rows(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], 'SN-EIP-003', 'ng')
        self._pass(order, wcs['a'], 'SN-EIP-003', 'ok')
        rows = self._rows('SN-EIP-003')
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(rows.mapped('conclusion')), [0, 1])
        codes = rows.mapped('test_code')
        self.assertEqual(len(set(codes)), 2)
        # aging interface rows carry no PCB identity (spec has none)
        self._pass(order, wcs['b'], 'SN-EIP-003', 'ok')
        aging = self._rows('SN-EIP-003').filtered(
            lambda r: r.info_type_code == '1011')
        self.assertEqual(len(aging), 1)
        self.assertFalse(aging.pcb_code)

    def test_30_scrap_not_collected(self):
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('SN-EIP-004', wcs['a'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial.id),
            ('result', '=', 'in_progress')], limit=1)
        self.assertTrue(history)
        # scrap is not a test verdict: the hook must not collect it
        history.write({'result': 'scrap', 'out_date': history.in_date})
        self.assertFalse(self._rows('SN-EIP-004'))

    def test_40_unmapped_operation_not_collected(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], 'SN-EIP-005', 'ok')
        self._pass(order, wcs['b'], 'SN-EIP-005', 'ok')
        self._pass(order, wcs['c'], 'SN-EIP-005', 'ok')
        rows = self._rows('SN-EIP-005')
        self.assertEqual(sorted(rows.mapped('info_type_code')),
                         ['1003', '1011'])

    def test_50_device_chain_equipment(self):
        order = self._make_order_online()
        wcs = self._wcs()
        equipment = self.env['sn.wsd.device.equipment'].create({
            'code': 'RF-EIP-01', 'name': 'Reflow Oven 1'})
        self.env['sn.wsd.workcenter.equipment'].create({
            'workcenter_id': wcs['a'].id, 'equipment_id': equipment.id})
        self._pass(order, wcs['a'], 'SN-EIP-006', 'ok')
        row = self._rows('SN-EIP-006')
        self.assertEqual(row.device_no, 'RF-EIP-01')
        self.assertEqual(row.equipment_id, equipment)

    def test_60_clear_pass_keeps_row(self):
        order = self._make_order_online()
        wcs = self._wcs()
        serial = self._pass(order, wcs['a'], 'SN-EIP-007', 'ok')
        row = self._rows('SN-EIP-007')
        self.assertEqual(len(row), 1)
        order.action_clear_station_pass(serial)
        row.invalidate_recordset()
        self.assertTrue(row.exists())
        self.assertFalse(row.history_id)
        # snapshots survive the anchor drop
        self.assertEqual(row.sn_name, 'SN-EIP-007')
        self.assertEqual(row.work_order_no, order.name)
        self.assertEqual(row.conclusion, 0)

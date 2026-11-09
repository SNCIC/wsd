from . import eip_test_common


class TestEipDetailExtract(eip_test_common.EipCaptureCase):
    """Bucket 1 (test detail items) + phase-2 enrichment: the report
    channel lands its test result after the pass; linking backfills
    test_result_id, refreshes the device chain (report device first)
    and extracts mapped detail values fill-empty."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # rewire op_a to a value-bearing detail interface: 1002
        Mapping = cls.env['sn.wsd.eip.operation.mapping']
        Mapping.search([('info_code', '=', '1003')]).unlink()
        Mapping.create({'operation_id': cls.op_a.id, 'info_code': '1002'})
        cls.report_equipment = cls.env['sn.wsd.device.equipment'].create({
            'code': 'HV-REPORT-01', 'name': 'Hipot Tester 1'})
        cls.wc_equipment = cls.env['sn.wsd.device.equipment'].create({
            'code': 'HV-WC-01', 'name': 'Hipot Station Device'})

    def _detail_mapping(self, eip_field, project_name):
        return self.env['sn.wsd.eip.value.mapping'].create({
            'info_type_code': '1002',
            'eip_field': eip_field,
            'source_kind': 'detail_item',
            'source_key': project_name,
        })

    def _ingest_report(self, order, serial, details, equipment=False):
        rop = order.x_mes_route_id.operation_ids.filtered(
            lambda op: op.operation_id == self.op_a)
        result = self.env['sn.wsd.mes.test.result'].create({
            'serial_identity_id': serial.id,
            'result': 'ok',
            'test_type': 'final_test',
            'mes_order_id': order.id,
            'route_operation_id': rop.id,
            'equipment_id': equipment.id if equipment else False,
        })
        self.env['sn.wsd.mes.test.result.detail'].create([{
            'test_result_id': result.id,
            'sequence': index,
            'project_name': name,
            'actual_value': value,
            'result': 'ok',
        } for index, (name, value) in enumerate(details, start=1)])
        return result

    def test_30_link_and_extract(self):
        order = self._make_order_online()
        wcs = self._wcs()
        Bridge = self.env['sn.wsd.workcenter.equipment']
        Bridge.create({'workcenter_id': wcs['a'].id,
                       'equipment_id': self.wc_equipment.id})
        self._detail_mapping('leakage_current', 'Leakage Current')
        self._detail_mapping('check_duration', 'Duration')
        self._detail_mapping('testing_voltage', 'Voltage')
        serial = self._pass(order, wcs['a'], '126100000001', 'ok')
        row = self._rows('126100000001')
        # phase 1: chain level 2 (work-center equipment)
        self.assertEqual(row.device_no, 'HV-WC-01')
        # phase 2: report lands later with its own device
        self._ingest_report(
            order, serial,
            [('Leakage Current', '2.05'), ('Duration', '60'),
             ('Voltage', '4200')],
            equipment=self.report_equipment)
        row.invalidate_recordset()
        self.assertTrue(row.test_result_id)
        self.assertEqual(row.device_no, 'HV-REPORT-01')
        self.assertEqual(row.equipment_id, self.report_equipment)
        self.assertEqual(row.leakage_current, 2.05)
        self.assertEqual(row.check_duration, '60')
        self.assertEqual(row.testing_voltage, '4200')
        # detail snapshot lines landed once
        details = row.line_ids.filtered(
            lambda line: line.line_type == 'test_detail')
        self.assertEqual(len(details), 3)
        self.assertTrue(row.values_extracted)

    def test_31_without_mapping_stays_empty(self):
        order = self._make_order_online()
        wcs = self._wcs()
        serial = self._pass(order, wcs['a'], '126100000002', 'ok')
        row = self._rows('126100000002')
        self.assertFalse(row.test_result_id)
        self._ingest_report(order, serial, [('Leakage Current', '2.05')])
        row.invalidate_recordset()
        self.assertTrue(row.test_result_id)
        self.assertFalse(row.leakage_current)

    def test_32_missing_project_left_empty(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._detail_mapping('leakage_current', 'Leakage Current')
        serial = self._pass(order, wcs['a'], '126100000003', 'ok')
        self._ingest_report(order, serial, [('Other Item', '1.0')])
        row = self._rows('126100000003')
        self.assertTrue(row.test_result_id)
        self.assertFalse(row.leakage_current)

    def test_33_unparsable_number_skipped(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._detail_mapping('leakage_current', 'Leakage Current')
        serial = self._pass(order, wcs['a'], '126100000004', 'ok')
        self._ingest_report(order, serial, [('Leakage Current', 'n/a')])
        row = self._rows('126100000004')
        self.assertFalse(row.leakage_current)

    def test_34_fill_empty_never_overwrites(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._detail_mapping('leakage_current', 'Leakage Current')
        serial = self._pass(order, wcs['a'], '126100000005', 'ok')
        row = self._rows('126100000005')
        row.leakage_current = 9.9
        self._ingest_report(order, serial, [('Leakage Current', '2.05')])
        row.invalidate_recordset()
        self.assertEqual(row.leakage_current, 9.9)

    def test_35_cron_idempotent_and_delivered_frozen(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._detail_mapping('leakage_current', 'Leakage Current')
        serial = self._pass(order, wcs['a'], '126100000006', 'ok')
        self._ingest_report(order, serial, [('Leakage Current', '2.05')])
        row = self._rows('126100000006')
        self.assertEqual(row.leakage_current, 2.05)
        # re-running the cron changes nothing
        self.env['sn.wsd.eip.pass.record']._cron_backfill_pending_values()
        row.invalidate_recordset()
        self.assertEqual(row.leakage_current, 2.05)
        self.assertEqual(len(row.line_ids.filtered(
            lambda line: line.line_type == 'test_detail')), 1)
        # delivered rows are frozen
        row.state = 'delivered'
        row.leakage_current = 0.0
        self.env['sn.wsd.eip.pass.record']._cron_backfill_pending_values()
        row.invalidate_recordset()
        self.assertFalse(row.leakage_current)

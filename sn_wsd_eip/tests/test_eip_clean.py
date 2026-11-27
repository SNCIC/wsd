"""Cleansing engine tests: the three gates, payload synthesis, the
expansion interfaces, the state machine (supersede / freeze), manual
corrections and the cron sweep."""

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase



class TestEipClean(TransactionCase):
    """Judge-and-snapshot behavior of sn.wsd.eip.pass.record."""

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.env['sn.wsd.eip.collect.outbox'].search([]).unlink()
        self.PassRecord = self.env['sn.wsd.eip.pass.record']
        self.Outbox = self.env['sn.wsd.eip.collect.outbox']
        self.Rule = self.env['sn.wsd.eip.clean.rule']
        self.company = self.env['res.company'].search(
            [], order='id asc', limit=1)
        self.config = self._ensure_config()
        self.counter = 0

    def _ensure_config(self):
        config = self.env['sn.wsd.eip.config'].search([
            ('company_id', '=', self.company.id),
            ('active', '=', True)], limit=1)
        if config:
            return config
        return self.env['sn.wsd.eip.config'].create({
            'company_id': self.company.id,
            'supplier_code': 'SUP-1',
            'supplier_name': 'Supplier One',
            'base_url': 'http://127.0.0.1:9',
        })

    def _source(self, code='1002', **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', code)
        vals.setdefault('test_code', '%s-T%s' % (code, self.counter))
        vals.setdefault('conclusion', 0)
        vals.setdefault('check_time', fields.Datetime.now())
        vals.setdefault('device_no', 'DX01')
        vals.setdefault('model_code', 'DDSY10217')
        vals.setdefault('pcb_code', 'SN001' + str(self.counter))
        vals.setdefault('production_order_no', 'MO001')
        vals.setdefault('work_order_no', 'W001')
        vals.setdefault('test_name', 'Withstand Voltage Test')
        return self.PassRecord.create(vals)

    def _full_1002(self):
        return self._source(
            check_duration='60', testing_voltage='4200',
            leakage_current=2.0)

    def test_10_required_gate_rejects(self):
        row = self._source()  # no 1002 value columns at all
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertIn('testing_voltage', row.clean_note)
        self.assertIn('leakage_current', row.clean_note)
        self.assertFalse(row.outbox_ids)
        self.assertTrue(row.clean_time)

    def test_20_pass_qualifies_and_snapshots(self):
        row = self._full_1002()
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        self.assertFalse(row.clean_note)
        snapshot = row.outbox_ids
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot.state, 'qualified')
        payload = snapshot.payload
        self.assertEqual(payload['STANDARD_VERSION'], 2)
        self.assertEqual(payload['TEST_CODE'], row.test_code)
        self.assertEqual(payload['TESTING_VOLTAGE'], '4200')
        self.assertEqual(payload['LEAKAGE_CURRENT'], 2.0)
        self.assertEqual(payload['CHECK_DURATION'], '60')
        self.assertEqual(payload['CONCLUSION'], 0)
        self.assertIn('PCB_CODE', payload)
        # dates ship in the spec format, UPLOAD_TIME = the clean stamp
        self.assertEqual(payload['CHECK_TIME'],
                         row.check_time.strftime('%Y-%m-%d %H:%M:%S'))
        self.assertEqual(payload['UPLOAD_TIME'],
                         row.clean_time.strftime('%Y-%m-%d %H:%M:%S'))

    def test_30_limit_gate(self):
        self.Rule.search([
            ('company_id', '=', self.company.id),
            ('info_type_code', '=', '1005')]).unlink()  # seed data may hold one
        self.Rule.create({
            'company_id': self.company.id,
            'info_type_code': '1005',
            'field_name': 'current_value',
            'lower_limit': 0.0,
            'upper_limit': 50.0,
        })
        out = self._source(code='1005', current_value=60.0,
                           pcb_code='SN1005', test_name='Battery Current')
        out._eip_clean_rows()
        self.assertEqual(out.state, 'rejected')
        self.assertIn('current_value', out.clean_note)
        ok = self._source(code='1005', current_value=30.0,
                          pcb_code='SN1005b', test_name='Battery Current')
        ok._eip_clean_rows()
        self.assertEqual(ok.state, 'qualified')

    def test_40_recleaned_stale_snapshots_are_deleted(self):
        row = self._full_1002()
        row._eip_clean_rows()
        first = row.outbox_ids
        # the raw column keeps its value; a failing re-judgement flips
        # the row and deletes the stale (undelivered) snapshot
        row.write({'conclusion': 1})
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertFalse(first.exists())
        self.assertFalse(row.outbox_ids)

    # ------------------------------------------------------------------
    # re-serve (user decision 2026-11-27): re-queue delivered snapshots
    # of one work order + interface, same payload, sources ride along
    # ------------------------------------------------------------------
    def test_60_re_serve_flips_delivered(self):
        row = self._full_1002()
        row._eip_clean_rows()
        snapshot = row.outbox_ids
        snapshot.write({'state': 'delivered',
                        'delivered_time': fields.Datetime.now()})
        row.write({'state': 'delivered',
                   'upload_time': fields.Datetime.now()})
        wizard = self.env['sn.wsd.eip.reserve.wizard'].create({
            'work_order_no': 'W001', 'info_type_code': '1002'})
        wizard.action_re_serve()
        self.assertEqual(snapshot.state, 'qualified')
        self.assertFalse(snapshot.delivered_time)
        self.assertEqual(row.state, 'qualified')
        self.assertFalse(row.upload_time)

    def test_61_re_serve_scopes_by_work_order_and_code(self):
        row_a = self._full_1002()
        row_a._eip_clean_rows()
        row_a.outbox_ids.write({'state': 'delivered'})
        row_b = self._source(code='1005', current_value=30.0,
                             work_order_no='W002')
        row_b._eip_clean_rows()
        row_b.outbox_ids.write({'state': 'delivered'})
        row_b.write({'state': 'delivered'})
        row_c = self._full_1002()
        row_c._eip_clean_rows()  # qualified, not delivered
        wizard = self.env['sn.wsd.eip.reserve.wizard'].create({
            'work_order_no': 'W001', 'info_type_code': '1002'})
        wizard.action_re_serve()
        # only the delivered 1002/W001 slice flipped
        self.assertEqual(row_a.state, 'qualified')
        self.assertEqual(row_b.state, 'delivered')
        self.assertEqual(row_c.state, 'qualified')
        self.assertEqual(
            row_b.outbox_ids.mapped('state'), ['delivered'])

    def test_62_re_serve_without_delivered_raises(self):
        wizard = self.env['sn.wsd.eip.reserve.wizard'].create({
            'work_order_no': 'W-MISSING', 'info_type_code': '1002'})
        with self.assertRaises(UserError):
            wizard.action_re_serve()

    def test_63_wizard_prefills_from_selection(self):
        row = self._full_1002()
        row._eip_clean_rows()
        defaults = self.env['sn.wsd.eip.reserve.wizard'].with_context(
            active_ids=row.outbox_ids.ids).default_get(
                ['work_order_no', 'info_type_code'])
        self.assertEqual(defaults.get('work_order_no'), 'W001')
        self.assertEqual(defaults.get('info_type_code'), '1002')

    def test_50_error_detail_expansion(self):
        row = self._source(code='1007')
        self.env['sn.wsd.eip.pass.record.line'].create([
            {'record_id': row.id, 'line_type': 'test_detail',
             'project_name': '正向-有功-C相-Imax1.0', 'actual_value': '-0.022'},
            {'record_id': row.id, 'line_type': 'test_detail',
             'project_name': '无法识别的项目', 'actual_value': '0.01'},
        ])
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payloads = row.outbox_ids.mapped('payload')
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]['AVERAGE_ERROR_TYPE'], 'C1')
        self.assertEqual(payloads[0]['AVERAGE_ERROR'], -0.022)
        self.assertEqual(payloads[0]['TEST_NAME'], '正向-有功-C相-Imax1.0')

    def test_51_error_detail_without_valid_lines_rejects(self):
        row = self._source(code='1007')
        self.env['sn.wsd.eip.pass.record.line'].create([{
            'record_id': row.id, 'line_type': 'test_detail',
            'project_name': '无法识别的项目', 'actual_value': '0.01'}])
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertIn('no valid error-detail lines', row.clean_note)

    def test_60_aging_expansion(self):
        row = self._source(code='1011', pcb_code=False,
                           standard_value=65.0)
        self.env['sn.wsd.eip.pass.record.line'].create([
            {'record_id': row.id, 'line_type': 'aging_point',
             'point_time': row.check_time, 'actual_value': '70.0'},
            {'record_id': row.id, 'line_type': 'aging_point',
             'point_time': row.check_time, 'actual_value': '71.5'},
        ])
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payloads = row.outbox_ids.mapped('payload')
        self.assertEqual(len(payloads), 2)
        self.assertEqual(
            sorted(item['AGINGROOM_TEMPERATURE'] for item in payloads),
            [70.0, 71.5])
        self.assertTrue(
            all(item['STANDARD_VALUE'] == 65.0 for item in payloads))
        self.assertTrue(
            all('PCB_CODE' not in item for item in payloads))

    def test_61_aging_without_points_rejects(self):
        row = self._source(code='1011', pcb_code=False)
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertIn('no aging temperature points', row.clean_note)

    def test_70_delivered_rows_are_frozen(self):
        row = self._full_1002()
        row._eip_clean_rows()
        claimed = self.Outbox._eip_claim('1002', 10)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(row.state, 'delivered')
        row._eip_clean_rows()
        self.assertEqual(row.state, 'delivered')
        self.assertEqual(len(row.outbox_ids), 1)

    def test_80_archive_correction_flows_into_the_payload(self):
        row = self._source(
            code='1008', software_version='V1.0', plant_code='P001',
            table_no='000687348053', table_address='000687348053',
            asset_management_no='3730001000000687348053')  # nameplate missing
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.env['sn.wsd.eip.clean.fix.wizard'].with_context(
            active_ids=[row.id]).create({
            'field_name': 'nameplate_code',
            'value': '3730001000000687348014',
            'basis': 'grid-issued list',
        }).action_apply()
        self.assertEqual(row.state, 'qualified')
        fix = row.fix_ids
        self.assertEqual(len(fix), 1)
        self.assertEqual(fix.original_value, '')
        self.assertEqual(fix.basis, 'grid-issued list')
        self.assertEqual(row.nameplate_code, False)  # raw untouched
        payload = row.outbox_ids.payload
        self.assertEqual(payload['NAMEPLATE_CODE'],
                         '3730001000000687348014')

    def test_805_correction_wizard_opener(self):
        """The Correct button opener: server-built context, scoped to
        the row."""
        row = self._source()
        action = row.action_open_correction_wizard()
        self.assertEqual(action['res_model'], 'sn.wsd.eip.clean.fix.wizard')
        self.assertEqual(action['context']['default_record_ids'],
                         str(row.id))

    def test_81_measured_values_are_not_correctable(self):
        row = self._full_1002()
        with self.assertRaises(UserError):
            self.env['sn.wsd.eip.clean.fix'].create({
                'source_id': row.id,
                'field_name': 'testing_voltage',
                'value': '4400',
                'basis': 'nope',
            })

    def test_82_re_clean_by_work_order(self):
        """The single cleansing trigger: type a work order number --
        everything of that order is judged, other orders untouched."""
        row = self._full_1002()
        broken = self._source()  # same order W001, missing fields
        other = self._full_1002()
        other.work_order_no = 'W002'
        result = self.env['sn.wsd.eip.clean.order.wizard'].create({
            'work_order_no': 'W001',
        }).action_re_clean()
        # closes the dialog and nothing else: the result goes out as a
        # bus toast (the webclient does not handle an action 'effect')
        self.assertEqual(result, {'type': 'ir.actions.act_window_close'})
        self.assertEqual(row.state, 'qualified')
        self.assertEqual(broken.state, 'rejected')
        self.assertEqual(other.state, 'pending')
        with self.assertRaises(UserError):
            self.env['sn.wsd.eip.clean.order.wizard'].create({
                'work_order_no': 'NOPE',
            }).action_re_clean()

    def test_90_family_resolution(self):
        product = self.env['product.product'].create({
            'name': 'Meter A', 'default_code': 'MTR-A'})
        self.assertEqual(
            self.PassRecord._eip_resolve_family(product, self.company),
            False)
        self.env['sn.wsd.eip.material.mapping'].create({
            'company_id': self.company.id,
            'eip_material_code': 'EIP-MTR-A',
            'material_code': 'MTR-A',
            'subclass_id': self.env.ref('sn_wsd_eip.subclass_30002').id,
        })
        self.assertEqual(
            self.PassRecord._eip_resolve_family(product, self.company),
            'meter')
        product.default_code = 'MTR-A2'
        mapping = self.env['sn.wsd.eip.material.mapping'].create({
            'company_id': self.company.id,
            'eip_material_code': 'EIP-MTR-A2',
            'material_code': 'MTR-A2',
            'subclass_id': self.env.ref('sn_wsd_eip.subclass_30001').id,
        })
        self.assertEqual(
            self.PassRecord._eip_resolve_family(product, self.company),
            'collector')
        mapping.subclass_id = self.env.ref('sn_wsd_eip.subclass_30003').id
        self.assertEqual(
            self.PassRecord._eip_resolve_family(product, self.company),
            False)

    def test_200_collector_codes_serve_their_own_family(self):
        row = self._source(code='2002', spec_family='collector',
                           test_name=False)
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payload = row.outbox_ids.payload
        self.assertNotIn('TEST_NAME', payload)
        self.assertEqual(row.outbox_ids.family, 'collector')
        serve = self.env['sn.wsd.eip.collect.interface']._eip_serve
        self.assertEqual(serve('2002', 10)['data'], [payload])
        self.assertEqual(serve('1002', 10)['data'], [])

    def test_210_ac_analog_expansion(self):
        row = self._source(code='2006', spec_family='collector',
                           standard_value=220.0, error_value=0.01)
        self.env['sn.wsd.eip.pass.record.line'].create([
            {'record_id': row.id, 'line_type': 'test_detail',
             'project_name': '交流模拟量采集A相', 'actual_value': '220.0'},
            {'record_id': row.id, 'line_type': 'test_detail',
             'project_name': '交流模拟量采集B相', 'actual_value': '219.9'},
        ])
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payloads = row.outbox_ids.mapped('payload')
        self.assertEqual(len(payloads), 2)
        self.assertEqual(
            sorted(item['AVERAGE_ERROR_TYPE'] for item in payloads),
            ['ⅠA', 'ⅠB'])
        self.assertTrue(all(
            item['STANDARD_VALUE'] == 220.0 and item['ERROR_VALUE'] == 0.01
            for item in payloads))

    def test_220_parameter_query_fields(self):
        row = self._source(code='2004', spec_family='collector',
                           plant_code='C001', logic_address='123456789012',
                           bureau_num='12343546576878644')
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payload = row.outbox_ids.payload
        self.assertEqual(payload['LOGIC_ADDRESS'], '123456789012')
        self.assertEqual(payload['BUREAU_NUM'], '12343546576878644')
        missing = self._source(code='2004', spec_family='collector',
                               plant_code='C001')
        missing._eip_clean_rows()
        self.assertEqual(missing.state, 'rejected')
        self.assertIn('logic_address', missing.clean_note)

    def test_230_value_mapping_field_guard(self):
        self.env['sn.wsd.eip.value.mapping'].create({
            'company_id': self.company.id,
            'info_type_code': '2006',
            'eip_field': 'measured_value',
            'source_kind': 'detail_item',
            'source_key': '交流模拟量采集A相',
        })
        with self.assertRaises(Exception):
            self.env['sn.wsd.eip.value.mapping'].create({
                'company_id': self.company.id,
                'info_type_code': '2006',
                'eip_field': 'testing_voltage',
                'source_kind': 'detail_item',
                'source_key': '交流模拟量采集A相',
            })

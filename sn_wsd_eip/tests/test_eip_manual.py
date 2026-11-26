"""Manual-entry interfaces (raw material inspection, packing/shipping)
plus the raw-material report file interface: end-to-end flows through
the shared cleansing / serving machinery."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestEipManual(TransactionCase):
    """Single-table manual entry -> gates -> snapshot -> serve."""

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.env['sn.wsd.eip.collect.outbox'].search([]).unlink()
        self.company = self.env['res.company'].search(
            [], order='id asc', limit=1)
        self.PassRecord = self.env['sn.wsd.eip.pass.record']
        self.Outbox = self.env['sn.wsd.eip.collect.outbox']
        self.Interface = self.env['sn.wsd.eip.collect.interface']
        self.config = self._ensure_config()

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

    def _raw(self, code='1012', **vals):
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', code)
        vals.setdefault('test_code', '%s-M1' % code)
        vals.setdefault('work_order_no', 'W-MANUAL')
        vals.setdefault('production_order_no', 'MO-M1')
        vals.setdefault('material_check_batch', 'JC20251126')
        vals.setdefault('material_batch', 'PC20251126')
        vals.setdefault('material_brand', 'Brand X')
        vals.setdefault('material_supplier', 'Maker Y')
        vals.setdefault('material_leave_date', '2025-11-01')
        vals.setdefault('incoming_check_date', '2025-11-03')
        vals.setdefault('model_code', 'RV-01')
        vals.setdefault('check_time', '2025-11-26 09:00:00')
        vals.setdefault('conclusion', 0)
        if code == '1012':
            vals.setdefault('varistor_voltage', 390.5)
            vals.setdefault('error_value', 1.2)
        if code == '1015':
            vals.setdefault('leakage_current', 2.0)
        return self.PassRecord.create(vals)

    def test_10_raw_inspection_end_to_end(self):
        """1012 manual row: gates pass, EXACT spec payload, served."""
        row = self._raw()
        self.PassRecord._eip_clean_by_order('W-MANUAL')
        self.assertEqual(row.state, 'qualified')
        snapshot = row.outbox_ids
        self.assertEqual(snapshot.info_type_code, '1012')
        payload = snapshot.payload
        # exact field list: no DEVICE_NO / PCB_CODE / TEST_NAME
        self.assertNotIn('DEVICE_NO', payload)
        self.assertNotIn('PCB_CODE', payload)
        self.assertEqual(payload['MATERIAL_CHECK_BATCH'], 'JC20251126')
        self.assertEqual(payload['MATERIAL_BRAND'], 'Brand X')
        self.assertEqual(payload['VARISTOR_VOLTAGE'], 390.5)
        self.assertEqual(payload['ERROR_VALUE'], 1.2)
        self.assertEqual(payload['CONCLUSION'], 0)
        result = self.Interface._eip_serve('1012', 10)
        self.assertEqual(result['data'], [payload])
        self.assertEqual(row.state, 'delivered')

    def test_20_raw_missing_batch_rejects(self):
        row = self._raw(code='1015', leakage_current=2.0)
        row.material_check_batch = False
        self.PassRecord._eip_clean_by_order('W-MANUAL')
        self.assertEqual(row.state, 'rejected')
        self.assertIn('material_check_batch', row.clean_note)

    def test_30_packing_entry_flow(self):
        """Packing storage: one record per unit, exact spec payload,
        served FIFO by the 1090 interface."""
        Pack = self.env['sn.wsd.eip.pack.record']
        pack = Pack.create({
            'company_id': self.company.id,
            'info_type_code': '1090',
            'production_order_no': 'MO-M1',
            'work_order_no': 'W-MANUAL',
            'test_code': 'IN-001',
            'model_code': 'DDSY10217',
            'nameplate_code': 'NP-1',
            'number': 1,
            'unit': '只',
            'storage_date': '2025-11-26',
        })
        self.Interface._eip_serve('1090', 10)
        self.assertEqual(pack.state, 'delivered')
        self.assertTrue(pack.delivered_time)
        payload = pack._eip_pack_payloads()[0]
        self.assertEqual(payload['NAMEPLATE_CODE'], 'NP-1')
        self.assertEqual(payload['NUMBER'], 1)
        self.assertEqual(payload['STORAGE_TIME'], '2025-11-26')
        # FIFO exhausted
        self.assertEqual(self.Interface._eip_serve('1090', 10)['data'], [])

    def test_31_shipping_flow(self):
        """Shipping: one record per batch, a continuous nameplate
        range, no CONCLUSION field in the payload (spec field table)."""
        Ship = self.env['sn.wsd.eip.ship.record']
        ship = Ship.create({
            'company_id': self.company.id,
            'info_type_code': '1091',
            'production_order_no': 'MO-M1',
            'work_order_no': 'W-MANUAL',
            'test_code': 'SH-001',
            'model_code': 'DDSY10217',
            'nameplate_start': 'NP-001',
            'nameplate_final': 'NP-100',
            'number': 100,
            'unit': '只',
            'deliver_date': '2025-11-27',
            'deliver_status': '1',
        })
        self.Interface._eip_serve('1091', 10)
        self.assertEqual(ship.state, 'delivered')
        payload = ship._eip_ship_payloads()[0]
        self.assertEqual(payload['NAMEPLATE_CODE_START'], 'NP-001')
        self.assertEqual(payload['NAMEPLATE_CODE_FINAL'], 'NP-100')
        self.assertEqual(payload['NUMBER'], 100)
        self.assertNotIn('CONCLUSION', payload)

    def test_40_delivered_rows_are_frozen_against_manual_edit(self):
        row = self._raw()
        self.PassRecord._eip_clean_by_order('W-MANUAL')
        self.Interface._eip_serve('1012', 10)
        self.assertEqual(row.state, 'delivered')
        with self.assertRaises(UserError):
            row.write({'material_brand': 'Rewrite'})
        # the delivery stamp itself is always allowed
        row.write({'upload_time': fields.Datetime.now()})

    def test_50_raw_report_flow(self):
        Report = self.env['sn.wsd.eip.raw.report']
        self.config.write({'collect_base_url': 'http://192.168.1.13:8069'})
        report = Report.create({
            'company_id': self.company.id,
            'production_order_no': 'MO-M1',
            'procedure_code': '1012',
            'test_code': 'RPT-001',
            'test_file_type': '1',
            'material_check_batch': 'JC20251126',
            'material_batch': 'PC20251126',
        })
        self.assertEqual(report.family, 'meter')
        import base64
        att = self.env['ir.attachment'].create({
            'name': 'JC20251126-report.pdf',
            'datas': base64.b64encode(b'%PDF-report'),
            'type': 'binary',
        })
        report.write({'attachment_ids': [(4, att.id)]})
        result = self.Interface._eip_serve('M-REPORT', 10)
        self.assertEqual(len(result['data']), 1)
        payload = result['data'][0]
        self.assertEqual(payload['procedureCode'], '1012')
        file_entry = payload['fileArray'][0]
        self.assertEqual(file_entry['testFileType'], 1)
        self.assertIn('/web/content/', file_entry['fileUrl'])
        self.assertIn('download=True', file_entry['fileUrl'])
        self.assertEqual(report.state, 'delivered')
        self.assertTrue(report.delivered_time)
        # FIFO exhausted
        self.assertEqual(self.Interface._eip_serve('M-REPORT', 10)['data'], [])
        # collector family served by its own interface
        report2 = Report.create({
            'company_id': self.company.id,
            'production_order_no': 'MO-M1',
            'procedure_code': '2011',
            'test_code': 'RPT-002',
            'test_file_type': '2',
            'material_check_batch': 'JC20251126',
        })
        self.assertEqual(report2.family, 'collector')
        self.assertEqual(
            self.Interface._eip_serve('C-REPORT', 10)['data'][0]
            ['Test_Code'], 'RPT-002')

    def test_60_report_interface_requires_base_url(self):
        self.config.write({'collect_base_url': False})
        with self.assertRaises(Exception):
            self.Interface._eip_serve('M-REPORT', 10)

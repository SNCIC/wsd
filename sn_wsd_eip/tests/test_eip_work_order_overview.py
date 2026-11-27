"""Work order data overview, server side: the SN-deduplicated summary
of the process steps, the document tabs, the drill-down of every
number, and the fixed query counts (spec eip-work-order-overview).
"""

from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

WO = 'MO-OVERVIEW-1'
RULE_CODES = ('1002', '1004', '1005', '1007', '1008')


@tagged('post_install', '-at_install')
class TestEipWorkOrderOverview(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.PassRecord = self.env['sn.wsd.eip.pass.record']
        self.RawRecord = self.env['sn.wsd.eip.raw.record']
        self.PackRecord = self.env['sn.wsd.eip.pack.record']
        self.ShipRecord = self.env['sn.wsd.eip.ship.record']
        self.RawReport = self.env['sn.wsd.eip.raw.report']
        self.Rule = self.env['sn.wsd.eip.clean.rule']
        self.company = self.env.company
        # seed rules would judge rows this class means to control
        self.Rule.search([
            ('company_id', '=', self.company.id),
            ('info_type_code', 'in', list(RULE_CODES))]).unlink()
        self.env['sn.wsd.eip.collect.outbox'].search([]).unlink()
        self.counter = 0

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------

    def _row(self, code='1002', sn=None, identity=False, **vals):
        self.counter += 1
        sn = sn or '1261100%05d' % self.counter
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', code)
        vals.setdefault('test_code', '%s-T%s' % (code, self.counter))
        vals.setdefault('conclusion', 0)
        vals.setdefault('check_time',
                        datetime(2026, 11, 20, 10, 0, 0)
                        + timedelta(minutes=self.counter))
        vals.setdefault('device_no', 'DX01')
        vals.setdefault('model_code', 'DDSY10217')
        vals.setdefault('pcb_code', sn)
        vals.setdefault('production_order_no', 'PO-1')
        vals.setdefault('work_order_no', WO)
        vals.setdefault('test_name', 'Step %s' % code)
        if identity:
            vals['serial_identity_id'] = self.env[
                'sn.wsd.serial.identity'].create({
                    'name': sn, 'company_id': self.company.id,
                    'origin_type': 'manual'}).id
        else:
            vals['sn_name'] = sn
        return self.PassRecord.create(vals)

    def _full_1002(self, **vals):
        values = {'check_duration': '60', 'testing_voltage': '4200',
                  'leakage_current': 2.0}
        values.update(vals)
        return self._row(**values)

    def _pass_row(self, data, code='1002'):
        return next(item for item in data['pass'] if item['code'] == code)

    def _raw(self, code='1012', conclusion=0, state='pending', **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', code)
        vals.setdefault('production_order_no', 'PO-1')
        vals.setdefault('work_order_no', WO)
        vals.setdefault('material_check_batch', 'JC-%s' % self.counter)
        vals.setdefault('material_batch', 'MB-1')
        vals.setdefault('material_brand', 'Brand')
        vals.setdefault('material_supplier', 'Maker')
        vals.setdefault('material_leave_date', fields.Date.today())
        vals.setdefault('incoming_check_date', fields.Date.today())
        vals.setdefault('test_code', 'RAW-%s' % self.counter)
        vals.setdefault('model_code', 'M1')
        vals.setdefault('check_time', fields.Datetime.now())
        vals.setdefault('conclusion', conclusion)
        vals.setdefault('state', state)
        return self.RawRecord.create(vals)

    def _pack(self, number=1, conclusion=0, state='pending', **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', '1090')
        vals.setdefault('production_order_no', 'PO-1')
        vals.setdefault('work_order_no', WO)
        vals.setdefault('test_code', 'PACK-%s' % self.counter)
        vals.setdefault('model_code', 'M1')
        vals.setdefault('nameplate_code', 'NP-%s' % self.counter)
        vals.setdefault('number', number)
        vals.setdefault('unit', 'PCS')
        vals.setdefault('storage_date', fields.Date.today())
        vals.setdefault('conclusion', conclusion)
        vals.setdefault('state', state)
        return self.PackRecord.create(vals)

    def _ship(self, number=10, status='0', state='pending', **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', '1091')
        vals.setdefault('production_order_no', 'PO-1')
        vals.setdefault('work_order_no', WO)
        vals.setdefault('test_code', 'SHIP-%s' % self.counter)
        vals.setdefault('model_code', 'M1')
        vals.setdefault('nameplate_start', 'NP-START')
        vals.setdefault('nameplate_final', 'NP-FINAL')
        vals.setdefault('number', number)
        vals.setdefault('unit', 'PCS')
        vals.setdefault('deliver_date', fields.Date.today())
        vals.setdefault('deliver_status', status)
        vals.setdefault('state', state)
        return self.ShipRecord.create(vals)

    # ------------------------------------------------------------------
    # process step summary: SN-deduplicated units
    # ------------------------------------------------------------------

    def test_10_units_are_deduplicated_by_sn(self):
        a = '126110000001'
        self._row(sn=a, conclusion=1)
        self._row(sn=a)
        self._row(sn=a)
        self._row(sn='126110000002')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        row = self._pass_row(data)
        self.assertEqual((row['units'], row['ng']), (2, 1))
        # live judgement: the plain rows miss their value columns
        self.assertEqual((row['missing'], row['limit'], row['rejected']),
                         (2, 0, 0))
        self.assertEqual(row['pending'], 2)
        # unit B would pass, unit A is NG: neither qualifies
        self.assertEqual(row['qualified'], 0)

    def test_11_identity_and_snapshot_are_the_same_unit(self):
        """A row linked to the SN identity and a row of the same SN
        that lost the link (clear-pass) are one unit."""
        a = '126110000011'
        self._row(sn=a, identity=True)
        self._row(sn=a)  # snapshot only
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(self._pass_row(data)['units'], 1)

    def test_12_flags_overlap_on_one_unit(self):
        row = self._row(code='1008', conclusion=1)  # NG and 6 missing
        row._eip_clean_rows()
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        step = self._pass_row(data, code='1008')
        self.assertEqual(step['units'], 1)
        self.assertEqual(step['ng'], 1)
        self.assertEqual(step['missing'], 1)
        self.assertEqual(step['rejected'], 1)
        self.assertEqual(step['pending'], 0)

    def test_13_ng_is_counted_on_an_uncleaned_row(self):
        self._full_1002(conclusion=1)
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        row = self._pass_row(data)
        self.assertEqual((row['ng'], row['pending']), (1, 1))
        self.assertEqual((row['missing'], row['limit']), (0, 0))

    def test_14_uncleaned_row_is_judged_live(self):
        """A pending row does not wait for the button: the gates run
        on the raw columns on the fly (user decision 2026-11-27)."""
        self._row()  # 3 missing, never cleansed
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        row = self._pass_row(data)
        self.assertEqual(row['pending'], 1)
        self.assertEqual((row['missing'], row['limit'], row['rejected']),
                         (1, 0, 0))
        self.assertEqual(row['qualified'], 0)
        # the drill-down lists the live problems too
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1002', 'missing')
        self.assertEqual(result['total'], 1)
        self.assertEqual(len(result['rows'][0]['issues']), 3)

    def test_15_unit_with_any_pending_row_is_pending(self):
        a = '126110000021'
        self._full_1002(sn=a)
        self._full_1002(sn=a)._eip_clean_rows()
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        row = self._pass_row(data)
        self.assertEqual((row['units'], row['pending']), (1, 1))

    def test_16_missing_units_are_deduplicated(self):
        a = '126110000031'
        self._row(code='1008', sn=a)._eip_clean_rows()
        self._row(code='1008', sn=a)._eip_clean_rows()
        self._row(code='1008', sn='126110000032')._eip_clean_rows()
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(self._pass_row(data, '1008')['missing'], 2)

    def test_17_has_limit_follows_the_rules(self):
        self._full_1002()
        self._row(code='1005', current_value=3.0)
        Model = self.env['sn.wsd.eip.pass.record']
        data = Model.get_overview(WO)
        self.assertFalse(self._pass_row(data)['has_limit'])
        self.assertFalse(self._pass_row(data, '1005')['has_limit'])
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '1002',
            'field_name': 'leakage_current', 'upper_limit': 5.0})
        data = Model.get_overview(WO)
        self.assertTrue(self._pass_row(data)['has_limit'])
        self.assertFalse(self._pass_row(data, '1005')['has_limit'])

    def test_18_limit_units_come_from_the_issue_rows(self):
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '1002',
            'field_name': 'leakage_current', 'upper_limit': 5.0})
        a = '126110000041'
        self._full_1002(sn=a, leakage_current=7.5)._eip_clean_rows()
        self._full_1002(sn=a, leakage_current=2.0)._eip_clean_rows()
        self._full_1002(sn='126110000042')._eip_clean_rows()
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        row = self._pass_row(data)
        self.assertEqual((row['units'], row['limit'], row['rejected']),
                         (2, 1, 1))
        # a judged in-limit unit: only the clean second unit qualifies
        self.assertEqual(row['qualified'], 1)

    def test_19_worst_step_sorts_first(self):
        self._full_1002(sn='126110000051')
        self._row(code='1008', conclusion=1)._eip_clean_rows()
        self._row(code='1005', conclusion=1)
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        # 1008: 1 NG + 1 missing; 1005: 1 NG; 1002: nothing
        self.assertEqual([row['code'] for row in data['pass']],
                         self.PROCESS_METER)
        # the off-registry sort key (most flagged first) only applies
        # to codes the registry does not list
        self.assertEqual(data['pass'][1]['operation'], 'Step 1002')

    def test_20_summary_row_shape(self):
        self._full_1002(sn='126110000061', check_time=datetime(
            2026, 11, 20, 10, 0, 0))
        self._full_1002(sn='126110000062', check_time=datetime(
            2026, 11, 25, 18, 0, 0))
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        row = self._pass_row(data)
        self.assertEqual(
            set(row),
            {'code', 'name', 'operation', 'units', 'ng', 'missing',
             'limit', 'pending', 'rejected', 'qualified', 'has_limit'})
        self.assertEqual(row['name'], 'Withstand Voltage Test')
        header = data['header']
        self.assertEqual(header['production_order_no'], 'PO-1')
        # no work order ledger of this number: quantity stays empty
        self.assertIsNone(data['header']['planned_qty'])
        self.assertEqual(header['first_check_time'][:10], '2026-11-20')
        self.assertEqual(header['last_check_time'][:10], '2026-11-25')
        self.assertEqual(data['work_order_no'], WO)
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])

    def test_21_work_order_number_is_stripped(self):
        self._full_1002()
        data = self.env['sn.wsd.eip.pass.record'].get_overview('  %s  ' % WO)
        self.assertEqual(self._pass_row(data)['units'], 1)

    def test_22_other_work_orders_are_left_out(self):
        self._full_1002()
        self._full_1002(work_order_no='MO-OTHER')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(self._pass_row(data)['units'], 1)

    # ------------------------------------------------------------------
    # process steps are the EIP interface codes: all of them are
    # listed, collected or not; the four tabs always show
    # ------------------------------------------------------------------

    PROCESS_METER = ['%d' % value for value in range(1001, 1012)]
    RAW_METER = ['%d' % value for value in range(1012, 1019)]
    ZERO_KEYS = ('units', 'ng', 'missing', 'limit', 'pending', 'rejected',
                 'qualified')

    def test_23_all_process_interfaces_are_listed(self):
        """Data on three steps only: the tab lists the eleven enabled
        meter process-step interfaces in code order, zeros where
        nothing was collected."""
        self._full_1002(sn='126110000601')
        self._row(code='1005', sn='126110000602', current_value=1.0)
        self._row(code='1008', sn='126110000603')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        rows = data['pass']
        self.assertEqual([row['code'] for row in rows], self.PROCESS_METER)
        empty = [row for row in rows if row['code'] not in
                 ('1002', '1005', '1008')]
        self.assertEqual(len(empty), 8)
        for row in empty:
            self.assertEqual([row[key] for key in self.ZERO_KEYS], [0] * 7)
            self.assertEqual(row['operation'], '')
        self.assertEqual(rows[0]['name'], 'PCB Mounting Inspection (AOI)')
        self.assertEqual(rows[0]['has_limit'], False)
        self.assertEqual(rows[1]['units'], 1)          # 1002
        self.assertEqual(rows[4]['units'], 1)          # 1005
        self.assertEqual(rows[7]['units'], 1)          # 1008
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])

    def test_24_tabs_always_show_with_zero_tables(self):
        """Only process-step data: the other three tabs still show,
        their interfaces listed with zeros."""
        self._full_1002(sn='126110000611')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])
        self.assertEqual([row['code'] for row in data['raw']], self.RAW_METER)
        self.assertTrue(all(row['count'] == 0 and row['ng'] == 0
                            and row['pending'] == 0 and row['delivered'] == 0
                            and row['reports'] == 0
                            for row in data['raw']))
        self.assertEqual(data['pack'], [
            {'code': '1090', 'name': 'Packing Storage', 'qty': 0,
             'ng_qty': 0, 'pending': 0, 'delivered': 0}])
        self.assertEqual(data['ship'], [
            {'code': '1091', 'name': 'Finished-Goods Shipping',
             'batches': 0, 'qty': 0, 'shipped': 0, 'not_shipped': 0,
             'pending': 0, 'delivered': 0}])

    def test_25_collector_family_lists_collector_interfaces(self):
        """Data on a 2xxx code: the tab lists the collection-device
        interfaces, not the meter ones."""
        self._row(code='2003', sn='126110000621')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual([row['code'] for row in data['pass']],
                         ['%d' % value for value in range(2001, 2011)])
        self.assertEqual(data['pass'][2]['units'], 1)
        self.assertEqual([row['code'] for row in data['raw']],
                         ['%d' % value for value in range(2011, 2015)])
        self.assertEqual(data['pack'][0]['code'], '2090')
        self.assertEqual(data['ship'][0]['code'], '2091')

    def test_26_both_families_when_data_on_both(self):
        self._full_1002(sn='126110000631')
        self._row(code='2003', sn='126110000632')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(len(data['pass']), 11 + 10)
        self.assertEqual([row['code'] for row in data['pack']],
                         ['1090', '2090'])

    def test_27_data_on_an_unknown_code_is_still_listed(self):
        """A code the registry does not list as a process step (or
        does not know at all) keeps its numbers, after the interfaces."""
        self._full_1002(sn='126110000641')
        self._row(code='1099', sn='126110000642')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        rows = data['pass']
        self.assertEqual(len(rows), 12)
        self.assertEqual((rows[-1]['code'], rows[-1]['units'],
                          rows[-1]['name']), ('1099', 1, '1099'))

    def test_28_collected_step_keeps_its_operation_name(self):
        self._full_1002(sn='126110000651')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['pass'][1]['operation'], 'Step 1002')

    # ------------------------------------------------------------------
    # tabs, header, errors
    # ------------------------------------------------------------------

    def test_30_only_tabs_with_data_appear(self):
        self._full_1002()
        self._raw()
        self._raw(code='1013')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])
        self.assertEqual(len(data['raw']), 7)
        self.assertEqual(data['pack'][0]['qty'], 0)
        self.assertEqual(data['ship'][0]['batches'], 0)

    def test_31_no_data_raises(self):
        Model = self.env['sn.wsd.eip.pass.record']
        with self.assertRaisesRegex(UserError, 'No collected data'):
            Model.get_overview('MO-NOTHING')
        with self.assertRaisesRegex(UserError, 'Type a work order'):
            Model.get_overview('   ')

    def test_32_other_company_is_left_out(self):
        self._full_1002()
        other = self.env['res.company'].create({'name': 'EIP Other Co'})
        self._full_1002(company_id=other.id, work_order_no=WO)
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(self._pass_row(data)['units'], 1)

    def test_33_header_falls_back_to_the_document_rows(self):
        """No process-step rows: the production order number comes
        from the document tables."""
        self._raw()
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])
        self.assertEqual(data['header']['production_order_no'], 'PO-1')
        self.assertEqual(data['header']['first_check_time'], '')
        # the MES order is only the work order key: no product lookup
        self.assertNotIn('product_name', data['header'])

    def test_335_quantity_comes_from_the_work_order_ledger(self):
        """The header quantity is the production quantity of the EIP
        work order ledger of the same number."""
        self.env['sn.wsd.eip.work.order'].create({
            'wo_no': WO, 'ipo_no': 'IPO-Q', 'amount': '200'})
        self._full_1002()
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['header']['planned_qty'], '200')
        # another ledger of another number must not leak in
        self.env['sn.wsd.eip.work.order'].create({
            'wo_no': 'WO-OTHER-Q', 'ipo_no': 'IPO-Q2', 'amount': '5'})
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['header']['planned_qty'], '200')

    def test_34_unknown_tab_and_flag_raise(self):
        self._full_1002()
        Model = self.env['sn.wsd.eip.pass.record']
        with self.assertRaisesRegex(UserError, 'Unknown tab'):
            Model.get_detail(WO, 'nope', '1002', 'units')
        with self.assertRaisesRegex(UserError, 'Unknown number'):
            Model.get_detail(WO, 'pass', '1002', 'shipped')
        with self.assertRaisesRegex(UserError, 'Unknown number'):
            Model.get_detail(WO, 'ship', '1091', 'ng')

    # ------------------------------------------------------------------
    # document tabs
    # ------------------------------------------------------------------

    def test_40_raw_material_tab(self):
        self._raw()
        self._raw()
        self._raw(conclusion=1)
        self._raw(code='1013', state='delivered')
        self.RawReport.create({
            'company_id': self.company.id, 'production_order_no': 'PO-1',
            'production_work_no': WO, 'procedure_code': '1012',
            'material_check_batch': 'JC-REPORT'})
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        rows = {item['code']: item for item in data['raw']}
        self.assertEqual(rows['1012'],
                         {'code': '1012', 'name': 'Varistor Inspection',
                          'count': 3, 'ng': 1, 'reports': 1, 'pending': 3,
                          'delivered': 0})
        self.assertEqual(rows['1013']['count'], 1)
        self.assertEqual(rows['1013']['delivered'], 1)
        # the report is a count only: no tab, no rows
        self.assertNotIn('raw_report', data['tabs'])
        self.assertNotIn('report', data)

    def test_41_reports_of_other_work_orders_are_left_out(self):
        self._raw()
        self.RawReport.create({
            'company_id': self.company.id, 'production_order_no': 'PO-1',
            'production_work_no': 'MO-OTHER', 'procedure_code': '1012',
            'material_check_batch': 'JC-OTHER'})
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)

    def test_42_packing_tab_sums_the_quantities(self):
        self._pack(number=1)
        self._pack(number=1)
        self._pack(number=1, conclusion=1, state='delivered')
        self._pack(number=97, state='delivered')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])
        self.assertEqual(data['pack'],
                         [{'code': '1090', 'name': 'Packing Storage',
                           'qty': 100, 'ng_qty': 1, 'pending': 2,
                           'delivered': 2}])

    def test_43_shipping_tab(self):
        self._ship(number=60)
        self._ship(number=40, status='1')
        self._ship(number=5, status='1', state='delivered')
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])
        self.assertEqual(data['ship'],
                         [{'code': '1091',
                           'name': 'Finished-Goods Shipping',
                           'batches': 3, 'qty': 105, 'shipped': 2,
                           'not_shipped': 1, 'pending': 2, 'delivered': 1}])

    def test_44_all_four_tabs(self):
        self._full_1002()
        self._raw()
        self._pack()
        self._ship()
        data = self.env['sn.wsd.eip.pass.record'].get_overview(WO)
        self.assertEqual(data['tabs'], ['pass', 'raw', 'pack', 'ship'])

    # ------------------------------------------------------------------
    # drill-down
    # ------------------------------------------------------------------

    def test_50_units_lists_every_record(self):
        a = '126110000071'
        self._full_1002(sn=a, conclusion=1)
        self._full_1002(sn=a)
        self._full_1002(sn='126110000072')
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1002', 'units')
        self.assertEqual(result['total'], 3)
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual({row['sn'] for row in result['rows']},
                         {a, '126110000072'})
        self.assertTrue(all(row['issues'] == [] for row in result['rows']))

    def test_51_ng_lists_each_fail_of_the_unit(self):
        a = '126110000081'
        self._full_1002(sn=a, conclusion=1)
        self._full_1002(sn=a, conclusion=1)
        self._full_1002(sn=a)
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1002', 'ng')
        self.assertEqual(result['total'], 2)
        self.assertEqual([row['sn'] for row in result['rows']], [a, a])
        self.assertTrue(all(row['conclusion'] == 1
                            for row in result['rows']))

    def test_52_detail_rows_are_newest_first(self):
        self._full_1002(sn='126110000091',
                        check_time=datetime(2026, 11, 20, 10, 0, 0))
        self._full_1002(sn='126110000092',
                        check_time=datetime(2026, 11, 25, 10, 0, 0))
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1002', 'units')
        self.assertEqual([row['sn'] for row in result['rows']],
                         ['126110000092', '126110000091'])
        row = result['rows'][0]
        self.assertEqual(row['check_time'][:10], '2026-11-25')
        self.assertEqual(row['state'], 'pending')
        self.assertEqual(row['device_no'], 'DX01')

    def test_53_missing_lists_the_rows_with_the_issue(self):
        self._row(code='1008', sn='126110000101')._eip_clean_rows()
        fixed = self._row(code='1008', sn='126110000102')
        self.env['sn.wsd.eip.clean.fix'].create([{
            'source_id': fixed.id, 'field_name': name, 'value': 'X',
            'basis': 'record',
        } for name in ('plant_code', 'software_version', 'nameplate_code',
                       'table_no', 'table_address', 'asset_management_no')])
        fixed._eip_clean_rows()
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1008', 'missing')
        self.assertEqual(result['total'], 1)
        row = result['rows'][0]
        self.assertEqual(row['sn'], '126110000101')
        self.assertEqual(len(row['issues']), 6)
        self.assertEqual({issue['kind'] if 'kind' in issue
                          else 'missing' for issue in row['issues']},
                         {'missing'})
        plant = next(issue for issue in row['issues']
                     if issue['field_name'] == 'plant_code')
        self.assertEqual(plant['message'], 'missing required: plant_code')

    def test_54_limit_issue_carries_type_and_limits(self):
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '1007',
            'field_name': 'average_error', 'average_error_type': 'C1',
            'lower_limit': -0.5, 'upper_limit': 0.5})
        row = self._row(code='1007', sn='126110000111')
        detail = self.env['sn.wsd.eip.pass.record.line'].create({
            'record_id': row.id, 'line_type': 'test_detail',
            'project_name': '正向-有功-C相-Imax1.0', 'actual_value': '-0.700',
            'upper_limit': '0.6', 'lower_limit': '0'})
        row._eip_clean_rows()
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1007', 'limit')
        self.assertEqual(result['total'], 1)
        issue = result['rows'][0]['issues'][0]
        self.assertEqual(issue['type_code'], 'C1')
        self.assertEqual(issue['field_name'], 'average_error')
        self.assertAlmostEqual(issue['actual_value'], -0.7, places=6)
        self.assertEqual((issue['lower_limit'], issue['upper_limit']),
                         (-0.5, 0.5))
        self.assertEqual(detail.cleansed_value, '-0.7')

    def test_55_pending_and_rejected(self):
        self._row(code='1008', sn='126110000121')
        self._row(code='1008', sn='126110000122')._eip_clean_rows()
        Model = self.env['sn.wsd.eip.pass.record']
        pending = Model.get_detail(WO, 'pass', '1008', 'pending')
        rejected = Model.get_detail(WO, 'pass', '1008', 'rejected')
        self.assertEqual([row['sn'] for row in pending['rows']],
                         ['126110000121'])
        self.assertEqual([row['sn'] for row in rejected['rows']],
                         ['126110000122'])

    def test_56_other_codes_are_left_out_of_the_detail(self):
        self._full_1002(sn='126110000131')
        self._row(code='1005', sn='126110000132', current_value=1.0)
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1005', 'units')
        self.assertEqual([row['sn'] for row in result['rows']],
                         ['126110000132'])

    def test_57_paging_is_stable(self):
        for index in range(5):
            self._full_1002(sn='12611000014%d' % index,
                            check_time=datetime(2026, 11, 20, 10, index, 0))
        Model = self.env['sn.wsd.eip.pass.record']
        first = Model.get_detail(WO, 'pass', '1002', 'units', 2, 0)
        second = Model.get_detail(WO, 'pass', '1002', 'units', 2, 2)
        last = Model.get_detail(WO, 'pass', '1002', 'units', 2, 4)
        self.assertEqual((first['total'], len(first['rows'])), (5, 2))
        pages = (first['rows'] + second['rows'] + last['rows'])
        self.assertEqual(len(pages), 5)
        self.assertEqual(len({row['id'] for row in pages}), 5)
        self.assertEqual(pages[0]['sn'], '126110000144')
        self.assertEqual(pages[-1]['sn'], '126110000140')
        beyond = Model.get_detail(WO, 'pass', '1002', 'units', 2, 50)
        self.assertEqual((beyond['total'], beyond['rows']), (5, []))

    def test_575_search_domain_filters_the_detail(self):
        """The search area's conditions arrive as a plain domain and
        are filtered server-side (totals and pagination included)."""
        self._full_1002(sn='126110000141',
                        check_time=datetime(2026, 11, 20, 10, 0, 0))
        self._full_1002(sn='126110000142',
                        check_time=datetime(2026, 11, 21, 10, 0, 0))
        Model = self.env['sn.wsd.eip.pass.record']
        result = Model.get_detail(WO, 'pass', '1002', 'units', 80, 0,
                                  [('sn_name', '=', '126110000141')])
        self.assertEqual(result['total'], 1)
        self.assertEqual([row['sn'] for row in result['rows']],
                         ['126110000141'])
        # combined with the flag
        result = Model.get_detail(WO, 'pass', '1002', 'units', 80, 0,
                                  [('check_time', '>=', '2026-11-21 00:00:00')])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['rows'][0]['sn'], '126110000142')

    def test_58_default_page_is_80_rows(self):
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'pass', '1002', 'units')
        self.assertEqual(result['rows'], [])

    def test_59_document_details(self):
        self._raw()
        self._raw(conclusion=1)
        ng_raw = self.env['sn.wsd.eip.raw.record'].search(
            [('conclusion', '=', 1), ('work_order_no', '=', WO)], limit=1)
        self._pack(number=7, conclusion=1)
        self._ship(number=9, status='1')
        self._ship(number=3, status='0')
        Model = self.env['sn.wsd.eip.pass.record']
        raw = Model.get_detail(WO, 'raw', '1012', 'ng')
        self.assertEqual((raw['total'], [row['id'] for row in raw['rows']]),
                         (1, [ng_raw.id]))
        self.assertIn('material_batch', raw['rows'][0])
        self.assertEqual(Model.get_detail(WO, 'raw', '1012', 'all')['total'],
                         2)
        pack = Model.get_detail(WO, 'pack', '1090', 'ng')
        self.assertEqual((pack['total'], pack['rows'][0]['number']), (1, 7))
        ship = Model.get_detail(WO, 'ship', '1091', 'not_shipped')
        self.assertEqual((ship['total'], ship['rows'][0]['number']), (1, 3))
        self.assertEqual(
            Model.get_detail(WO, 'ship', '1091', 'shipped')['total'], 1)
        paged = Model.get_detail(WO, 'ship', '1091', 'all', 1, 1)
        self.assertEqual((paged['total'], len(paged['rows'])), (2, 1))

    def test_60_document_detail_is_company_and_order_scoped(self):
        self._raw()
        self._raw(work_order_no='MO-OTHER')
        result = self.env['sn.wsd.eip.pass.record'].get_detail(
            WO, 'raw', '1012', 'all')
        self.assertEqual(result['total'], 1)

    # ------------------------------------------------------------------
    # query counts: fixed, independent of the row count
    # ------------------------------------------------------------------

    def _seed_many(self, count):
        a = '126110000201'
        rows = []
        for _index in range(count):
            rows.append({'company_id': self.company.id,
                         'info_type_code': '1002',
                         'test_code': 'BULK-%s' % self._bulk_counter(),
                         'conclusion': 1, 'work_order_no': WO,
                         'production_order_no': 'PO-1', 'sn_name': a})
        self.PassRecord.create(rows)

    def _bulk_counter(self):
        self.counter += 1
        return self.counter

    def test_70_overview_query_count_is_fixed(self):
        self._seed_many(20)
        self._raw()
        Model = self.env['sn.wsd.eip.pass.record']
        with self.assertQueryCount(16):
            Model.get_overview(WO)
        self._seed_many(40)
        self.env.flush_all()
        with self.assertQueryCount(15):
            data = Model.get_overview(WO)
        self.assertEqual(self._pass_row(data)['units'], 1)
        self.assertEqual(self._pass_row(data)['ng'], 1)

    def test_71_detail_query_count_is_fixed(self):
        self._seed_many(20)
        Model = self.env['sn.wsd.eip.pass.record']
        with self.assertQueryCount(13):
            result = Model.get_detail(WO, 'pass', '1002', 'ng')
        self.assertEqual((result['total'], len(result['rows'])), (20, 20))
        self._seed_many(40)
        self.env.flush_all()
        with self.assertQueryCount(8):
            result = Model.get_detail(WO, 'pass', '1002', 'ng')
        self.assertEqual((result['total'], len(result['rows'])), (60, 60))

    def test_72_issue_detail_adds_exactly_one_query(self):
        for index in range(3):
            self._row(code='1008',
                      sn='1261100003%03d' % index)._eip_clean_rows()
        Model = self.env['sn.wsd.eip.pass.record']
        # count + page ids + row read + the page's problems
        with self.assertQueryCount(11):
            result = Model.get_detail(WO, 'pass', '1008', 'missing')
        self.assertEqual(result['total'], 3)
        self.assertTrue(all(len(row['issues']) == 6
                            for row in result['rows']))

    def test_73_document_detail_query_count(self):
        self._raw()
        with self.assertQueryCount(3):
            self.env['sn.wsd.eip.pass.record'].get_detail(
                WO, 'raw', '1012', 'all')

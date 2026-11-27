from odoo import fields
from odoo.exceptions import ValidationError

from . import eip_test_common


class TestEipCapture(eip_test_common.EipCaptureCase):
    """Phase-1 capture: rows are born in the pass transaction with the
    common EIP fields; scrap and unmapped operations produce nothing."""

    def test_10_ok_pass_row_and_fields(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], '126100000001', 'ok')
        rows = self._rows('126100000001')
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.info_type_code, '1003')
        self.assertEqual(row.conclusion, 0)
        self.assertEqual(row.pcb_code, '126100000001')
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
        self._pass(order, wcs['a'], '126100000002', 'ng')
        row = self._rows('126100000002')
        self.assertEqual(len(row), 1)
        self.assertEqual(row.conclusion, 1)

    def test_20_retest_two_rows(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], '126100000003', 'ng')
        self._pass(order, wcs['a'], '126100000003', 'ok')
        rows = self._rows('126100000003')
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(rows.mapped('conclusion')), [0, 1])
        codes = rows.mapped('test_code')
        self.assertEqual(len(set(codes)), 2)
        # aging interface rows carry no PCB identity (spec has none)
        self._pass(order, wcs['b'], '126100000003', 'ok')
        aging = self._rows('126100000003').filtered(
            lambda r: r.info_type_code == '1011')
        self.assertEqual(len(aging), 1)
        self.assertFalse(aging.pcb_code)

    def test_30_scrap_not_collected(self):
        order = self._make_order_online()
        wcs = self._wcs()
        serial = order.scan_enter('126100000004', wcs['a'])
        history = self.env['sn.wsd.serial.operation.history'].search([
            ('serial_identity_id', '=', serial.id),
            ('result', '=', 'in_progress')], limit=1)
        self.assertTrue(history)
        # scrap is not a test verdict: the hook must not collect it
        history.write({'result': 'scrap', 'out_date': history.in_date})
        self.assertFalse(self._rows('126100000004'))

    def test_40_unmapped_operation_not_collected(self):
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], '126100000005', 'ok')
        self._pass(order, wcs['b'], '126100000005', 'ok')
        self._pass(order, wcs['c'], '126100000005', 'ok')
        rows = self._rows('126100000005')
        self.assertEqual(sorted(rows.mapped('info_type_code')),
                         ['1003', '1011'])

    def test_50_device_chain_equipment(self):
        order = self._make_order_online()
        wcs = self._wcs()
        equipment = self.env['sn.wsd.device.equipment'].create({
            'code': 'RF-EIP-01', 'name': 'Reflow Oven 1'})
        self.env['sn.wsd.workcenter.equipment'].create({
            'workcenter_id': wcs['a'].id, 'equipment_id': equipment.id})
        self._pass(order, wcs['a'], '126100000006', 'ok')
        row = self._rows('126100000006')
        self.assertEqual(row.device_no, 'RF-EIP-01')
        self.assertEqual(row.equipment_id, equipment)

    def test_60_clear_pass_keeps_row(self):
        order = self._make_order_online()
        wcs = self._wcs()
        serial = self._pass(order, wcs['a'], '126100000007', 'ok')
        row = self._rows('126100000007')
        self.assertEqual(len(row), 1)
        order.action_clear_station_pass(serial)
        row.invalidate_recordset()
        self.assertTrue(row.exists())
        self.assertFalse(row.history_id)
        # snapshots survive the anchor drop
        self.assertEqual(row.sn_name, '126100000007')
        self.assertEqual(row.work_order_no, order.name)
        self.assertEqual(row.conclusion, 0)

    # ------------------------------------------------------------------
    # multi-code operations (2026-11-27 joint-test finding): one pass on
    # a station mapped to several interfaces spawns one row per code
    # ------------------------------------------------------------------
    def test_70_multi_code_pass_one_row_per_code(self):
        Mapping = self.env['sn.wsd.eip.operation.mapping']
        Mapping.create({'operation_id': self.op_a.id, 'info_code': '1005'})
        order = self._make_order_online()
        wcs = self._wcs()
        serial = self._pass(order, wcs['a'], '126100000010', 'ok')
        rows = self._rows('126100000010')
        self.assertEqual(sorted(rows.mapped('info_type_code')),
                         ['1003', '1005'])
        # same pass anchor, one test_code per code, common fields equal
        self.assertEqual(len(rows.mapped('history_id')), 1)
        self.assertEqual(
            sorted(rows.mapped('test_code')),
            ['1003-%d' % rows[0].history_id.id,
             '1005-%d' % rows[0].history_id.id])
        self.assertEqual(rows.mapped('sn_name'),
                         ['126100000010', '126100000010'])
        # re-running the capture hook stays idempotent per code
        self.env['sn.wsd.eip.pass.record']._capture_from_history(
            rows.history_id)
        rows = self._rows('126100000010')
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(rows.mapped('info_type_code')),
                         ['1003', '1005'])

    def test_71_multi_code_report_feeds_all_rows(self):
        Mapping = self.env['sn.wsd.eip.operation.mapping']
        Mapping.create({'operation_id': self.op_a.id, 'info_code': '1005'})
        self.env['sn.wsd.eip.value.mapping'].create({
            'info_type_code': '1005', 'source_kind': 'detail_item',
            'source_key': 'Battery Current', 'eip_field': 'current_value'})
        order = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], '126100000011', 'ok')
        rop = order.x_mes_route_id.operation_ids.filtered(
            lambda op: op.operation_id == self.op_a)
        serial = self.env['sn.wsd.serial.identity'].search(
            [('name', '=', '126100000011')])
        result = self.env['sn.wsd.mes.test.result'].create({
            'serial_identity_id': serial.id, 'result': 'ok',
            'test_type': 'final_test', 'mes_order_id': order.id,
            'route_operation_id': rop.id})
        self.env['sn.wsd.mes.test.result.detail'].create({
            'test_result_id': result.id, 'sequence': 1,
            'project_name': 'Battery Current', 'actual_value': '12.5',
            'result': 'ok'})
        rows = self._rows('126100000011')
        self.assertEqual(len(rows), 2)
        # the single report fed every row of the pass
        self.assertEqual(rows.mapped('test_result_id'), result)
        by_code = {row.info_type_code: row for row in rows}
        # each row extracted only its own code's value mappings
        self.assertEqual(by_code['1005'].current_value, 12.5)
        self.assertFalse(by_code['1003'].current_value)


class TestEipNormalization(eip_test_common.EipCaptureCase):
    """One EIP work order covers the SMT / DIP / assembly MES orders:
    the capture writes the ledger numbers, an unlinked order keeps its
    own, the ledger rewrites the undelivered rows when it is saved."""

    def _ledger(self, main, *linked, wo_no=None, ipo_no=None):
        return self.env['sn.wsd.eip.work.order'].create({
            'mes_order_id': main.id,
            'mes_order_ids': [(6, 0, [main.id] + [o.id for o in linked])],
            'wo_no': wo_no or main.name,
            'ipo_no': ipo_no or main.production_id.name,
        })

    def _online(self):
        """One online order per line: a second order created on the
        same line stays offline, mark it online directly (the pass
        fixtures only need the flag)."""
        order = self._make_order_online()
        if not order.x_online_date:
            order._apply_online(self.env['sn.wsd.mes.order'])
        return order

    def _pack(self, order, nameplate, state=None):
        pack = self.env['sn.wsd.eip.pack.record'].create({
            'info_type_code': '1090',
            'production_order_no': order.production_id.name,
            'work_order_no': order.name,
            'test_code': 'PACK-%s' % nameplate,
            'model_code': 'DDS102 220V 5(60)A',
            'nameplate_code': nameplate,
            'unit': '只',
            'storage_date': fields.Date.today(),
        })
        if state:
            pack.write({'state': state})
        return pack

    # ------------------------------------------------------------------
    # capture: linked order -> ledger numbers
    # ------------------------------------------------------------------
    def test_10_linked_order_reports_ledger_numbers(self):
        main = self._make_order_online()
        smt = self._online()
        self._ledger(main, smt)
        wcs = self._wcs()
        self._pass(smt, wcs['a'], '126100000101', 'ok')
        row = self._rows('126100000101')
        self.assertEqual(len(row), 1)
        self.assertEqual(row.work_order_no, main.name)
        self.assertEqual(row.production_order_no, main.production_id.name)
        # the row keeps its own true MES order / manufacturing order
        self.assertEqual(row.mes_order_id, smt)
        self.assertEqual(row.production_id, smt.production_id)

    def test_11_unlinked_order_keeps_its_numbers(self):
        main = self._make_order_online()
        other = self._online()
        self._ledger(main)
        wcs = self._wcs()
        self._pass(other, wcs['a'], '126100000102', 'ok')
        row = self._rows('126100000102')
        self.assertEqual(row.work_order_no, other.name)
        self.assertEqual(row.production_order_no,
                         other.production_id.name)

    def test_12_multi_code_rows_share_the_ledger_numbers(self):
        self.env['sn.wsd.eip.operation.mapping'].create({
            'operation_id': self.op_a.id, 'info_code': '1005'})
        main = self._make_order_online()
        dip = self._online()
        self._ledger(main, dip)
        wcs = self._wcs()
        self._pass(dip, wcs['a'], '126100000103', 'ok')
        rows = self._rows('126100000103')
        self.assertEqual(sorted(rows.mapped('info_type_code')),
                         ['1003', '1005'])
        # one pass, one row per code, every row carries the same ledger
        # numbers
        self.assertEqual(set(rows.mapped('work_order_no')), {main.name})
        self.assertEqual(set(rows.mapped('production_order_no')),
                         {main.production_id.name})

    def test_13_overview_finds_the_linked_line_under_the_ledger(self):
        """The work-order overview is keyed by the reported number: a
        row captured under a linked MES order shows up under the
        ledger number (the three lines converge on one page)."""
        main = self._make_order_online()
        smt = self._online()
        self._ledger(main, smt)
        wcs = self._wcs()
        self._pass(smt, wcs['a'], '126100000107', 'ok')
        overview = self.env['sn.wsd.eip.pass.record'].get_overview(main.name)
        steps = {row['code']: row for row in overview['pass']}
        self.assertIn('1003', steps)
        self.assertEqual(steps['1003']['units'], 1)

    # ------------------------------------------------------------------
    # ledger constraints
    # ------------------------------------------------------------------
    def test_20_onchange_adds_the_main_order_to_the_list(self):
        main = self._make_order_online()
        work = self.env['sn.wsd.eip.work.order'].new({
            'mes_order_id': main.id})
        work._onchange_mes_order_id()
        self.assertEqual(work.wo_no, main.name)
        self.assertEqual(work.ipo_no, main.production_id.name)
        self.assertEqual(work.mes_order_ids.mapped('name'), [main.name])

    def test_21_main_order_must_be_linked(self):
        main = self._make_order_online()
        other = self._make_order_online()
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.eip.work.order'].create({
                'mes_order_id': main.id,
                'mes_order_ids': [(6, 0, [other.id])],
                'wo_no': main.name,
                'ipo_no': main.production_id.name,
            })

    def test_22_one_mes_order_belongs_to_one_work_order(self):
        main = self._make_order_online()
        first = self._ledger(main)
        with self.assertRaises(ValidationError) as caught:
            self.env['sn.wsd.eip.work.order'].create({
                'mes_order_id': main.id,
                'mes_order_ids': [(6, 0, [main.id])],
                'wo_no': 'WO-SECOND',
                'ipo_no': 'IPO-SECOND',
            })
        self.assertIn(first.wo_no, str(caught.exception))

    def test_23_linked_order_cannot_join_a_second_work_order(self):
        main = self._make_order_online()
        smt = self._make_order_online()
        self._ledger(main, smt)
        with self.assertRaises(ValidationError) as caught:
            self.env['sn.wsd.eip.work.order'].create({
                'mes_order_ids': [(6, 0, [smt.id])],
                'wo_no': 'WO-THIRD',
                'ipo_no': 'IPO-THIRD',
            })
        self.assertIn(smt.name, str(caught.exception))

    # ------------------------------------------------------------------
    # write-back on ledger save
    # ------------------------------------------------------------------
    def test_30_late_link_rewrites_undelivered_rows(self):
        order = self._make_order_online()
        main = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], '126100000104', 'ok')
        pack = self._pack(order, '260000000104')
        row = self._rows('126100000104')
        self.assertEqual(row.work_order_no, order.name)
        self._ledger(main, order)
        row.invalidate_recordset()
        pack.invalidate_recordset()
        self.assertEqual(row.work_order_no, main.name)
        self.assertEqual(row.production_order_no,
                         main.production_id.name)
        self.assertEqual(pack.work_order_no, main.name)
        self.assertEqual(pack.production_order_no,
                         main.production_id.name)
        # the gateway payload is read off the columns: it reports the
        # ledger numbers too
        payload = pack._eip_pack_payloads()[0]
        self.assertEqual(payload['WORK_ORDER_CODE'], main.name)
        self.assertEqual(payload['PRODUCTION_ORDER_ID'],
                         main.production_id.name)

    def test_31_delivered_rows_stay_frozen(self):
        order = self._make_order_online()
        main = self._make_order_online()
        wcs = self._wcs()
        self._pass(order, wcs['a'], '126100000105', 'ok')
        pack = self._pack(order, '260000000105', state='delivered')
        row = self._rows('126100000105')
        row.write({'state': 'delivered'})
        self._ledger(main, order)
        row.invalidate_recordset()
        pack.invalidate_recordset()
        self.assertEqual(row.work_order_no, order.name)
        self.assertEqual(pack.work_order_no, order.name)

    def test_32_change_main_rewrites_to_the_new_numbers(self):
        assembly = self._make_order_online()
        smt = self._make_order_online()
        dip = self._online()
        work = self._ledger(assembly, smt, dip)
        wcs = self._wcs()
        self._pass(dip, wcs['a'], '126100000106', 'ok')
        pack = self._pack(dip, '260000000106')
        row = self._rows('126100000106')
        self.assertEqual(row.work_order_no, assembly.name)
        work.write({
            'mes_order_id': smt.id,
            'wo_no': smt.name,
            'ipo_no': smt.production_id.name,
        })
        row.invalidate_recordset()
        pack.invalidate_recordset()
        self.assertEqual(row.work_order_no, smt.name)
        self.assertEqual(row.production_order_no,
                         smt.production_id.name)
        self.assertEqual(pack.work_order_no, smt.name)
        self.assertEqual(pack.production_order_no,
                         smt.production_id.name)

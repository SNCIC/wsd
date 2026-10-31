"""OQC receipt release gates (oqc-disposition-closure batch 2, second
half: tasks 2.4/2.5).

Covers every scenario of the ADDED requirement "OQC Release Checks Cover
Completion Receipts and Pallet Receipts" of mes-completion-sn:
- scheme hit without an inspection document blocks completion
- a done/pass batch with pending boards blocks completion, all-closed
  releases it
- line-side direct validation is gated before backflush
- a mixed two-order pallet is refused as a whole (atomic rollback)
- an already-created receipt is re-checked on validation when a new NG
  arrives (no stale pass)
- SN-level refusals: scrapped / unresolved boards never enter stock
- no-obligation orders and report mode get no extra gate
- material-issue pickings are never mistaken for MES receipts.

Fixtures reuse the batch-2a release-judgment class (route A -> OQC(C)
-> B, n=2/Ac=1/Re=2)."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.sn_wsd_mrp.tests.pick_gate import give_pick
from odoo.addons.sn_wsd_quality.tests.test_oqc_release_judgment import (
    TestOqcReleaseJudgment,
)


@tagged('post_install', '-at_install')
class TestOqcReceiptGate(TestOqcReleaseJudgment):

    def _identity(self, name):
        """Existing board identity (auto-created while walking the route);
        unlike the base _serial helper this never creates a duplicate."""
        return self.env['sn.wsd.serial.identity'].search([
            ('name', '=', name), ('company_id', '=', self.company.id)],
            limit=1)

    def _full_ok_round(self, order, name):
        """One board walks A, the OQC operation C and the tail B with OK:
        unlike the base _ok_round this also counts as output, so a small
        completion does not close the order."""
        self._feed_through_a(order, name)
        for wc in (self.wc_c, self.wc_b):
            res = order.sn_station_scan(wc.id, name)
            if isinstance(res, dict) and res.get('action') == 'leave':
                order.sn_station_leave(res['wip_id'], 'ok')
        return order.x_oqc_inspection_id

    def _stock_line_side(self, order, qty=100):
        component = order.production_id.bom_id.bom_line_ids.product_id
        line_side = order.production_line_id.workshop_id.component_location_id
        Quant = self.env['stock.quant']
        if not Quant.search_count([
                ('product_id', '=', component.id),
                ('location_id', '=', line_side.id)]):
            Quant.create({
                'product_id': component.id,
                'location_id': line_side.id, 'quantity': qty})
        return component, line_side

    def _receipt_picking(self, order):
        return order.picking_ids.filtered(
            lambda p: p.state not in ('cancel',) and p.x_mes_order_id)

    # ------------------------------------------------------------------
    # Scenario: scheme hit but no inspection document yet
    # ------------------------------------------------------------------
    def test_01_scheme_hit_without_document_blocks_completion(self):
        order = self._order()
        self.assertFalse(order.x_oqc_inspection_ids)
        with self.assertRaises(UserError) as ctx:
            order.action_complete(2.0, 'stock')
        self.assertIn('outgoing inspection plan', str(ctx.exception))
        # refusal happened before backflush / receipt / quantity: nothing moved
        self.assertEqual(order.x_done_qty, 0.0)
        self.assertFalse(self._receipt_picking(order))

    # ------------------------------------------------------------------
    # Scenario: done/pass batch (Ac>0) still carries pending boards
    # ------------------------------------------------------------------
    def test_02_pending_board_blocks_then_release_allows(self):
        order = self._order()
        self._stock_line_side(order)
        inspection = self._ok_round(order, 'SN-RG-101')
        self._ng_round(order, 'SN-RG-102')
        ng_serial = self._identity('SN-RG-102')
        inspection.action_done()
        self.assertEqual(inspection.state, 'done')
        self.assertEqual(inspection.result, 'pass')  # d=1 <= Ac=1
        self.assertFalse(inspection.x_oqc_release_ready)

        with self.assertRaises(UserError) as ctx:
            order.action_complete(1.0, 'stock')
        self.assertIn(inspection.name, str(ctx.exception))
        self.assertIn('SN-RG-102', str(ctx.exception))
        self.assertEqual(order.x_done_qty, 0.0)

        # every known defect closed -> release -> completion goes through
        self._close_retest(inspection, ng_serial)
        self.assertTrue(inspection.x_oqc_release_ready)
        order.action_complete(1.0, 'stock')
        self.assertEqual(order.x_done_qty, 1.0)
        self.assertTrue(self._receipt_picking(order))

    # ------------------------------------------------------------------
    # Scenario: line-side direct validation is gated too
    # ------------------------------------------------------------------
    def test_03_lineside_direct_validate_blocked_before_backflush(self):
        order = self._order()
        component, line_side = self._stock_line_side(order)
        inspection = self._ok_round(order, 'SN-RG-201')
        self.assertEqual(inspection.state, 'open')  # not completed yet
        with self.assertRaises(UserError) as ctx:
            order.action_complete(1.0, 'lineside', workshop=self.workshop)
        self.assertIn('has not released', str(ctx.exception))
        self.assertEqual(order.x_done_qty, 0.0)
        self.assertFalse(self._receipt_picking(order))
        quant = self.env['stock.quant'].search([
            ('product_id', '=', component.id),
            ('location_id', '=', line_side.id)])
        self.assertEqual(quant.quantity, 100.0)  # no backflush happened

    # ------------------------------------------------------------------
    # Scenario: mixed pallet of two orders is refused as a whole
    # ------------------------------------------------------------------
    def test_04_two_order_pallet_refused_atomically(self):
        # order 1: clean sample -> done/pass, released (two orders
        # share the MO: plan 5 each to stay within its quantity)
        order1 = self._order(qty=5)
        inspection1 = self._ok_round(order1, 'SN-RG-301')
        self._ok_round(order1, 'SN-RG-302')
        inspection1.action_done()
        self.assertTrue(inspection1.x_oqc_release_ready)
        # order 2: NG board pending -> done/pass but not released; its own
        # MO (pack records resolve the receiving order through the
        # production), line and work centers so scans resolve this order
        mo2 = self.env['mrp.production'].create({
            'product_id': self.product.id, 'product_qty': 5,
            'company_id': self.company.id,
        })
        line2, wcs2 = self._alt_line_wcs('O2')
        order2 = self.env['sn.wsd.mes.order'].create({
            'production_id': mo2.id,
            'production_line_id': line2.id,
            'date_plan': fields.Date.today(), 'planned_qty': 5,
        })
        gate2 = give_pick(self.env, order2)
        order2.action_online()
        gate2.action_cancel()
        inspection2 = self._ok_round(order2, 'SN-RG-303', wcs=wcs2)
        self._ng_round(order2, 'SN-RG-304', wcs=wcs2)
        inspection2.action_done()
        self.assertFalse(inspection2.x_oqc_release_ready)

        Package = self.env['stock.package']
        PackRecord = self.env['sn.wsd.meter.pack.record']
        BindLog = self.env['sn.wsd.carton.pallet.binding.log']

        def pack(order, serial_name, carton_no):
            carton = Package.get_or_create_wsd_package(
                carton_no, 'carton', self.company)
            PackRecord.create({
                'serial_identity_id': self._identity(serial_name).id,
                'production_id': order.production_id.id,
                'carton_package_id': carton.id,
            })
            BindLog.bind_carton_to_pallet('PLT-RG-01', carton_no)

        pack(order1, 'SN-RG-301', 'CTN-RG-01')
        pack(order2, 'SN-RG-304', 'CTN-RG-02')
        BindLog.close_pallet('PLT-RG-01')
        pallet = Package.search([
            ('name', '=', 'PLT-RG-01'),
            ('x_wsd_company_id', '=', self.company.id),
            ('x_wsd_package_role', '=', 'pallet')], limit=1)

        with self.assertRaises(UserError) as ctx:
            BindLog.receive_pallets(['PLT-RG-01'])
        self.assertIn(inspection2.name, str(ctx.exception))
        # whole batch rolled back: neither order moved, pallet stays closed
        self.assertEqual(order1.x_done_qty, 0.0)
        self.assertEqual(order2.x_done_qty, 0.0)
        self.assertEqual(pallet.x_wsd_pack_state, 'closed')

    # ------------------------------------------------------------------
    # Scenario: a receipt created earlier is re-checked on validation
    # ------------------------------------------------------------------
    def test_05_receipt_revalidated_when_new_ng_arrives(self):
        order = self._order()
        self._stock_line_side(order)
        inspection = self._full_ok_round(order, 'SN-RG-401')
        self._full_ok_round(order, 'SN-RG-402')
        inspection.action_done()
        self.assertTrue(inspection.x_oqc_release_ready)
        order.action_complete(1.0, 'stock')
        receipt = self._receipt_picking(order)
        self.assertTrue(receipt)
        self.assertNotEqual(receipt.state, 'done')

        # a new NG lands on the released batch (board outside the sample)
        self._ng_round(order, 'SN-RG-403')
        self.assertFalse(inspection.x_oqc_release_ready)
        with self.assertRaises(UserError) as ctx:
            receipt.button_validate()
        self.assertIn('has not released', str(ctx.exception))
        # backend direct calls cannot bypass the creation-time check either
        with self.assertRaises(UserError):
            receipt.with_context(skip_backorder=True)._action_done()
        self.assertNotEqual(receipt.state, 'done')

    # ------------------------------------------------------------------
    # Scenario: normal release allows; scrapped SN never enters stock
    # ------------------------------------------------------------------
    def test_06_sn_level_refusals(self):
        order = self._order()
        inspection = self._ok_round(order, 'SN-RG-501')
        self._ng_round(order, 'SN-RG-502')
        ng_serial = self._identity('SN-RG-502')
        self._close_retest(inspection, ng_serial)
        inspection.action_done()
        self.assertTrue(inspection.x_oqc_release_ready)
        # clean serials pass
        order._check_oqc_receipt_release(
            serials=self._identity('SN-RG-501'))

        # a scrapped serial is refused by name even on a released batch
        scrapped = self._identity('SN-RG-502')
        scrapped.x_quality_hold_state = 'scrapped'
        with self.assertRaises(UserError) as ctx:
            order._check_oqc_receipt_release(serials=scrapped)
        self.assertIn('SN-RG-502', str(ctx.exception))
        self.assertIn('scrapped', str(ctx.exception))
        scrapped.x_quality_hold_state = 'released'

        # a serial with a re-opened disposition is refused as unresolved
        self._ng_round(order, 'SN-RG-503')
        pending = self._identity('SN-RG-503')
        with self.assertRaises(UserError) as ctx:
            order._check_oqc_receipt_release(serials=pending)
        self.assertIn('SN-RG-503', str(ctx.exception))
        self.assertIn('awaiting disposition', str(ctx.exception))

    # ------------------------------------------------------------------
    # Scenario: no-obligation and report-mode boundaries
    # ------------------------------------------------------------------
    def test_07_no_obligation_and_report_mode_not_gated(self):
        # no scheme in effect and no document -> no quality restriction
        order = self._order(qty=5)
        self.scheme.state = 'draft'
        try:
            self.assertTrue(order._check_oqc_receipt_release())
        finally:
            self.scheme.state = 'effective'
        # report mode keeps the suspended quality linkage
        report_order = self._order(mode='report', qty=5)
        self.assertTrue(report_order._check_oqc_receipt_release())
        self.assertFalse(report_order.x_oqc_inspection_ids)

    # ------------------------------------------------------------------
    # Scenario: pickings that are not MES receipts are never blocked
    # ------------------------------------------------------------------
    def test_08_material_issue_picking_not_mistaken(self):
        order = self._order()
        inspection = self._ok_round(order, 'SN-RG-601')
        self.assertFalse(inspection.x_oqc_release_ready)
        order.action_generate_picking()
        warehouse = order.production_id.picking_type_id.warehouse_id
        issue = order.picking_ids.filtered(
            lambda p: p.picking_type_id
            == warehouse.picking_type_issue_id)
        self.assertTrue(issue)
        issue = issue[:1]
        # the _action_done gate filters on this exact predicate: issue,
        # over-pick and return pickings never run the OQC release check
        self.assertFalse(issue._oqc_is_mes_receipt())

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sn_out')
class TestOutsource(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.today = fields.Date.context_today(env['sn.out.order'])
        cls.grade = env['sn.inj.material.grade'].create({
            'code': 'T-PC', 'name': 'PC 测试', 'family': 'pc', 'need_drying': True, 'dry_temp': 120,
            'dry_hours': 4, 'moisture_max': 0.02, 'hold_hours': 6, 'regrind_max_pct': 15, 'regrind_control': 'block'})
        kg = env.ref('uom.product_uom_kgm')
        cls.resin = env['product.product'].create({
            'name': '测试 PC 粒子', 'type': 'consu', 'is_storable': True, 'tracking': 'lot',
            'uom_id': kg.id, 'standard_price': 20.0})
        cls.part = env['product.product'].create({'name': '测试上盖', 'type': 'consu', 'is_storable': True})
        workshop = env['sn.mrp.workshop'].search([], limit=1)
        env['mrp.bom'].create({
            'product_tmpl_id': cls.part.product_tmpl_id.id, 'product_qty': 1000, 'x_workshop_id': workshop.id,
            'bom_line_ids': [(0, 0, {'product_id': cls.resin.id, 'product_qty': 40.0})]})   # 40 g/件
        wh = env['stock.warehouse'].search([('company_id', '=', env.company.id)], limit=1)
        cls.stock = wh.lot_stock_id
        lot = env['stock.lot'].create({'name': 'T-PC-LOT1', 'product_id': cls.resin.id})
        env['stock.quant']._update_available_quantity(cls.resin, cls.stock, 1000, lot_id=lot)
        cls.machine = env['sn.inj.machine'].create({'code': 'T-ZS-09', 'name': '测试 260T', 'tonnage': 260,
                                                     'brand': 'haitian'})
        cls.mold = env['sn.inj.mold'].create({
            'sn': 'T-MJ-OUT', 'name': '测试外借模', 'tonnage_min': 200, 'tonnage_max': 300, 'design_life': 500000,
            'maint_cycle': 50000, 'maint_remind': 5000, 'std_cycle': 30, 'grade_id': cls.grade.id,
            'product_line_ids': [(0, 0, {'product_id': cls.part.id, 'cavity_qty': 2, 'part_weight': 39})]})
        partner = env['res.partner'].create({'name': '测试代工厂甲', 'is_company': True})
        partner2 = env['res.partner'].create({'name': '测试代工厂乙', 'is_company': True})
        cls.fac = env['sn.out.factory'].create({
            'code': 'T-DGC-1', 'name': '甲厂', 'partner_id': partner.id, 'coop_state': 'qualified',
            'rating': 'A', 'rating_score': 92, 'capacity_pcs_day': 10000, 'tonnage_min': 90, 'tonnage_max': 450})
        cls.fac2 = env['sn.out.factory'].create({
            'code': 'T-DGC-2', 'name': '乙厂', 'partner_id': partner2.id, 'coop_state': 'suspended',
            'suspend_reason': '质量整改', 'rating': 'D', 'rating_score': 60, 'capacity_pcs_day': 8000})

    def _order(self, mode='consign', qty=10000, **kw):
        vals = {'factory_id': self.fac.id, 'product_id': self.part.id, 'qty': qty, 'mode': mode,
                'date_deadline': self.today + timedelta(days=10), 'date_promised': self.today + timedelta(days=9),
                'unit_price': 0.30, 'loss_rate_max': 2.0}
        if mode == 'mold_loan':
            vals['mold_id'] = self.mold.id
        vals.update(kw)
        order = self.env['sn.out.order'].create(vals)
        order.action_release()
        return order

    def _receive(self, order, qty, defects=0, disposition=None, **iqc_kw):
        rcp = self.env['sn.out.receipt'].create({'order_id': order.id, 'qty': qty})
        rcp.action_confirm()
        iqc = rcp.iqc_id
        iqc.action_pass_all_items()
        if defects:
            iqc.defect_ids = [(0, 0, {'defect_id': self.env.ref('sn_wsd_injection.defect_d01').id, 'qty': defects})]
        if iqc_kw:
            iqc.write(iqc_kw)
        iqc.action_judge(disposition=disposition)
        return rcp

    # ------------------------------------------------------------------
    def test_factory_location_and_suspended_block(self):
        self.assertTrue(self.fac.location_id)
        self.assertEqual(self.fac.location_id.usage, 'internal')
        req = self.env['sn.out.request'].create({
            'source': 'manual', 'product_id': self.part.id, 'qty': 10000,
            'date_need': self.today + timedelta(days=10), 'reason_type': 'load'})
        req.action_invite(self.fac | self.fac2)
        self.assertEqual(req.state, 'quoting')
        self.assertTrue(req.load_line_ids, '应按吨位匹配的机台评估负荷')
        q1 = req.quote_ids.filtered(lambda q: q.factory_id == self.fac)
        q2 = req.quote_ids.filtered(lambda q: q.factory_id == self.fac2)
        q1.write({'unit_price': 0.32, 'date_promise': self.today + timedelta(days=9), 'mode': 'consign'})
        q2.write({'unit_price': 0.25, 'date_promise': self.today + timedelta(days=8), 'mode': 'consign'})
        self.assertTrue(q1.is_best, '暂停代工厂即使价低也不推荐')
        with self.assertRaises(UserError):
            q2.action_award()
        q1.action_award()
        self.assertEqual(req.state, 'awarded')
        self.assertEqual(req.order_id.factory_id, self.fac)
        self.assertEqual(q2.state, 'lost')

    def test_release_creates_purchase(self):
        order = self._order(mode='turnkey', unit_price=0.80)
        self.assertEqual(order.state, 'released')
        self.assertEqual(order.purchase_id.state, 'purchase')
        self.assertEqual(order.purchase_id.order_line.price_unit, 0.80)
        self.assertEqual(order.purchase_id.order_line.product_qty, 10000)

    def test_receipt_gate_and_reject(self):
        order = self._order(mode='turnkey')
        rcp = self.env['sn.out.receipt'].create({'order_id': order.id, 'qty': 5000})
        rcp.action_confirm()
        self.assertEqual(order.state, 'partial')
        with self.assertRaises(UserError):
            rcp.action_stock_in()                     # 回货未检验不能入库
        rcp.iqc_id.action_pass_all_items()
        self.assertEqual((rcp.iqc_id.sample_code, rcp.iqc_id.sample_qty, rcp.iqc_id.ac), ('L', 200, 3))
        rcp.iqc_id.defect_ids = [(0, 0, {'defect_id': self.env.ref('sn_wsd_injection.defect_d02').id, 'qty': 6})]
        with self.assertRaises(UserError):
            rcp.iqc_id.action_judge()                 # 不合格必须选处置
        rcp.iqc_id.action_judge(disposition='return')
        self.assertEqual(rcp.iqc_id.result, 'fail')
        with self.assertRaises(UserError):
            rcp.action_stock_in()
        rcp.action_return_goods()
        self.assertEqual(rcp.state, 'returned')
        ok = self._receive(order, 5000, defects=1)
        ok.action_stock_in()
        self.assertEqual(ok.state, 'done')
        self.assertEqual(order.accepted_qty, 4999)
        self.assertEqual(order.purchase_id.order_line.qty_received, 4999)

    def test_consign_balance_excess_and_settle(self):
        order = self._order(mode='consign', qty=10000)
        order.action_create_issue()
        issue = order.issue_ids
        self.assertAlmostEqual(issue.total_qty, 408.0, places=2)    # 10000 × 0.04 × 1.02
        issue.action_done()
        quant = self.env['stock.quant']._gather(self.resin, self.fac.location_id)
        self.assertAlmostEqual(sum(quant.mapped('quantity')), 408.0, places=2)
        order.report_progress(10000, shots=5000)
        self.assertEqual(order.state, 'producing')
        rcp = self._receive(order, 10000)
        rcp.action_stock_in()
        order.action_compute_balance()
        bal = order.balance_ids
        bal.remaining_qty = 5.0
        with self.assertRaises(UserError):
            order.action_create_statement()           # 物料未平衡不能结算
        with self.assertRaises(UserError):
            bal.action_confirm()                      # 代工厂结存未退
        ret = self.env['sn.out.issue'].create({'order_id': order.id, 'kind': 'return', 'line_ids': [
            (0, 0, {'product_id': self.resin.id, 'lot_id': issue.line_ids.lot_id.id, 'qty': 5.0})]})
        ret.action_done()
        bal.remaining_qty = 0
        # 发 408 退 5，良品耗用 400，允许损耗 8 → 实际损耗 3，无超耗
        self.assertAlmostEqual(bal.std_use_qty, 400.0)
        self.assertAlmostEqual(bal.reasonable_loss_qty, 3.0)
        self.assertAlmostEqual(bal.excess_qty, 0.0)
        self.assertTrue(bal.check_ok)
        bal.action_confirm()
        self.assertEqual(order.balance_state, 'balanced')
        self.assertFalse(sum(self.env['stock.quant']._gather(self.resin, self.fac.location_id).mapped('quantity')))
        order.action_create_statement()
        st = order.statement_id
        self.assertAlmostEqual(st.amount_total, 3000.0)
        with self.assertRaises(UserError):
            order.action_done()                       # 对账单未确认
        st.action_confirm()
        order.action_done()
        self.assertEqual(order.state, 'done')

    def test_excess_deduction(self):
        order = self._order(mode='consign', qty=10000, penalty_factor=1.5)
        order.action_create_issue()
        order.issue_ids.action_done()
        rcp = self._receive(order, 9500)                 # 少交 500 件，物料全耗：超耗
        rcp.action_stock_in()
        order.action_compute_balance()
        bal = order.balance_ids
        # 发 408，良品 9500 × 0.04 = 380，允许 7.6 → 实际损耗 28，超耗 20.4，扣款 20.4 × 20 × 1.5 = 612
        self.assertAlmostEqual(bal.excess_qty, 20.4, places=2)
        self.assertAlmostEqual(bal.deduct_amount, 612.0, places=2)
        self.assertAlmostEqual(bal.issued_qty, bal.std_use_qty + bal.reasonable_loss_qty + bal.returned_qty + bal.excess_qty,
                               places=2)
        bal.action_confirm()
        with self.assertRaises(UserError):
            order.action_close()                     # 关闭须填写原因
        order.close_reason = '客户减量'
        order.action_create_statement()
        st = order.statement_id
        self.assertAlmostEqual(st.amount_goods, 2850.0)
        self.assertAlmostEqual(st.amount_excess, 612.0)
        self.assertAlmostEqual(st.amount_total, 2238.0)
        st.action_confirm()
        order.action_close()
        self.assertEqual(order.state, 'closed')

    def test_mold_loan_blocks_schedule_and_return_updates_life(self):
        order = self._order(mode='mold_loan', unit_price=1.2)
        before = self.mold.total_usage_count
        loan = order.action_loan_mold()
        self.assertEqual(self.mold.mold_state, 'loaned')
        self.assertEqual(self.mold.location_id, self.fac.location_id)
        self.assertIn('外借-甲厂', self.mold.position_text)
        rec = self.env['sn.tooling.record'].search([('tooling_id', '=', self.mold.tooling_id.id)], limit=1, order='id desc')
        self.assertIn('外借至', rec.reason)
        with self.assertRaises(ValidationError):
            self.env['sn.inj.plan'].create({'product_id': self.part.id, 'mold_id': self.mold.id,
                                            'machine_id': self.machine.id, 'planned_qty': 1000,
                                            'date_start': fields.Datetime.now()})
        with self.assertRaises(UserError):
            self.mold._mount(self.machine)
        rcp = self._receive(order, 10000)
        rcp.action_stock_in()
        with self.assertRaises(UserError):
            order.action_create_statement()           # 模具未归还不能结算
        loan.action_return(shots=5010)
        self.assertEqual(loan.state, 'returned')
        self.assertEqual(self.mold.mold_state, 'in_stock')
        self.assertEqual(self.mold.total_usage_count, before + 5010)
        self.assertFalse(self.mold.loan_id)
        plan = self.env['sn.inj.plan'].create({'product_id': self.part.id, 'mold_id': self.mold.id,
                                               'machine_id': self.machine.id, 'planned_qty': 1000,
                                               'date_start': fields.Datetime.now()})
        self.assertTrue(plan)

    def test_progress_api_and_risk(self):
        order = self._order(mode='turnkey', qty=100000, date_promised=self.today + timedelta(days=4))
        res = self.env['sn.out.progress'].api_report({'token': self.fac.api_token, 'order': order.name,
                                                       'produced_qty': 2000, 'stage': 'mass'})
        self.assertEqual(res['produced_qty'], 2000)
        self.assertEqual(order.state, 'producing')
        self.assertEqual(order.risk_level, 'high')       # 4~5 天需日产约 2 万 > 1 万
        with self.assertRaises(UserError):
            self.env['sn.out.progress'].api_report({'token': 'bad', 'order': order.name, 'produced_qty': 3000})
        with self.assertRaises(UserError):
            order.report_progress(1000)                  # 累计数不能倒退
        order._update_risk(today=self.today + timedelta(days=6))
        self.assertEqual(order.risk_level, 'overdue')

    def test_kpi_writeback_and_auto_suspend(self):
        order = self._order(mode='turnkey')
        bad = self._receive(order, 5000, defects=8, disposition='concession', concession_pct=5)
        bad.action_stock_in()
        kpis = self.env['sn.out.kpi'].compute_period(self.today.replace(day=1), self.today + timedelta(days=1))
        kpi = kpis.filtered(lambda k: k.factory_id == self.fac)
        self.assertEqual(kpi.pass_rate, 0.0)
        self.assertEqual(kpi.ontime_rate, 100.0)
        self.assertEqual(kpi.score, 60.0)
        self.assertEqual(kpi.rating, 'D')
        self.assertEqual(self.fac.rating, 'D')
        self.assertEqual(self.fac.coop_state, 'suspended')
        with self.assertRaises(UserError):
            self._order(mode='turnkey')                  # 暂停后不能下达

    def test_from_sale_and_plan(self):
        customer = self.env['res.partner'].create({'name': '测试客户', 'is_company': True})
        so = self.env['sale.order'].create({'partner_id': customer.id, 'order_line': [
            (0, 0, {'product_id': self.part.id, 'product_uom_qty': 6000, 'price_unit': 1.5})]})
        so.action_confirm()
        act = so.action_to_outsource()
        req = self.env['sn.out.request'].browse(act['res_id'])
        self.assertEqual((req.source, req.sale_line_id, req.qty), ('sale', so.order_line, 6000))
        self.assertTrue(req.load_summary)
        with self.assertRaises(UserError):
            so.action_to_outsource()                    # 同一订单行不重复外发
        plan = self.env['sn.inj.plan'].create({'product_id': self.part.id, 'mold_id': self.mold.id,
                                               'machine_id': self.machine.id, 'planned_qty': 4000,
                                               'date_start': fields.Datetime.now() + timedelta(days=1),
                                               'date_deadline': self.today + timedelta(days=8)})
        act = plan.action_to_outsource()
        req2 = self.env['sn.out.request'].browse(act['res_id'])
        self.assertEqual((req2.source, req2.plan_id), ('plan', plan))
        self.assertNotIn(plan.machine_id, req2.load_line_ids.filtered(lambda l: l.planned_hours > 0).machine_id,
                         '来源计划本身不计入本厂负荷')
        req2.action_invite(self.fac)
        req2.quote_ids.write({'unit_price': 0.3, 'date_promise': self.today + timedelta(days=7), 'mode': 'consign'})
        act = req2.quote_ids.action_award()
        order = self.env['sn.out.order'].browse(act['res_id'])
        order.action_release()
        self.assertEqual(plan.state, 'cancel', '代工单下达后来源注塑计划自动取消')

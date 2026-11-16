from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sn_inj')
class TestInjection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.grade = env['sn.inj.material.grade'].create({
            'code': 'T-ABS', 'name': 'ABS 测试', 'family': 'abs', 'need_drying': True,
            'dry_temp': 80, 'dry_hours': 2, 'moisture_max': 0.1, 'hold_hours': 4,
            'regrind_max_pct': 20, 'regrind_control': 'block'})
        cls.product = env['product.product'].create({'name': '测试外壳', 'type': 'consu'})
        cls.machine = env['sn.inj.machine'].create({
            'code': 'T-ZS-01', 'name': '测试注塑机', 'tonnage': 120, 'brand': 'haitian'})
        cls.mold = env['sn.inj.mold'].create({
            'sn': 'T-MJ-01', 'name': '测试模', 'mold_kind': 'multi', 'tonnage_min': 90, 'tonnage_max': 160,
            'design_life': 100000, 'maint_cycle': 20000, 'maint_remind': 2000,
            'runner_weight': 10.0, 'std_cycle': 20.0, 'grade_id': cls.grade.id,
            'product_line_ids': [(0, 0, {'product_id': cls.product.id, 'cavity_qty': 4, 'part_weight': 12})]})
        cls.card = env['sn.inj.process.card'].create({
            'product_id': cls.product.id, 'mold_id': cls.mold.id, 'std_cycle': 20.0})
        for line in cls.card.line_ids:
            if line.code == 'cycle':
                line.write({'std_value': 20, 'lower': 19, 'upper': 21})
            if line.code == 'hold_p1':
                line.write({'std_value': 60, 'lower': 55, 'upper': 65})
        cls.card.action_submit()
        cls.card.action_approve()
        cls.mold._mount(cls.machine)

    def _plan(self, **kw):
        vals = {'product_id': self.product.id, 'mold_id': self.mold.id, 'machine_id': self.machine.id,
                'planned_qty': 1000, 'date_start': fields.Datetime.now()}
        vals.update(kw)
        return self.env['sn.inj.plan'].create(vals)

    def test_plan_shots_and_hours(self):
        plan = self._plan(planned_qty=1001)
        self.assertEqual(plan.cavity, 4)
        self.assertEqual(plan.required_shots, 251)          # ceil(1001/4)
        self.assertAlmostEqual(plan.planned_hours, round(251 * 20 / 3600.0, 2))

    def test_report_accumulates_mold_shots(self):
        plan = self._plan()
        before_total = self.mold.total_usage_count
        rep = self.env['sn.inj.report'].create({
            'machine_id': self.machine.id, 'mold_id': self.mold.id, 'plan_id': plan.id,
            'counter_start': 1000, 'counter_end': 1250, 'shift': 'day'})
        rep.write({'defect_ids': [(0, 0, {'product_id': self.product.id,
                                          'defect_id': self.env.ref('sn_wsd_injection.defect_d01').id, 'qty': 6})]})
        rep.action_done()
        self.assertEqual(rep.shots, 250)
        self.assertEqual(rep.total_qty, 1000)
        self.assertEqual(rep.good_qty, 994)
        self.assertEqual(self.mold.total_usage_count, before_total + 250)
        self.assertEqual(self.mold.cycle_usage_count, 250)
        regrind = self.env['sn.inj.regrind'].search([('report_id', '=', rep.id)])
        self.assertAlmostEqual(regrind.qty_kg, 2.5)           # 250 模 × 10 g
        self.assertEqual(plan.good_qty, 994)

    def test_sealed_cavity_reduces_output(self):
        self.env['sn.inj.mold.seal'].create({'mold_id': self.mold.id, 'cavity_no': '#2', 'reason': '型芯拉伤',
                                             'date_seal': fields.Datetime.now() - timedelta(minutes=5)})
        self.assertEqual(self.mold.effective_cavity, 3)
        plan = self._plan(planned_qty=300)
        self.assertEqual(plan.required_shots, 100)

    def test_shot_out_of_limit(self):
        shot_ok = self.env['sn.inj.shot'].create({'machine_id': self.machine.id, 'mold_id': self.mold.id,
                                                  'cycle_time': 20.2, 'hold_pressure': 60})
        self.assertFalse(shot_ok.is_out)
        shot_bad = self.env['sn.inj.shot'].create({'machine_id': self.machine.id, 'mold_id': self.mold.id,
                                                   'cycle_time': 22.5, 'hold_pressure': 52})
        self.assertTrue(shot_bad.is_out)
        self.assertEqual(shot_bad.out_count, 2)
        self.assertTrue(shot_bad.exception_id, '超限应自动生成异常单')
        self.assertEqual(shot_bad.exception_id.production_line_id, self.machine.production_line_id)

    def _dry_ok(self):
        start = fields.Datetime.now() - timedelta(hours=3)
        d = self.env['sn.inj.drying'].create({'dryer_id': self.env['sn.inj.dryer'].create(
            {'code': 'T-GZ-01', 'name': '测试干燥机'}).id, 'grade_id': self.grade.id, 'lot_no': 'L1', 'date_start': start})
        d.action_finish(start + timedelta(hours=2.5))
        d.action_test(0.05)
        return d

    def _regrind_stock(self, kg):
        self.env['sn.inj.regrind'].create({'move_type': 'crush', 'grade_id': self.grade.id, 'qty_kg': kg})

    def test_regrind_ratio_block(self):
        self._regrind_stock(100)
        dry = self._dry_ok()
        ok = self.env['sn.inj.mix'].create({'machine_id': self.machine.id, 'grade_id': self.grade.id,
                                            'drying_id': dry.id, 'virgin_kg': 85, 'regrind_kg': 15})
        ok.action_confirm()
        self.assertEqual(ok.state, 'done')
        bad = self.env['sn.inj.mix'].create({'machine_id': self.machine.id, 'grade_id': self.grade.id,
                                             'drying_id': dry.id, 'virgin_kg': 70, 'regrind_kg': 30})
        self.assertTrue(bad.over_limit)
        with self.assertRaises(UserError):
            bad.action_confirm()
        self.grade.regrind_control = 'warn'
        bad.action_confirm()
        self.assertEqual(bad.state, 'done')
        self.assertTrue(bad.block_reason)

    def test_drying_gate(self):
        self._regrind_stock(10)
        mix = self.env['sn.inj.mix'].create({'machine_id': self.machine.id, 'grade_id': self.grade.id,
                                             'virgin_kg': 50})
        with self.assertRaises(UserError):
            mix.action_confirm()      # 未选烘干批次
        dry = self._dry_ok()
        mix.drying_id = dry
        mix.mix_time = dry.usable_until + timedelta(minutes=1)
        with self.assertRaises(UserError):
            mix.action_confirm()      # 超出可用窗口

    def test_mold_conflict_and_tonnage(self):
        self._plan(date_start=fields.Datetime.now() + timedelta(days=1))
        other = self.env['sn.inj.machine'].create({'code': 'T-ZS-02', 'name': '测试机 2', 'tonnage': 150})
        with self.assertRaises(ValidationError):
            self._plan(machine_id=other.id, date_start=fields.Datetime.now() + timedelta(days=1, hours=1))
        big = self.env['sn.inj.machine'].create({'code': 'T-ZS-03', 'name': '测试机 3', 'tonnage': 450})
        with self.assertRaises(ValidationError):
            self._plan(machine_id=big.id, date_start=fields.Datetime.now() + timedelta(days=5))

    def test_fai_gate_and_maint_block(self):
        change = self.env['sn.inj.mold.change'].create({'machine_id': self.machine.id, 'change_type': 'remount',
                                                        'mold_out_id': self.mold.id, 'mold_in_id': self.mold.id})
        change.action_start()
        change.action_mounted()
        self.assertEqual(change.state, 'fai')
        plan = self._plan()
        rep = self.env['sn.inj.report'].create({'machine_id': self.machine.id, 'mold_id': self.mold.id,
                                                'plan_id': plan.id, 'shots': 100})
        with self.assertRaises(UserError):
            rep.action_done()        # 首件未判合格
        change.fai_id.action_pass()
        self.assertEqual(change.state, 'done')
        rep.action_done()
        # 保养逾期：周期模次超过保养周期 → 排产拦截
        self.mold.tooling_id.cycle_usage_count = 25000
        with self.assertRaises(ValidationError):
            self._plan(date_start=fields.Datetime.now() + timedelta(days=10))

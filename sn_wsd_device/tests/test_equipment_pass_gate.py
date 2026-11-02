from datetime import datetime

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, freeze_time, tagged


@tagged('post_install', '-at_install')
class TestEquipmentPassGate(TransactionCase):
    """设备台账的过站闸门入口：resolve_for_pass（存在性硬拦）与
    _pass_gate_block_reason（状态闸门 + 点检/保养逾期闸门）。

    逾期用例全部冻结时钟并显式写死触发时刻参数：触发时刻按用户时区
    解析（admin 时区随库变化），必须保证确定性。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.eq_type = cls.env['sn.wsd.device.equipment.type'].create({
            'name': 'Gate Type', 'code': 'GATETYPE'})
        cls.equipment = cls.env['sn.wsd.device.equipment'].create({
            'code': 'GATE-EQ-1', 'name': 'Gate Test Device',
            'company_id': cls.company.id, 'equipment_status': 'enabled',
            'equipment_type_id': cls.eq_type.id})
        cls.check_plan = cls.env['sn.wsd.device.check.plan'].create({
            'equipment_type_id': cls.eq_type.id,
            'cycle_type': 'weekly', 'start_date': datetime(2026, 10, 1).date(),
        })

    def _set_trigger(self, value):
        self.env['ir.config_parameter'].sudo().set_param(
            'equipment_inspection_trigger_time', value)

    # ------------------------------------------------------------------
    # existence (hard rejection)
    # ------------------------------------------------------------------
    def test_resolve_for_pass_found(self):
        resolved = self.env['sn.wsd.device.equipment'].resolve_for_pass(
            'GATE-EQ-1')
        self.assertEqual(resolved, self.equipment)

    def test_resolve_for_pass_unknown_hard_rejects(self):
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.device.equipment'].resolve_for_pass('NOPE-EQ')

    def test_resolve_for_pass_scopes_to_company(self):
        """跨公司同名码不得命中：闸门按本公司解析。"""
        other = self.env['res.company'].create({'name': 'Gate Other Co'})
        self.env['sn.wsd.device.equipment'].create({
            'code': 'GATE-EQ-OTHER', 'name': 'Other Co Device',
            'company_id': other.id, 'equipment_status': 'enabled'})
        # the gate resolves in the current company: the other company's
        # row is invisible
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.device.equipment'].with_company(
                self.company).resolve_for_pass('GATE-EQ-OTHER')

    # ------------------------------------------------------------------
    # status gate
    # ------------------------------------------------------------------
    def test_pass_gate_block_reason_status(self):
        now = fields.Datetime.now()
        self.equipment.last_spot_check_date = False
        self.assertFalse(self.equipment._pass_gate_block_reason(now))
        for status in ('repair', 'sealed', 'scrapped'):
            self.equipment.equipment_status = status
            reason = self.equipment._pass_gate_block_reason(now)
            self.assertTrue(reason, 'status %s must block' % status)
            self.assertIn('GATE-EQ-1', reason)
        self.equipment.equipment_status = 'enabled'

    # ------------------------------------------------------------------
    # overdue gate (batch 2)
    # ------------------------------------------------------------------
    def test_overdue_blocks_after_trigger_time(self):
        """spec: 周点检、上次 7 天前、09:00（过 08:00 触发）→ 拦。"""
        self._set_trigger('08:00')
        self.equipment.last_spot_check_date = datetime(2026, 10, 26, 9, 0)
        with freeze_time('2026-11-02 09:00:00'):
            reason = self.equipment._pass_gate_block_reason(
                fields.Datetime.now())
        self.assertTrue(reason)
        self.assertIn('overdue', reason)
        self.assertIn('GATE-EQ-1', reason)

    def test_overdue_night_shift_exempt(self):
        """spec: 夜班时段不拦——未到每日触发时刻放行。

        触发时刻按用户时区解析；把参数设为 23:59 保证 UTC 与
        Asia/Shanghai 两种 admin 时区下 09:00 都未到触发时刻。"""
        self._set_trigger('23:59')
        self.equipment.last_spot_check_date = datetime(2026, 10, 26, 9, 0)
        with freeze_time('2026-11-02 09:00:00'):
            self.assertFalse(self.equipment._pass_gate_block_reason(
                fields.Datetime.now()))

    def test_overdue_done_today_passes(self):
        """spec: 当天已完成（last 日期=今天）→ 逾期闸门放行。"""
        self._set_trigger('08:00')
        self.equipment.last_spot_check_date = datetime(2026, 11, 2, 7, 0)
        with freeze_time('2026-11-02 09:00:00'):
            self.assertFalse(self.equipment._pass_gate_block_reason(
                fields.Datetime.now()))

    def test_overdue_not_due_today_passes(self):
        """周期未到（上次 6 天前，周计划）→ 放行。"""
        self._set_trigger('08:00')
        self.equipment.last_spot_check_date = datetime(2026, 10, 27, 9, 0)
        with freeze_time('2026-11-02 09:00:00'):
            self.assertFalse(self.equipment._pass_gate_block_reason(
                fields.Datetime.now()))

    def test_overdue_no_plan_not_managed(self):
        """spec: 无计划不管控——类型无活跃计划/设备无类型，只查存在性与状态。"""
        self._set_trigger('08:00')
        self.equipment.last_spot_check_date = datetime(2026, 10, 26, 9, 0)
        self.check_plan.active = False
        with freeze_time('2026-11-02 09:00:00'):
            self.assertFalse(self.equipment._pass_gate_block_reason(
                fields.Datetime.now()))
        self.check_plan.active = True
        self.equipment.equipment_type_id = False
        with freeze_time('2026-11-02 09:00:00'):
            self.assertFalse(self.equipment._pass_gate_block_reason(
                fields.Datetime.now()))
        self.equipment.equipment_type_id = self.eq_type

    def test_overdue_never_executed_due_from_start(self):
        """spec: 从未执行过 → 锚计划开始日（开始当天即应做，新设备先点检）。"""
        self._set_trigger('08:00')
        self.equipment.last_spot_check_date = False
        # weekly plan, started exactly 14 days before the frozen today:
        # (today - start) % 7 == 0 with no full-cycle requirement
        self.check_plan.start_date = datetime(2026, 10, 19).date()
        with freeze_time('2026-11-02 09:00:00'):
            reason = self.equipment._pass_gate_block_reason(
                fields.Datetime.now())
        self.assertTrue(reason)
        self.assertIn('never', reason)

    def test_overdue_maintenance_plan_blocks(self):
        """spec: 保养逾期同构——月保养超期未做即拦。

        月度锚点对齐：上次 8 月 2 日 + 1×3 月 = 11 月 2 日恰好到期。"""
        self.env['ir.config_parameter'].sudo().set_param(
            'equipment_maintenance_trigger_time', '08:30')
        self.env['sn.wsd.device.maint.plan'].create({
            'equipment_type_id': self.eq_type.id,
            'cycle_type': 'monthly', 'start_date': datetime(2026, 8, 1).date(),
        })
        self.equipment.last_maintenance_date = datetime(2026, 8, 2, 9, 0)
        with freeze_time('2026-11-02 09:00:00'):
            reason = self.equipment._pass_gate_block_reason(
                fields.Datetime.now())
        self.assertTrue(reason)
        self.assertIn('maintenance', reason)

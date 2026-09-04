from datetime import datetime, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestStationSource(PieceRateTestCommon):
    """piece-rate 批次4：过站模式数量来源——未结算余额（首次OK锚点去重）、
    默认带满/改小补切（FIFO 截取）、一台只付一次、超额拦截、并发复核。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.station_order = cls._make_order_common(mode='station')

    def _pass_ok(self, order, serial, operation, when, result='ok'):
        return self.env['sn.wsd.serial.operation.history'].create({
            'serial_identity_id': serial.id,
            'mes_order_id': order.id,
            'route_operation_id': self._op_row(order, operation).id,
            'result': result,
            'out_date': when,
        })

    def _serial(self, name):
        return self.env['sn.wsd.serial.identity'].create({
            'name': name, 'origin_type': 'manual'})

    def _station_settlement(self, qty=0.0):
        return self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': self.station_order.id,
            'route_operation_id': self._op_a_row(self.station_order).id,
            'qty_ok': qty,
        })

    def _seed_passes(self, count=20, base=None):
        """造 count 个 SN 的首次 OK 过站（第 3、7 个复测多一行 OK）。"""
        base = base or datetime(2026, 9, 4, 8, 0, 0)
        serials = []
        for i in range(count):
            serial = self._serial(f'PRS-SN-{i + 1:03d}')
            serials.append(serial)
            when = base + timedelta(minutes=5 * i)
            self._pass_ok(self.station_order, serial, self.op_a, when)
            if i in (2, 6):
                self._pass_ok(self.station_order, serial, self.op_a,
                              when + timedelta(minutes=1))
        return serials, base

    def test_default_full_and_dedup(self):
        """20 个 SN（复测多行）→ 未结算 20；默认带满 20，覆盖集去重。"""
        self._rate()
        serials, _ = self._seed_passes(20)
        settlement = self._station_settlement()
        self.assertAlmostEqual(settlement.unsettled_qty, 20.0)
        settlement.action_compute_from_station()
        self.assertAlmostEqual(settlement.qty_ok, 20.0)
        self.assertEqual(len(settlement.serial_identity_ids), 20)
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.amount, 6.0, places=2)
        settlement._validate_source()

    def test_partial_split_fifo(self):
        """未结算 20 改小 5 → 覆盖最早 5 台；第二单未结算 15。"""
        self._rate()
        serials, base = self._seed_passes(20)
        first = self._station_settlement(qty=5.0)
        first.action_compute_from_station()
        self.assertEqual(
            set(first.serial_identity_ids.ids),
            set(s.id for s in serials[:5]))  # base+0..20min 最早的 5 台
        second = self._station_settlement()
        self.assertAlmostEqual(second.unsettled_qty, 15.0)
        second.action_compute_from_station()
        self.assertAlmostEqual(second.qty_ok, 15.0)
        self.assertEqual(
            set(second.serial_identity_ids.ids), set(s.id for s in serials[5:]))

    def test_one_pay_per_sn(self):
        """已结算 SN 返修回流重过 OK → 不再计入未结算。"""
        self._rate()
        serials, base = self._seed_passes(5)
        first = self._station_settlement()
        first.action_compute_from_station()
        # 回流重过：SN-001 再次 OK
        self._pass_ok(self.station_order, serials[0], self.op_a,
                      base + timedelta(hours=8))
        second = self._station_settlement()
        self.assertAlmostEqual(second.unsettled_qty, 0.0)
        with self.assertRaises(UserError):
            second.action_compute_from_station()

    def test_over_quantity_blocked(self):
        """本次结算数量 > 未结算台数 → 拦截。"""
        self._rate()
        self._seed_passes(18)
        settlement = self._station_settlement(qty=100.0)
        with self.assertRaises(UserError):
            settlement.action_compute_from_station()

    def test_concurrency_clash_rejected(self):
        """两张单覆盖同一 SN → 确认复核拦截（并发开单防重）。"""
        self._rate()
        serials, _ = self._seed_passes(10)
        first = self._station_settlement()
        first.action_compute_from_station()
        # 绕过按钮手工伪造第二张同覆盖单（模拟并发窗口）
        second = self._station_settlement(qty=10.0)
        second.serial_identity_ids = [(6, 0, [s.id for s in serials])]
        second._resolve_rate_price()
        first._validate_source()  # 先到者可确认（复核只认已确认单）
        first.state = 'confirmed'
        with self.assertRaises(ValidationError):
            second._validate_source()

from datetime import datetime, timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestStationSource(PieceRateTestCommon):
    """piece-rate 批次4：过站模式数量来源——未结算余额（按每一次 OK 过站
    计件，同一 SN 复测/返修重过各算一次）、默认带满/改小补切（FIFO 截取）、
    超额拦截、并发复核。"""

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
        """造 count 个 SN 的 OK 过站（第 3、7 台各多一条复测 OK，用来验证按次数计件）。"""
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

    def test_default_full_and_pass_count(self):
        """20 个 SN、其中 2 台各多一次复测 OK → 共 22 条 OK 过站，
        未结算 22；默认带满 22，覆盖的 SN 去重后仍是 20 个。"""
        self._rate()
        serials, _ = self._seed_passes(20)
        settlement = self._station_settlement()
        self.assertAlmostEqual(settlement.unsettled_qty, 22.0)
        settlement.action_compute_from_station()
        self.assertAlmostEqual(settlement.qty_ok, 22.0)
        self.assertEqual(len(settlement.serial_history_ids), 22)
        self.assertEqual(len(settlement.serial_identity_ids), 20)
        self.assertAlmostEqual(settlement.price, 0.3)
        self.assertAlmostEqual(settlement.amount, 6.6, places=2)
        settlement._validate_source()

    def test_partial_split_fifo(self):
        """未结算 22 改小 5 → 覆盖最早 5 条过站记录；第二单未结算 17。"""
        self._rate()
        serials, base = self._seed_passes(20)
        first = self._station_settlement(qty=5.0)
        first.action_compute_from_station()
        self.assertEqual(len(first.serial_history_ids), 5)
        # 最早 5 条 = SN1、SN2、SN3、SN3 复测、SN4
        self.assertEqual(
            sorted(first.serial_identity_ids.mapped('name')),
            ['PRS-SN-001', 'PRS-SN-002', 'PRS-SN-003', 'PRS-SN-004'])
        second = self._station_settlement()
        self.assertAlmostEqual(second.unsettled_qty, 17.0)
        second.action_compute_from_station()
        self.assertAlmostEqual(second.qty_ok, 17.0)
        self.assertFalse(
            set(second.serial_history_ids.ids) & set(first.serial_history_ids.ids))

    def test_repasse_pays_again(self):
        """返修回流重过 OK → 该次过站再计一次件（不再按 SN 去重）。"""
        self._rate()
        serials, base = self._seed_passes(5)
        first = self._station_settlement()
        first.action_compute_from_station()
        # 5 台里有 1 台多一条复测 OK → 共 6 条过站记录
        self.assertAlmostEqual(first.qty_ok, 6.0)
        self._pass_ok(self.station_order, serials[0], self.op_a,
                      base + timedelta(hours=8))
        second = self._station_settlement()
        self.assertAlmostEqual(second.unsettled_qty, 1.0)
        second.action_compute_from_station()
        self.assertAlmostEqual(second.qty_ok, 1.0)
        self.assertEqual(second.serial_identity_ids.ids, serials[0].ids)

    def test_over_quantity_blocked(self):
        """本次结算数量 > 未结算台数 → 拦截。"""
        self._rate()
        self._seed_passes(18)
        settlement = self._station_settlement(qty=100.0)
        with self.assertRaises(UserError):
            settlement.action_compute_from_station()

    def test_concurrency_clash_rejected(self):
        """两张单覆盖同一批过站记录 → 确认复核拦截（并发开单防重）。"""
        self._rate()
        serials, _ = self._seed_passes(10)
        first = self._station_settlement()
        first.action_compute_from_station()
        taken = first.serial_history_ids.ids
        # 绕过按钮手工伪造第二张同覆盖单（模拟并发窗口）
        second = self._station_settlement(qty=float(len(taken)))
        second.serial_history_ids = [(6, 0, taken)]
        second.serial_identity_ids = [
            (6, 0, [s.id for s in serials])]
        second._resolve_rate_price()
        first._validate_source()  # 先到者可确认（复核只认已确认单）
        first.state = 'confirmed'
        with self.assertRaises(ValidationError):
            second._validate_source()

    def test_pending_rows_are_not_anchors(self):
        # spec: station-pass-history/spec/完成态语义对在制行不可见/产出与计件口径不变
        """pass-history-on-enter：在制行（in_progress，未出站）不进首次 OK
        锚点、不加未结算余额——没付的钱只认 OK 出站。"""
        self._rate()
        self._seed_passes(2)
        pending = self._serial('PRS-SN-WIP')
        self.env['sn.wsd.serial.operation.history'].create({
            'serial_identity_id': pending.id,
            'mes_order_id': self.station_order.id,
            'route_operation_id': self._op_a_row(self.station_order).id,
            'result': 'in_progress',
            'in_date': datetime(2026, 9, 4, 9, 0, 0),
        })
        settlement = self._station_settlement()
        self.assertAlmostEqual(settlement.unsettled_qty, 2.0)
        settlement.action_compute_from_station()
        self.assertNotIn(pending.id, settlement.serial_identity_ids.ids)

from datetime import datetime, timedelta

from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestBatchPassPayment(PieceRateTestCommon):
    """批量过站（行政補录）的 OK 行同样计件：口径只看过站结果是否为 OK，
    不再区分是现场扫出来的还是批量补录的。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.station_order = cls._make_order_common(mode='station')

    def _serial(self, name):
        return self.env['sn.wsd.serial.identity'].create({
            'name': name, 'origin_type': 'manual'})

    def _pass_ok(self, serial, when, batch_log=None):
        return self.env['sn.wsd.serial.operation.history'].create({
            'serial_identity_id': serial.id,
            'mes_order_id': self.station_order.id,
            'route_operation_id': self._op_a_row(self.station_order).id,
            'result': 'ok',
            'out_date': when,
            'x_batch_pass_log_id': batch_log and batch_log.id or False,
        })

    def test_admin_rows_pay_like_physical_rows(self):
        self._rate()
        order = self.station_order
        base = datetime(2026, 9, 4, 8, 0, 0)
        physical_1 = self._serial('BPP-P-001')
        physical_2 = self._serial('BPP-P-002')
        admin_sn = self._serial('BPP-A-001')
        log = self.env['sn.wsd.batch.pass.log'].create({
            'mes_order_id': order.id,
            'route_operation_id': self._op_a_row(order).id,
            'reason': 'equipment_failure',
            'serial_identity_ids': [(6, 0, admin_sn.ids)],
        })
        p1 = self._pass_ok(physical_1, base)
        p2 = self._pass_ok(physical_2, base + timedelta(minutes=5))
        p3 = self._pass_ok(admin_sn, base + timedelta(minutes=3), batch_log=log)
        settlement = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': order.id,
            'route_operation_id': self._op_a_row(order).id,
            'qty_ok': 0.0,
        })
        passes = settlement._station_pass_rows()
        self.assertEqual(len(passes), 3)
        self.assertIn(p1.id, passes)
        self.assertIn(p2.id, passes)
        self.assertIn(
            p3.id, passes,
            'batch-pass (administrative) OK rows pay piece rate too')
        self.assertAlmostEqual(settlement.unsettled_qty, 3.0)
        settlement.action_compute_from_station()
        self.assertAlmostEqual(settlement.qty_ok, 3.0)
        self.assertEqual(len(settlement.serial_identity_ids), 3)

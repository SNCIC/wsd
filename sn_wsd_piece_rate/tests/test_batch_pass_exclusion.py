from datetime import datetime, timedelta

from odoo.tests import tagged

from .common_piece_rate import PieceRateTestCommon


@tagged('post_install', '-at_install')
class TestBatchPassExclusion(PieceRateTestCommon):
    """批量过站（行政 OK）不进计件余额：物理过站照常计件。"""

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

    def test_admin_rows_never_anchor_a_payment(self):
        order = self.station_order
        base = datetime(2026, 9, 4, 8, 0, 0)
        physical_1 = self._serial('BPE-P-001')
        physical_2 = self._serial('BPE-P-002')
        admin_sn = self._serial('BPE-A-001')
        log = self.env['sn.wsd.batch.pass.log'].create({
            'mes_order_id': order.id,
            'route_operation_id': self._op_a_row(order).id,
            'reason': 'equipment_failure',
            'serial_identity_ids': [(6, 0, admin_sn.ids)],
        })
        self._pass_ok(physical_1, base)
        self._pass_ok(physical_2, base + timedelta(minutes=5))
        self._pass_ok(admin_sn, base + timedelta(minutes=3), batch_log=log)
        settlement = self.env['sn.wsd.piece.settlement'].create({
            'mes_order_id': order.id,
            'route_operation_id': self._op_a_row(order).id,
            'qty_ok': 0.0,
        })
        anchors = settlement._station_anchor_map()
        self.assertIn(physical_1.id, anchors)
        self.assertIn(physical_2.id, anchors)
        self.assertNotIn(
            admin_sn.id, anchors,
            'batch-pass (administrative) OK rows must never pay piece rate')

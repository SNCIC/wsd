from datetime import date, datetime

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStockBalanceDetail(TransactionCase):
    """收发汇总表与下钻明细必须同源。

    汇总视图直接从明细视图聚合，所以「明细按方向相加」必须逐位等于汇总行的
    期初/收入/发出/结存；跨仓库调拨两端各一条腿，库内调拨则两边都不出现。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env.ref('stock.warehouse0')
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.supplier_location = cls.env.ref('stock.stock_location_suppliers')
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        # 库存区（WH/库存）内的子库位：库内调拨的两端都在里面
        cls.shelf_location = cls.env['stock.location'].create({
            'name': 'Balance Detail Shelf',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.warehouse_2 = cls.env['stock.warehouse'].create({
            'name': 'Balance Detail Second WH',
            'code': 'BAL2',
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Balance Detail Product',
            'default_code': 'BAL-DETAIL-1',
            # 本库把新物料的 tracking 默认设成了 lot，这里显式关掉，
            # 让用例只验证收发口径，不依赖环境里的默认值
            'tracking': 'none',
            'is_storable': True,
        })
        # 第二个物料只在期前入库：9 月、10 月都有行，用来验行 id 不随期间漂移
        cls.product_2 = cls.env['product.product'].create({
            'name': 'Balance Detail Product 2',
            'default_code': 'BAL-DETAIL-2',
            'tracking': 'none',
            'is_storable': True,
        })
        # 固定流水时间，测试不受执行时刻与时区边界影响
        cls.date_before = datetime(2025, 8, 10, 3, 0)
        cls.date_in = datetime(2025, 9, 10, 3, 0)
        cls.date_out = datetime(2025, 9, 11, 3, 0)
        cls.date_internal = datetime(2025, 9, 12, 3, 0)
        cls.date_other_warehouse = datetime(2025, 10, 5, 3, 0)

        # 期初：区间开始日之前入库 10
        cls.picking, cls.move_before = cls._make_move(
            cls, 10, cls.supplier_location, cls.stock_location,
            cls.date_before, cls.warehouse.in_type_id,
        )
        # 期内：入库 5、出库 4、库内调拨 3（不计收发）
        cls.move_in = cls._make_move(
            cls, 5, cls.supplier_location, cls.stock_location,
            cls.date_in, cls.warehouse.in_type_id,
        )[1]
        cls.move_out = cls._make_move(
            cls, 4, cls.stock_location, cls.customer_location,
            cls.date_out, cls.warehouse.out_type_id,
        )[1]
        cls.move_internal = cls._make_move(
            cls, 3, cls.stock_location, cls.shelf_location,
            cls.date_internal, cls.warehouse.int_type_id,
        )[1]
        # 区外：跨仓库调拨 7（主仓记发出、第二仓记收入）
        cls.move_cross_warehouse = cls._make_move(
            cls, 7, cls.stock_location, cls.warehouse_2.lot_stock_id,
            cls.date_other_warehouse, cls.warehouse.int_type_id,
        )[1]
        cls._make_move(
            cls, 2, cls.supplier_location, cls.stock_location,
            datetime(2025, 8, 11, 3, 0), cls.warehouse.in_type_id,
            product=cls.product_2,
        )
        cls._set_range(cls, date(2025, 9, 1), date(2025, 9, 30))

    def _make_move(self, quantity, location, location_dest, date, picking_type, product=None):
        """按单据流程做出库/入库/调拨，并把流水时间固定到指定时刻。

        入库单额外建一张调拨单，用来验证明细能下钻回单据。
        """
        product = product or self.product
        picking = False
        if picking_type.code == 'incoming':
            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'location_id': location.id,
                'location_dest_id': location_dest.id,
            })
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'location_id': location.id,
            'location_dest_id': location_dest.id,
            'picking_type_id': picking_type.id,
            'picking_id': picking.id if picking else False,
        })
        move._action_confirm()
        move._action_assign()
        # 不依赖预留结果，直接把完成数量写死在行上
        move._set_quantity_done(quantity)
        move.picked = True
        move._action_done()
        move.move_line_ids.write({'date': date})
        return picking, move

    def _set_range(self, date_from, date_to):
        self.env['sn.wsd.stock.balance.range']._current(self.env).write({
            'date_from': date_from,
            'date_to': date_to,
        })
        self.env.flush_all()
        self.env['sn.wsd.stock.balance.report'].invalidate_model()

    def _report_row(self, warehouse, product=None):
        rows = self.env['sn.wsd.stock.balance.report'].search([
            ('product_id', '=', (product or self.product).id),
            ('warehouse_id', '=', warehouse.id),
        ])
        self.assertEqual(len(rows), 1, '该物料在该仓库应只有一行汇总')
        return rows

    def _details(self, warehouse, date_from, date_to):
        return self.env['sn.wsd.stock.balance.detail'].search([
            ('product_id', '=', self.product.id),
            ('warehouse_id', '=', warehouse.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ])

    def test_detail_reconciles_with_summary(self):
        report = self._report_row(self.warehouse)
        self.assertEqual(report.default_code, 'BAL-DETAIL-1')
        self.assertAlmostEqual(report.qty_initial, 10.0)
        self.assertAlmostEqual(report.qty_in, 5.0)
        self.assertAlmostEqual(report.qty_out, 4.0)
        self.assertAlmostEqual(report.qty_balance, 11.0)

        details = self._details(self.warehouse, date(2025, 9, 1), date(2025, 9, 30))
        # 库内调拨不出现在明细里，所以期内只有入库、出库两条
        self.assertEqual(len(details), 2)
        self.assertAlmostEqual(
            sum(details.filtered(lambda d: d.direction == 'in').mapped('quantity')),
            report.qty_in,
        )
        self.assertAlmostEqual(
            sum(details.filtered(lambda d: d.direction == 'out').mapped('quantity')),
            report.qty_out,
        )
        self.assertNotIn(self.shelf_location, details.mapped('location_dest_id'))

        # 期初等于区间之前明细的净流入
        initial_details = self._details(self.warehouse, date(2025, 8, 1), date(2025, 8, 31))
        self.assertEqual(len(initial_details), 1)
        self.assertEqual(initial_details.direction, 'in')
        self.assertAlmostEqual(sum(initial_details.mapped('quantity')), report.qty_initial)

    def test_open_details_uses_report_period(self):
        report = self._report_row(self.warehouse)
        # 参数表故意指向别的期间：下钻要跟着生成报表时那份区间，才对得上眼前看到的数字
        self._set_range(date(2025, 10, 1), date(2025, 10, 31))
        action = report.with_context(
            sn_wsd_balance_date_from='2025-09-01',
            sn_wsd_balance_date_to='2025-09-30',
        ).action_open_details()
        self.assertEqual(action['res_model'], 'sn.wsd.stock.balance.detail')
        self.assertEqual(action['view_mode'], 'list')
        self.assertIn(('product_id', '=', self.product.id), action['domain'])
        self.assertIn(('warehouse_id', '=', self.warehouse.id), action['domain'])
        self.assertEqual(
            len(self.env['sn.wsd.stock.balance.detail'].search(action['domain'])), 2,
        )

        # 环境里没有报表区间时才回落到参数表（此时是 10 月，只剩跨仓库调拨的发出）
        fallback = report.action_open_details()
        fallback_details = self.env['sn.wsd.stock.balance.detail'].search(fallback['domain'])
        self.assertEqual(len(fallback_details), 1)
        self.assertEqual(fallback_details.direction, 'out')

    def test_row_id_survives_period_change(self):
        """行 id 必须只由「物料 × 仓库」决定。

        区间一变，进出区间的物料会让报表行数变化；行 id 若跟着重新编号，
        用户点开的就是另一颗物料的明细。
        """
        product_row = self._report_row(self.warehouse, self.product)
        product_2_row = self._report_row(self.warehouse, self.product_2)
        self.assertNotEqual(product_row.id, product_2_row.id)
        self._set_range(date(2025, 10, 1), date(2025, 10, 31))
        self.assertEqual(
            self._report_row(self.warehouse, self.product).id, product_row.id,
        )
        self.assertEqual(
            self._report_row(self.warehouse, self.product_2).id, product_2_row.id,
        )

    def test_cross_warehouse_transfer_has_two_legs(self):
        self._set_range(date(2025, 10, 1), date(2025, 10, 31))
        move_lines = self.move_cross_warehouse.move_line_ids
        details = self.env['sn.wsd.stock.balance.detail'].search([
            ('move_line_id', 'in', move_lines.ids),
        ])
        # 一笔跨仓库调拨在两端各出一条明细
        self.assertEqual(len(details), 2)
        self.assertEqual(set(details.mapped('direction')), {'in', 'out'})
        self.assertEqual(
            details.filtered(lambda d: d.direction == 'out').warehouse_id, self.warehouse,
        )
        self.assertEqual(
            details.filtered(lambda d: d.direction == 'in').warehouse_id, self.warehouse_2,
        )
        out_report = self._report_row(self.warehouse)
        in_report = self._report_row(self.warehouse_2)
        self.assertAlmostEqual(out_report.qty_out, 7.0)
        self.assertAlmostEqual(out_report.qty_in, 0.0)
        self.assertAlmostEqual(in_report.qty_in, 7.0)
        # 第二仓没有期初：主仓 8 月的入库不应算到第二仓头上
        self.assertAlmostEqual(in_report.qty_initial, 0.0)

    def test_open_document(self):
        incoming = self._details(self.warehouse, date(2025, 9, 1), date(2025, 9, 30)).filtered(
            lambda d: d.move_line_id in self.move_in.move_line_ids,
        )
        self.assertEqual(len(incoming), 1)
        action = incoming.action_open_document()
        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['res_id'], self.move_in.picking_id.id)

        # 库存调整这类流水没有单据（本库 14822 条已完成流水里有 172 条如此），
        # 这时退回打开库存流水本身。先改再查，避免读到明细视图缓存里的旧值。
        self.move_cross_warehouse.move_line_ids.picking_id = False
        # Odoo 19 的写入是延迟的，视图（SQL）要等 flush 之后才看得到
        self.env.flush_all()
        outgoing = self._details(
            self.warehouse, date(2025, 10, 1), date(2025, 10, 31),
        ).filtered(lambda d: d.direction == 'out')
        self.assertEqual(len(outgoing), 1)
        action = outgoing.action_open_document()
        self.assertEqual(action['res_model'], 'stock.move.line')
        self.assertEqual(action['res_id'], self.move_cross_warehouse.move_line_ids.id)

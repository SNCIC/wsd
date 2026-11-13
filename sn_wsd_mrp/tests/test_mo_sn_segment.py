from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMoSnSegment(TransactionCase):
    """mo-sn-segment（制造订单 SN 号段登记）：

    - 一段式可选登记：两端成对填写，均可空 = 无号段订单；
    - 两端必须是标准 SN（12 位数字、首位 1/2，与过站格式闸同一把尺）；
    - 起始 ≤ 结束（定长 12 位字典序 = 数值序，1 头段恒低于 2 头段）；
    - 全公司跨 MO 不重叠（含已取消单，无释放逻辑），报错带出冲突方；
    - 输入两端自动去空白；
    - 段长 = 结束 - 起始 + 1，不校验与计划数量的关系（会发超）。
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.product = cls.env['product.product'].create({
            'name': 'SN Segment Meter',
            'default_code': 'SEGSN-01',
        })

    def _create_mo(self, **values):
        values.setdefault('product_id', self.product.id)
        values.setdefault('product_qty', 100)
        values.setdefault('company_id', self.company.id)
        return self.env['mrp.production'].create(values)

    def test_segment_optional(self):
        """两端留空 = 不需要号段的订单，保存通过且不参与校验。"""
        mo = self._create_mo()
        self.assertFalse(mo.x_sn_segment_start)
        self.assertFalse(mo.x_sn_segment_end)
        self.assertEqual(mo.x_sn_segment_length, 0)
        mo.write({'x_sn_segment_start': False, 'x_sn_segment_end': False})

    def test_pair_required(self):
        """只填一端报错（成对填写）。"""
        with self.assertRaises(ValidationError) as ctx:
            self._create_mo(x_sn_segment_start='126110003668')
        self.assertIn('pair', str(ctx.exception))
        with self.assertRaises(ValidationError):
            self._create_mo(x_sn_segment_end='126110003668')

    def test_format_rejected(self):
        """非标准格式（11 位 / 首位 3 / 含字母）报错。"""
        for bad in ('12611003668', '326110003668', '12611000366X'):
            with self.assertRaises(ValidationError) as ctx:
                self._create_mo(
                    x_sn_segment_start=bad, x_sn_segment_end='126110004668')
            self.assertIn('standard format', str(ctx.exception))

    def test_start_after_end_rejected(self):
        """起始 > 结束报错。"""
        with self.assertRaises(ValidationError) as ctx:
            self._create_mo(
                x_sn_segment_start='126110004668',
                x_sn_segment_end='126110003668')
        self.assertIn('starts after it ends', str(ctx.exception))

    def test_valid_segment_and_length(self):
        """合法号段保存通过，段长 = 差值 + 1（可大于计划数量，发超）。"""
        mo = self._create_mo(
            x_sn_segment_start='126110003668',
            x_sn_segment_end='126110004668')
        self.assertEqual(mo.x_sn_segment_length, 1001)

    def test_overlap_rejected_with_conflict_info(self):
        """与已有号段重叠报错，带出冲突 MO 及其区间。"""
        first = self._create_mo(
            x_sn_segment_start='126110003668',
            x_sn_segment_end='126110004668')
        with self.assertRaises(ValidationError) as ctx:
            self._create_mo(
                x_sn_segment_start='126110003700',
                x_sn_segment_end='126110003800')
        message = str(ctx.exception)
        self.assertIn(first.display_name, message)
        self.assertIn('126110003668', message)
        self.assertIn('126110004668', message)

    def test_modify_to_conflict_rejected(self):
        """修改已有单造成冲突同样报错。"""
        self._create_mo(
            x_sn_segment_start='126110003668',
            x_sn_segment_end='126110004668')
        second = self._create_mo(
            x_sn_segment_start='126110005000',
            x_sn_segment_end='126110005100')
        with self.assertRaises(ValidationError):
            second.write({'x_sn_segment_start': '126110004000'})

    def test_adjacent_and_other_head_allowed(self):
        """紧接其后与另一首位（2 头）区间通过。"""
        self._create_mo(
            x_sn_segment_start='126110003668',
            x_sn_segment_end='126110004668')
        self._create_mo(
            x_sn_segment_start='126110004669',
            x_sn_segment_end='126110005668')
        self._create_mo(
            x_sn_segment_start='226110003668',
            x_sn_segment_end='226110004168')

    def test_cancelled_mo_still_occupies(self):
        """取消的 MO 仍占用号段（无释放逻辑，让段靠手工清空）。"""
        first = self._create_mo(
            x_sn_segment_start='126110003668',
            x_sn_segment_end='126110004668')
        first.action_cancel()
        with self.assertRaises(ValidationError):
            self._create_mo(
                x_sn_segment_start='126110004000',
                x_sn_segment_end='126110004100')

    def test_bounds_stripped(self):
        """输入两端自动去空白后再校验/存储。"""
        mo = self._create_mo(
            x_sn_segment_start=' 126110003668 ',
            x_sn_segment_end=' 126110004668\n')
        self.assertEqual(mo.x_sn_segment_start, '126110003668')
        self.assertEqual(mo.x_sn_segment_end, '126110004668')
        self.assertEqual(mo.x_sn_segment_length, 1001)

    def test_copy_does_not_duplicate_segment(self):
        """复制 MO 不带号段（copy=False），避免一复制就重叠。"""
        self._create_mo(
            x_sn_segment_start='126110003668',
            x_sn_segment_end='126110004668')
        clone = self.env['mrp.production'].search([
            ('x_sn_segment_start', '=', '126110003668')], limit=1).copy()
        self.assertFalse(clone.x_sn_segment_start)
        self.assertFalse(clone.x_sn_segment_end)

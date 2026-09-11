from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSamplingStats(TransactionCase):
    """抽样样本统计（iqc/oqc 聚合 qty 口径回归）：ipqc 异常驱动重构不波及。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'STATS NG', 'code': 'STATS-NG',
            'category': 'other', 'severity': 'minor',
        })

    def _assert_qty_sum_caliber(self, inspection_type):
        # 口径：样本行可代表聚合数量（无 SN 跟踪时一行多台）——已检/不良
        # = pass/fail 行的 qty 求和，pending 行不参与
        inspection = self.env['sn.wsd.quality.inspection'].create({
            'inspection_type': inspection_type,
        })
        Sample = self.env['sn.wsd.quality.inspection.sample']
        Sample.create({'inspection_id': inspection.id, 'result': 'pass'})
        Sample.create({'inspection_id': inspection.id, 'result': 'fail',
                       'defect_code_id': self.defect.id, 'qty': 5})
        Sample.create({'inspection_id': inspection.id, 'result': 'pending',
                       'qty': 2})
        inspection.invalidate_recordset()
        self.assertEqual(inspection.sample_checked_qty, 6,
                         'checked = qty sum of pass/fail rows (1 + 5)')
        self.assertEqual(inspection.sample_defect_qty, 5,
                         'defect = qty sum of fail rows')

    def test_iqc_sample_stats_keep_qty_sum_caliber(self):
        self._assert_qty_sum_caliber('iqc')

    def test_oqc_sample_stats_keep_qty_sum_caliber(self):
        self._assert_qty_sum_caliber('oqc')

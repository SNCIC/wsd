from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSamplingStats(TransactionCase):
    """抽样样本统计（iqc/oqc 旧口径回归）：ipqc 异常驱动重构不波及。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'STATS NG', 'code': 'STATS-NG',
            'category': 'other', 'severity': 'minor',
        })

    def _assert_row_count_caliber(self, inspection_type):
        # 旧口径：已检=有 pass/fail 结果的行数，缺陷=fail 行数——qty 不参与
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
        self.assertEqual(inspection.sample_checked_qty, 2,
                         'checked = rows carrying a pass/fail result')
        self.assertEqual(inspection.sample_defect_qty, 1,
                         'defect = fail row count; qty does not participate')

    def test_iqc_sample_stats_keep_row_count_caliber(self):
        self._assert_row_count_caliber('iqc')

    def test_oqc_sample_stats_keep_row_count_caliber(self):
        self._assert_row_count_caliber('oqc')

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMatrixRegression(TransactionCase):
    """FAI 检验矩阵不回归（fai-inspection-matrix）：iqc/oqc/ipqc 原口径不变。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'MTX REG NG', 'code': 'MTXREG-NG',
            'category': 'other', 'severity': 'minor',
        })

    def _inspection(self, inspection_type, extra=None):
        values = {'inspection_type': inspection_type}
        if extra:
            values.update(extra)
        return self.env['sn.wsd.quality.inspection'].create(values)

    def _line(self, inspection, code):
        return inspection.line_ids.filtered(
            lambda l: l.item_code == code)[:1]

    # ---------------- iqc：line 手填口径 ----------------
    def test_10_iqc_lines_keep_manual_caliber(self):
        # line.result 手填口径原样（数值比对/手填判定），矩阵格不波及
        inspection = self._inspection('iqc', {'line_ids': [
            (0, 0, {'name': 'Appearance', 'item_code': 'IQC-MREG-APP',
                    'item_type': 'pass_fail'}),
            (0, 0, {'name': 'Length', 'item_code': 'IQC-MREG-LEN',
                    'item_type': 'numeric', 'lower_limit': 5.0,
                    'upper_limit': 6.0}),
        ]})
        appearance = self._line(inspection, 'IQC-MREG-APP')
        length = self._line(inspection, 'IQC-MREG-LEN')
        appearance.write({'is_checked': True, 'manual_result': 'pass'})
        length.write({'is_checked': True, 'measured_value': 5.5})
        self.assertEqual(appearance.result, 'pass',
                         'the manual pass keeps judging the line')
        self.assertEqual(length.result, 'pass',
                         'an in-range measurement passes the line')
        self.assertEqual(inspection.result, 'pass')
        length.write({'measured_value': 7.0})
        self.assertEqual(length.result, 'fail',
                         'an over-limit measurement fails the line')
        self.assertEqual(inspection.result, 'partial')
        appearance.write({'manual_result': 'fail'})
        self.assertEqual(appearance.result, 'fail',
                         'the manual fail keeps judging the line')
        self.assertEqual(inspection.result, 'fail')
        self.assertFalse(inspection.cell_ids,
                         'matrix cells stay FAI-only')
        self.assertFalse(inspection.line_ids.mapped('cell_ids'),
                         'iqc lines never grow result cells')

    # ---------------- oqc：done 时 AQL 判定 ----------------
    def _oqc_with_samples(self, results):
        # 无既有 oqc 用例，按 _compute_result 的 oqc 分支直建：
        # 2 样本、accept 0 / reject 1 → 缺陷过线 reject、未过线 pass
        inspection = self._inspection('oqc', {
            'sample_size': 2, 'accept_qty': 0, 'reject_qty': 1,
            'line_ids': [(0, 0, {'name': 'Visual', 'item_code': 'OQC-MREG-VIS',
                                 'item_type': 'pass_fail'})],
        })
        inspection.line_ids.write(
            {'is_checked': True, 'manual_result': 'pass'})
        Sample = self.env['sn.wsd.quality.inspection.sample']
        for result in results:
            Sample.create({
                'inspection_id': inspection.id, 'result': result,
                'defect_code_id': self.defect.id if result == 'fail' else False,
            })
        inspection.invalidate_recordset()
        return inspection

    def test_20_oqc_done_keeps_aql_verdict(self):
        # done 时按 accept/reject 的 AQL 判定口径不变（口径=样本行数）
        rejected = self._oqc_with_samples(['fail', 'fail'])
        rejected.action_done()
        rejected.invalidate_recordset()
        self.assertEqual(rejected.state, 'done')
        self.assertEqual(rejected.result, 'reject',
                         'fail samples over the reject qty reject the lot')
        accepted = self._oqc_with_samples(['pass', 'pass'])
        accepted.action_done()
        accepted.invalidate_recordset()
        self.assertEqual(accepted.state, 'done')
        self.assertEqual(accepted.result, 'pass',
                         'defects within the accept qty pass the lot')
        self.assertFalse(accepted.cell_ids | rejected.cell_ids,
                         'matrix cells stay FAI-only')

    # ---------------- ipqc：样本统计口径 ----------------
    def test_30_ipqc_sample_stats_keep_caliber(self):
        # 上次变更（add-mes-ipqc-patrol）的统计口径不受格存在影响：
        # 已检=实际抽取数（未填回退方案样本量）、缺陷=无 SN fail 行 qty 累加
        inspection = self._inspection('ipqc', {
            'sample_size': 3,
            'line_ids': [(0, 0, {'name': 'Paste thickness',
                                 'item_code': 'IPQC-MREG-PST',
                                 'item_type': 'numeric', 'lower_limit': 0.1,
                                 'upper_limit': 0.2})],
        })
        inspection.line_ids.write(
            {'is_checked': True, 'measured_value': 0.15})
        self.assertEqual(inspection.line_ids.result, 'pass',
                         'the line judge caliber is untouched by the matrix')
        Sample = self.env['sn.wsd.quality.inspection.sample']
        Sample.create({'inspection_id': inspection.id, 'result': 'fail',
                       'defect_code_id': self.defect.id, 'qty': 3})
        Sample.create({'inspection_id': inspection.id, 'result': 'pass'})
        inspection.invalidate_recordset()
        self.assertEqual(inspection.sample_checked_qty, 3,
                         'checked falls back to the sample size '
                         'when nothing was picked')
        self.assertEqual(inspection.sample_defect_qty, 3,
                         'defect = SN-less fail quantities only')
        inspection.write({'x_picked_qty': 5})
        inspection.invalidate_recordset()
        self.assertEqual(inspection.sample_checked_qty, 5,
                         'checked follows the picked qty')
        self.assertEqual(inspection.sample_defect_qty, 3,
                         'defect ignores the picked qty')
        self.assertFalse(inspection.cell_ids,
                         'ipqc never grows matrix cells')

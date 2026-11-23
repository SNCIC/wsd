from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestNqiCallback(TransactionCase):

    def _pushed_row_and_log(self):
        row = self.env['sn.wsd.nqi.rd.product.info'].create({
            'product_code': 'CB-1',
            'product_type': 'T',
            'product_name': 'N',
            'product_categid': '101',
            'product_design_basis': 'GB',
        })
        log = self.env['sn.wsd.nqi.push.log'].create({
            'model_name': row._name,
            'row_ids': str(row.id),
            'state': 'success',
        })
        row.write({'push_state': 'pushed', 'notice_no': log.notice_no})
        return row, log

    def test_success_callback_marks_processed(self):
        row, log = self._pushed_row_and_log()
        self.env['sn.wsd.nqi.push.log'].process_callback(
            log.notice_no, '1', '上传成功！')
        self.assertEqual(row.handle_flag, '1')  # 处理完成
        self.assertTrue(row.handle_date)
        self.assertEqual(row.push_state, 'pushed')
        self.assertEqual(log.callback_flag, '1')
        self.assertEqual(log.callback_msg, '上传成功！')

    def test_failure_callback_reopens_rows(self):
        row, log = self._pushed_row_and_log()
        self.env['sn.wsd.nqi.push.log'].process_callback(
            log.notice_no, '0',
            '生产企业编号 ENTERPRISE_CODE 字段有误，应为 11059')
        self.assertEqual(row.handle_flag, '3')  # 异常
        self.assertEqual(row.push_state, 'failed')  # withdraw-fix-repush
        self.assertEqual(log.callback_flag, '0')
        # after fixing, the standard withdraw path applies again
        row.action_withdraw()
        self.assertEqual(row.push_state, 'draft')

    def test_pushed_rows_still_frozen_for_users(self):
        row, _log = self._pushed_row_and_log()
        with self.assertRaises(UserError):
            row.write({'product_name': 'X'})

    def test_unknown_notice_rejected(self):
        with self.assertRaises(UserError):
            self.env['sn.wsd.nqi.push.log'].process_callback(
                '00000000-0000-0000-0000-000000000000', '1', 'x')

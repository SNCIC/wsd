from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestNqiPush(TransactionCase):
    """State machine closure, payload reflection, claim/push behavior."""

    def _product_row(self, code):
        return self.env['sn.wsd.nqi.rd.product.info'].create({
            'product_code': code,
            'product_type': 'DDSU666',
            'product_name': 'Meter %s' % code,
            'product_categid': '101',
            'product_design_basis': 'GB/T 17215',
        })

    def _config(self, **extra):
        config = self.env['sn.wsd.nqi.config'].search([
            ('company_id', '=', self.env.company.id)], limit=1)
        if not config:
            config = self.env['sn.wsd.nqi.config'].create({
                'company_id': self.env.company.id,
                'enterprise_code': '88888',
            })
        if extra:
            config.write(extra)
        return config

    def test_payload_keys_mirror_docx_columns(self):
        self._config()
        row = self._product_row('PAY-1')
        payload = row._nqi_payload()
        self.assertEqual(payload['PRODUCT_CODE'], 'PAY-1')
        self.assertEqual(payload['PRODUCT_NAME'], 'Meter PAY-1')
        self.assertIn('PRODUCT_DESIGN_BASIS', payload)
        self.assertIn('ENTERPRISE_CODE', payload)
        self.assertIn('WRITE_DATE', payload)  # nqi_write_date mapping
        # anchors and bookkeeping stay out
        self.assertNotIn('PRODUCT_ID', payload)
        self.assertNotIn('MISSING_COUNT', payload)
        self.assertNotIn('PUSH_STATE', payload)

    def test_withdraw_and_pushed_freeze(self):
        self._config()
        row = self._product_row('PAY-2')
        row.action_mark_to_push()
        self.assertEqual(row.push_state, 'to_push')
        row.action_withdraw()
        self.assertEqual(row.push_state, 'draft')
        # pushed rows are frozen
        row.action_mark_to_push()
        row.write({'push_state': 'pushed'})
        with self.assertRaises(UserError):
            row.write({'product_name': 'X'})
        with self.assertRaises(UserError):
            row.unlink()

    def test_push_without_api_leaves_rows_pending(self):
        self._config()  # no api_base_url: transport not configured
        row = self._product_row('PAY-3')
        row.action_mark_to_push()
        message = self.env['sn.wsd.nqi.worker'].run_push(
            'sn.wsd.nqi.rd.product.info')
        self.assertIn('No push API configured', message)
        self.assertEqual(row.push_state, 'to_push')

    def test_claim_is_atomic_on_state(self):
        row = self._product_row('PAY-4')
        row.write({'push_state': 'to_push'})
        worker = self.env['sn.wsd.nqi.worker']
        claimed = worker._claim(row)
        self.assertEqual(claimed.ids, row.ids)
        self.assertEqual(row.push_state, 'pushing')
        # a second claim on already-pushing rows gets nothing
        again = worker._claim(row)
        self.assertFalse(again.ids)

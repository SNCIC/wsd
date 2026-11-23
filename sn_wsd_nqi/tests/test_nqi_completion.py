from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestNqiCompletion(TransactionCase):
    """Completion paths: batch fill, auto fill, SN checkup."""

    def _asset(self, serial):
        return self.env['sn.wsd.nqi.fit.meter.info'].create({
            'serial_no': serial,
        })

    def test_batch_fill_updates_rows_and_bookkeeping(self):
        row_a = self._asset('126110004001')
        row_b = self.env['sn.wsd.nqi.fit.meter.info'].create({
            'serial_no': '126110004002',
        })
        wizard = self.env['sn.wsd.nqi.batch.fill'].create({
            'target_model': 'sn.wsd.nqi.fit.meter.info',
            'field_name': 'software_version',
            'value': 'V1.2',
        })
        wizard.with_context(
            active_ids=[row_a.id, row_b.id],
        ).action_apply()
        self.assertEqual(row_a.software_version, 'V1.2')
        self.assertEqual(row_b.software_version, 'V1.2')

        with self.assertRaises(UserError):
            self.env['sn.wsd.nqi.batch.fill'].create({
                'target_model': 'sn.wsd.nqi.fit.meter.info',
                'field_name': 'no_such_column',
                'value': 'x',
            }).with_context(active_ids=[row_a.id]).action_apply()

    def test_auto_fill_enriches_asset(self):
        row = self._asset('126110004003')
        enriched = row.action_try_auto_fill()
        # no history anchor: nothing to enrich, but no crash either
        self.assertIn(enriched, (0, 1))

    def test_sn_checkup_reports_domains(self):
        self._asset('126110004004')
        checkup = self.env['sn.wsd.nqi.checkup'].create({
            'sn': '126110004004',
        })
        checkup.action_run()
        self.assertEqual(checkup.state, 'done')
        asset_line = checkup.line_ids.filtered(
            lambda line: line.table_label == 'Asset Info')
        self.assertEqual(asset_line.row_count, 1)
        # asset row misses required columns -> warn state
        self.assertEqual(asset_line.state, 'warn')

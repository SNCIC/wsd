from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestNqiCompletion(TransactionCase):
    """Completion paths: batch fill, auto fill, SN checkup."""

    def _asset(self, serial):
        return self.env['sn.wsd.nqi.fit.meter.info'].create({
            'serial_no': serial,
        })

    def test_batch_fill_updates_rows_and_bookkeeping(self):
        Model = self.env['sn.wsd.nqi.fit.meter.info']
        row_a = self._asset('126110004001')
        row_b = Model.create({'serial_no': '126110004002',
                              'software_version': 'V1.0'})
        row_c = Model.create({'serial_no': '126110004003'})
        row_c.write({'push_state': 'pushed'})
        column = self.env['ir.model.fields'].search([
            ('model', '=', Model._name), ('name', '=', 'software_version')])
        wizard = self.env['sn.wsd.nqi.batch.fill'].create({
            'target_model': Model._name,
            'field_id': column.id,
            'value': 'V1.2',
        })
        wizard.with_context(
            active_ids=[row_a.id, row_b.id, row_c.id],
        ).action_apply()
        self.assertEqual(row_a.software_version, 'V1.2')
        self.assertEqual(row_b.software_version, 'V1.0')  # only empty cells
        self.assertFalse(row_c.software_version)  # pushed: read-only

        # overwrite mode reaches rows that already carry a value
        self.env['sn.wsd.nqi.batch.fill'].create({
            'target_model': Model._name,
            'field_id': column.id,
            'value': 'V1.3',
            'only_empty': False,
        }).with_context(active_ids=[row_a.id, row_b.id]).action_apply()
        self.assertEqual(row_a.software_version, 'V1.3')
        self.assertEqual(row_b.software_version, 'V1.3')
        with self.assertRaises(UserError):
            self.env['sn.wsd.nqi.batch.fill'].create({
                'target_model': Model._name,
                'field_id': column.id,
                'value': 'x',
            }).with_context(
                active_ids=[row_b.id, row_c.id]).action_apply()
        # the missing bookkeeping ignores the filled optional column
        self.assertEqual(row_a.missing_count, 5)

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

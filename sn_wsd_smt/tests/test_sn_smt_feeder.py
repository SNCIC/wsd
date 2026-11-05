from datetime import date, timedelta

import psycopg2

from odoo import Command, exceptions
from odoo.tests.common import TransactionCase


class TestSnSmtFeeder(TransactionCase):

    def _create_feeder(self, sn, channel_type='single', channels=None, **vals):
        if channels is None:
            channels = [sn]
        return self.env['sn.smt.feeder'].create({
            'feeder_sn': sn,
            'channel_type': channel_type,
            'channel_ids': [
                Command.create({'channel_no': i + 1, 'channel_sn': csn})
                for i, csn in enumerate(channels)
            ],
            **vals,
        })

    def test_name_is_feeder_sn(self):
        feeder = self._create_feeder('FDR-N1')
        self.assertEqual(feeder.name, 'FDR-N1')

    def test_channel_count_mismatch(self):
        with self.assertRaises(exceptions.ValidationError):
            self._create_feeder('FDR-T1', channel_type='triple', channels=['FDR-T1-1'])

    def test_channel_sn_unique(self):
        self._create_feeder('FDR-A', channels=['CH-X'])
        with self.assertRaises(psycopg2.IntegrityError):
            with self.env.cr.savepoint():
                self._create_feeder('FDR-B', channels=['CH-X'])

    def test_lifecycle_flow(self):
        feeder = self._create_feeder('FDR-L1')
        self.assertEqual(feeder.status, 'normal')
        feeder.action_disable()
        self.assertEqual(feeder.status, 'disabled')
        feeder.action_enable()
        self.assertEqual(feeder.status, 'normal')
        feeder.action_report_repair('nozzle jam')
        self.assertEqual(feeder.status, 'in_repair')
        repair = self.env['sn.smt.feeder.repair'].search([('feeder_id', '=', feeder.id)])
        self.assertEqual(repair.fault_desc, 'nozzle jam')
        self.assertFalse(repair.done_at)
        feeder.action_complete_repair('replaced nozzle')
        self.assertEqual(feeder.status, 'normal')
        self.assertTrue(repair.done_at)
        self.assertEqual(repair.result, 'replaced nozzle')
        feeder.action_scrap('broken frame')
        self.assertEqual(feeder.status, 'scrapped')
        with self.assertRaises(exceptions.UserError):
            feeder.action_enable()

    def test_bound_feeder_blocks_lifecycle(self):
        feeder = self._create_feeder('FDR-B1')
        product = self.env['product.product'].create({'name': 'Test Product'})
        production = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1,
        })
        feeder.write({'status': 'in_use', 'bound_production_id': production.id})
        with self.assertRaises(exceptions.UserError):
            feeder.action_disable()
        with self.assertRaises(exceptions.UserError):
            feeder.action_scrap('want to scrap')

    def test_care_state_count_thresholds(self):
        feeder = self._create_feeder(
            'FDR-C1', remind_count=10, maintenance_count=20, usage_count_limit=30)
        feeder.usage_count = 5
        self.assertEqual(feeder.care_state, 'ok')
        self.assertTrue(feeder.maintenance_ok)
        feeder.usage_count = 10
        self.assertEqual(feeder.care_state, 'remind')
        self.assertTrue(feeder.maintenance_ok)
        feeder.usage_count = 20
        self.assertEqual(feeder.care_state, 'maintain_due')
        self.assertFalse(feeder.maintenance_ok)
        feeder.usage_count = 30
        self.assertEqual(feeder.care_state, 'usage_expired')
        self.assertFalse(feeder.maintenance_ok)
        with self.assertRaises(exceptions.UserError):
            feeder.action_maintenance()

    def test_care_state_days_thresholds(self):
        feeder = self._create_feeder(
            'FDR-D1',
            maintenance_days=10,
            usage_days_limit=30,
            last_maintenance_date=date.today() - timedelta(days=11),
        )
        self.assertEqual(feeder.care_state, 'maintain_due')
        feeder.last_maintenance_date = date.today() - timedelta(days=31)
        self.assertEqual(feeder.care_state, 'usage_expired')

    def test_maintenance_reset(self):
        feeder = self._create_feeder('FDR-M1', maintenance_count=20)
        feeder.usage_count = 20
        self.assertEqual(feeder.care_state, 'maintain_due')
        feeder.action_maintenance()
        self.assertEqual(feeder.usage_count, 0)
        self.assertEqual(feeder.care_state, 'ok')
        record = self.env['sn.smt.feeder.maintenance'].search([('feeder_id', '=', feeder.id)])
        self.assertEqual(record.trigger, 'count_due')
        self.assertEqual(record.snapshot_usage_count, 20)

    def test_add_usage_batch_and_auto_scrap(self):
        feeder1 = self._create_feeder('FDR-U1', channels=['CH-U1'], usage_count_limit=10)
        feeder2 = self._create_feeder('FDR-U2', usage_count_limit=5)
        self.env['sn.smt.feeder'].add_usage([
            {'sn': 'CH-U1', 'qty': 3},
            {'sn': 'FDR-U2', 'qty': 4},
        ])
        self.assertEqual(feeder1.usage_count, 3)
        self.assertEqual(feeder2.usage_count, 4)
        self.env['sn.smt.feeder'].add_usage([
            {'sn': 'FDR-U2', 'qty': 1},
            {'sn': 'FDR-U2', 'qty': 1},
        ])
        self.assertEqual(feeder2.usage_count, 6)
        self.assertEqual(feeder2.status, 'scrapped')
        scrap = self.env['sn.smt.feeder.scrap'].search([('feeder_id', '=', feeder2.id)])
        self.assertEqual(scrap.trigger, 'usage_limit')
        with self.assertRaises(exceptions.UserError):
            self.env['sn.smt.feeder'].add_usage([{'sn': 'NOPE', 'qty': 1}])
        with self.assertRaises(exceptions.UserError):
            self.env['sn.smt.feeder'].add_usage([{'sn': 'FDR-U2', 'qty': 1}])

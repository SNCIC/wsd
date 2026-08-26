"""PDA device screen routes: group guard, board without scanning, location
filter, equipment scan resolve and overdue visibility."""

import json

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPdaDeviceCall(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.equipment_type = env['sn.wsd.device.equipment.type'].create({
            'name': 'PDA Test Oven',
        })
        cls.workshop_w1 = env['sn.wsd.device.location'].create(
            {'name': 'PDA-W1', 'kind': 'workshop'})
        cls.workshop_w2 = env['sn.wsd.device.location'].create(
            {'name': 'PDA-W2', 'kind': 'workshop'})
        cls.equipment = env['sn.wsd.device.equipment'].create({
            'code': 'DEV-PDA-01',
            'name': 'Reflow PDA',
            'equipment_type_id': cls.equipment_type.id,
            'location_id': cls.workshop_w1.id,
        })
        cls.equipment_empty = env['sn.wsd.device.equipment'].create({
            'code': 'DEV-PDA-02',
            'name': 'AOI PDA',
            'equipment_type_id': cls.equipment_type.id,
            'location_id': cls.workshop_w2.id,
        })
        cls.check_plan = env['sn.wsd.device.check.plan'].create({
            'equipment_type_id': cls.equipment_type.id,
        })
        cls.maint_plan = env['sn.wsd.device.maint.plan'].create({
            'equipment_type_id': cls.equipment_type.id,
        })
        yesterday = fields.Date.subtract(fields.Date.today(), days=1)
        cls.task_check = env['sn.wsd.device.check.task'].create({
            'plan_id': cls.check_plan.id,
            'equipment_id': cls.equipment.id,
            'task_date': fields.Date.today(),
            'task_status': 'pending',
            'line_ids': [(0, 0, {'name': 'Air pressure',
                                 'value_type': 'status'})],
        })
        cls.task_overdue = env['sn.wsd.device.maint.task'].create({
            'plan_id': cls.maint_plan.id,
            'equipment_id': cls.equipment.id,
            'task_date': yesterday,
            'task_status': 'overdue',
            'line_ids': [(0, 0, {'name': 'Clean rail',
                                 'value_type': 'status'})],
        })

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def _call(self, action, **params):
        response = self.url_open(
            '/sn_wsd_barcode/pda/device/call',
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': {'action': action, **params}}),
            headers={'Content-Type': 'application/json'},
        )
        return response.json().get('result', {})

    def test_01_group_guard(self):
        no_group = self.env['res.users'].create({
            'name': 'PDA Device No Group',
            'login': 'pda_device_nogroup',
            'email': 'pda_device_nogroup@example.com',
            'password': 'pda123',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.assertEqual(no_group.has_group(
            'sn_wsd_mrp.group_mes_shop'), False)
        self.authenticate('pda_device_nogroup', 'pda123')
        res = self._call('today_board')
        self.assertFalse(res['ok'])
        self.assertIn('permission', res['message'].lower())
        res = self._call('resolve', code='DEV-PDA-01')
        self.assertFalse(res['ok'])
        # nothing moved
        self.assertEqual(self.task_check.task_status, 'pending')

    def test_02_board_without_scan(self):
        res = self._call('today_board')
        self.assertTrue(res['ok'])
        group = next(g for g in res['data']['groups']
                     if g['equipment']['code'] == 'DEV-PDA-01')
        task_ids = {t['id'] for t in group['tasks']}
        self.assertEqual(task_ids,
                         {self.task_check.id, self.task_overdue.id})
        statuses = {t['status'] for t in group['tasks']}
        self.assertIn('overdue', statuses)
        codes = [g['equipment']['code'] for g in res['data']['groups']]
        self.assertNotIn('DEV-PDA-02', codes)

    def test_03_location_filter(self):
        res = self._call('today_board', location_id=self.workshop_w1.id)
        codes = [g['equipment']['code'] for g in res['data']['groups']]
        self.assertIn('DEV-PDA-01', codes)
        res = self._call('today_board', location_id=self.workshop_w2.id)
        codes = [g['equipment']['code'] for g in res['data']['groups']]
        self.assertNotIn('DEV-PDA-01', codes)

    def test_04_scan_equipment_resolves_card_and_tasks(self):
        res = self._call('resolve', code='DEV-PDA-01')
        self.assertTrue(res['ok'])
        card = res['data']['equipment']
        self.assertEqual(card['code'], 'DEV-PDA-01')
        self.assertEqual(card['name'], 'Reflow PDA')
        self.assertEqual(card['status'], 'enabled')
        self.assertIn('PDA-W1', card['location'])
        task_ids = {t['id'] for t in res['data']['tasks']}
        self.assertEqual(task_ids,
                         {self.task_check.id, self.task_overdue.id})

    def test_05_scan_equipment_without_tasks(self):
        res = self._call('resolve', code='DEV-PDA-02')
        self.assertTrue(res['ok'])
        self.assertEqual(res['data']['tasks'], [])
        self.assertEqual(res['data']['equipment']['code'], 'DEV-PDA-02')

    def test_06_unknown_action_and_unknown_code(self):
        res = self._call('does_not_exist')
        self.assertFalse(res['ok'])
        res = self._call('resolve', code='NOPE-404')
        self.assertFalse(res['ok'])
        self.assertIn('NOPE-404', res['message'])

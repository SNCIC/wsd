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
        cls.task_range = env['sn.wsd.device.check.task'].create({
            'plan_id': cls.check_plan.id,
            'equipment_id': cls.equipment.id,
            'task_date': fields.Date.today(),
            'task_status': 'pending',
            'line_ids': [
                (0, 0, {'name': 'Furnace temperature',
                        'value_type': 'range',
                        'lower_limit': 230.0, 'upper_limit': 240.0}),
                (0, 0, {'name': 'Belt check', 'value_type': 'status'}),
            ],
        })

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        # the HTTP session user is admin, NOT the test env user (OdooBot)
        self.http_user = self.env.ref('base.user_admin')

    def _call(self, action, **params):
        response = self.url_open(
            '/sn_wsd_barcode/pda/device/call',
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': {'action': action, **params}}),
            headers={'Content-Type': 'application/json'},
        )
        return response.json().get('result', {})

    def test_01_group_guard(self):
        # 制造权限扁平化后只分 制造用户/制造管理员，且内部用户经
        # Shop Floor 链即制造用户：门禁只拦门户(portal)等非内部账号。
        portal_user = self.env['res.users'].create({
            'name': 'PDA Device Portal',
            'login': 'pda_device_portal',
            'email': 'pda_device_portal@example.com',
            'password': 'pda123',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        self.assertEqual(portal_user.has_group('mrp.group_mrp_user'), False)
        self.authenticate('pda_device_portal', 'pda123')
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
                         {self.task_check.id, self.task_overdue.id,
                          self.task_range.id})
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
                         {self.task_check.id, self.task_overdue.id,
                          self.task_range.id})

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

    def test_07_task_flow_default_ok_submit(self):
        res = self._call('task_start', kind='check', task_id=self.task_range.id)
        self.assertTrue(res['ok'])
        self.assertEqual(self.task_range.task_status, 'in_progress')
        lines = {l['name']: l for l in res['data']['lines']}
        # default all-OK prefill: range mid value, status pass
        self.assertEqual(
            lines['Furnace temperature']['measured_value'], 235.0)
        self.assertEqual(lines['Belt check']['line_result'], 'pass')
        submit = self._call('task_submit', kind='check',
                            task_id=self.task_range.id)
        self.assertTrue(submit['ok'])
        self.assertEqual(submit['data']['overall_result'], 'pass')
        self.assertEqual(self.task_range.task_status, 'completed')
        self.assertEqual(self.task_range.executor_id, self.http_user)
        self.assertTrue(self.equipment.last_spot_check_date)

    def test_08_task_mark_abnormal_overall_fail(self):
        self._call('task_start', kind='check', task_id=self.task_range.id)
        range_line = self.task_range.line_ids.filtered(
            lambda l: l.value_type == 'range')
        status_line = self.task_range.line_ids.filtered(
            lambda l: l.value_type == 'status')
        updated = self._call('task_update_line', kind='check',
                             line_id=range_line.id, measured_value=245.0)
        self.assertTrue(updated['ok'])
        self.assertEqual(updated['data']['line_result'], 'fail')
        updated = self._call('task_update_line', kind='check',
                             line_id=status_line.id,
                             line_result='fail', line_note='belt loose')
        self.assertEqual(updated['data']['line_result'], 'fail')
        submit = self._call('task_submit', kind='check',
                            task_id=self.task_range.id)
        self.assertEqual(submit['data']['overall_result'], 'fail')
        self.assertFalse(range_line.line_note)
        self.assertEqual(status_line.line_note, 'belt loose')

    def test_09_repair_create_route(self):
        res = self._call('repair_create', code='DEV-PDA-01',
                         fault_type='electrical', fault_level='general',
                         description='belt noise\nstopped')
        self.assertTrue(res['ok'])
        order = self.env['sn.wsd.device.repair.order'].search([
            ('name', '=', res['data']['order'])])
        self.assertEqual(order.state, 'pending')
        self.assertEqual(order.reported_user_id, self.http_user)
        self.assertEqual(order.responsible_user_id,
                         self.equipment.maintenance_user_id)
        self.assertIn('belt noise', order.fault_phenomenon)
        # empty description is rejected
        res = self._call('repair_create', code='DEV-PDA-01',
                         fault_type='electrical', fault_level='general',
                         description='   ')
        self.assertFalse(res['ok'])
        self.assertFalse(self.env['sn.wsd.device.repair.order'].search([
            ('fault_phenomenon', 'like', 'DEV-PDA-01-noise-xyz')]))

    def test_10_mixed_pda_start_pc_submit(self):
        # PDA starts the task (prefill + in_progress), PC form submits it:
        # both go through the same model methods, no divergence.
        self._call('task_start', kind='check', task_id=self.task_range.id)
        self.assertEqual(self.task_range.task_status, 'in_progress')
        self.task_range.action_submit()
        self.assertEqual(self.task_range.task_status, 'completed')
        self.assertEqual(self.task_range.overall_result, 'pass')

    def test_11_locations_route_returns_list_in_data(self):
        self.env['sn.wsd.device.location'].create({
            'name': 'PDA-L1', 'kind': 'line',
            'parent_id': self.workshop_w1.id})
        res = self._call('locations')
        self.assertTrue(res['ok'])
        self.assertIsInstance(res['data'], list)
        w1 = next(item for item in res['data'] if item['name'] == 'PDA-W1')
        self.assertEqual(w1['full_name'], 'PDA-W1')
        self.assertEqual(w1['depth'], 0)
        child = next(item for item in res['data'] if item['name'] == 'PDA-L1')
        self.assertEqual(child['full_name'], 'PDA-W1 / PDA-L1')
        self.assertEqual(child['depth'], 1)

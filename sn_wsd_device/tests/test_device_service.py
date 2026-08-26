from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDeviceService(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.equipment_type = env['sn.wsd.device.equipment.type'].create({
            'name': 'Reflow Oven',
        })
        cls.maintenance_user = env['res.users'].create({
            'name': 'Maintenance Guy',
            'login': 'device_maintenance_user',
        })
        cls.equipment = env['sn.wsd.device.equipment'].create({
            'code': 'DEV-T01',
            'name': 'Reflow Oven #1',
            'equipment_type_id': cls.equipment_type.id,
            'maintenance_user_id': cls.maintenance_user.id,
        })
        cls.check_plan = env['sn.wsd.device.check.plan'].create({
            'equipment_type_id': cls.equipment_type.id,
        })
        cls.maint_plan = env['sn.wsd.device.maint.plan'].create({
            'equipment_type_id': cls.equipment_type.id,
        })

    def _create_task(self, kind, lines, task_date=None, status='pending',
                     equipment=None):
        model = self.env['sn.wsd.device.%s.task' % kind]
        return model.create({
            'plan_id': (self.check_plan if kind == 'check'
                        else self.maint_plan).id,
            'equipment_id': (equipment or self.equipment).id,
            'task_date': task_date or fields.Date.today(),
            'task_status': status,
            'line_ids': [(0, 0, line) for line in lines],
        })

    @staticmethod
    def _status_line(name='Visual check'):
        return {'name': name, 'value_type': 'status'}

    @staticmethod
    def _range_line(name='Furnace temperature', lower=230.0, upper=240.0):
        return {'name': name, 'value_type': 'range',
                'lower_limit': lower, 'upper_limit': upper}

    def _service(self):
        return self.env['sn.device.service']

    # ===== default all-OK start + submit =====

    def test_task_start_prefills_and_submit_all_ok(self):
        task = self._create_task('check', [
            self._status_line(),
            {'name': 'Fixed item', 'value_type': 'fixed'},
            self._range_line(),
        ])
        result = self._service().task_start('check', task.id)
        self.assertEqual(task.task_status, 'in_progress')
        lines = {(l['name'], l['value_type']): l for l in result['lines']}
        self.assertEqual(
            lines[('Visual check', 'status')]['line_result'], 'pass')
        self.assertEqual(
            lines[('Fixed item', 'fixed')]['line_result'], 'pass')
        self.assertEqual(
            lines[('Furnace temperature', 'range')]['measured_value'], 235.0)
        submit = self._service().task_submit('check', task.id)
        self.assertEqual(submit['overall_result'], 'pass')
        self.assertEqual(task.task_status, 'completed')
        self.assertEqual(task.executor_id, self.env.user)
        self.assertTrue(task.executed_time)
        self.assertTrue(self.equipment.last_spot_check_date)

    def test_range_override_marks_fail(self):
        task = self._create_task('check', [self._range_line()])
        self._service().task_start('check', task.id)
        line = task.line_ids
        updated = self._service().task_update_line(
            'check', line.id, measured_value=245.0)
        self.assertEqual(updated['line_result'], 'fail')
        submit = self._service().task_submit('check', task.id)
        self.assertEqual(submit['overall_result'], 'fail')

    def test_status_line_marked_fail(self):
        task = self._create_task('check', [self._status_line()])
        self._service().task_start('check', task.id)
        self._service().task_update_line(
            'check', task.line_ids.id, line_result='fail')
        submit = self._service().task_submit('check', task.id)
        self.assertEqual(submit['overall_result'], 'fail')

    def test_maint_task_flow_writes_ledger(self):
        task = self._create_task('maint', [self._status_line()])
        self._service().task_start('maint', task.id)
        self._service().task_submit('maint', task.id)
        self.assertEqual(task.task_status, 'completed')
        self.assertTrue(self.equipment.last_maintenance_date)

    # ===== resume / interruption =====

    def test_resume_keeps_worker_values(self):
        task = self._create_task('check', [
            self._status_line(), self._range_line()])
        self._service().task_start('check', task.id)
        self._service().task_update_line(
            'check', task.line_ids[0].id, line_result='fail',
            line_note='air pressure low')
        # Simulate an interruption: the task stays in_progress server-side,
        # a later scan reloads the values and does not reset them.
        reloaded = self._service().task_start('check', task.id)
        by_name = {l['name']: l for l in reloaded['lines']}
        self.assertEqual(by_name['Visual check']['line_result'], 'fail')
        self.assertEqual(by_name['Visual check']['line_note'], 'air pressure low')
        self.assertEqual(
            by_name['Furnace temperature']['measured_value'], 235.0)
        detail = self._service().task_detail('check', task.id)
        self.assertEqual(
            {l['name']: l['line_result'] for l in detail['lines']}[
                'Visual check'],
            'fail')

    def test_update_line_requires_in_progress(self):
        task = self._create_task('check', [self._status_line()])
        with self.assertRaises(UserError):
            self._service().task_update_line(
                'check', task.line_ids.id, line_result='fail')

    def test_completed_task_cannot_restart(self):
        task = self._create_task('check', [self._status_line()])
        self._service().task_start('check', task.id)
        self._service().task_submit('check', task.id)
        with self.assertRaises(UserError):
            self._service().task_start('check', task.id)

    # ===== equipment state guards =====

    def test_sealed_equipment_blocked(self):
        task = self._create_task('check', [self._status_line()])
        self.equipment.equipment_status = 'sealed'
        with self.assertRaises(UserError):
            self._service().task_start('check', task.id)
        with self.assertRaises(UserError):
            self._service().repair_create(
                'DEV-T01', 'mechanical', 'minor', 'noise')

    # ===== repair report =====

    def test_repair_create_defaults(self):
        result = self._service().repair_create(
            'DEV-T01', 'electrical', 'general', 'belt noise\nstopped')
        order = self.env['sn.wsd.device.repair.order'].search([
            ('name', '=', result['order'])])
        self.assertTrue(order)
        self.assertEqual(order.state, 'pending')
        self.assertEqual(order.reported_user_id, self.env.user)
        self.assertEqual(order.responsible_user_id, self.maintenance_user)
        self.assertIn('belt noise', order.fault_phenomenon)

    def test_repair_create_requires_description(self):
        with self.assertRaises(UserError):
            self._service().repair_create(
                'DEV-T01', 'electrical', 'general', '   ')
        with self.assertRaises(UserError):
            self._service().repair_create(
                'DEV-T01', 'does-not-exist', 'general', 'noise')

    # ===== scan / board =====

    def test_resolve_unknown_code_raises(self):
        with self.assertRaises(UserError):
            self._service().resolve('NOPE-404')

    def test_resolve_returns_open_tasks_and_card(self):
        open_task = self._create_task('check', [self._status_line()])
        done_task = self._create_task('check', [self._status_line()])
        done_task.write({
            'task_status': 'completed',
            'overall_result': 'pass',
            'executed_time': fields.Datetime.now(),
        })
        result = self._service().resolve('DEV-T01')
        self.assertEqual(result['equipment']['code'], 'DEV-T01')
        self.assertEqual(result['equipment']['name'], 'Reflow Oven #1')
        self.assertEqual(
            [t['id'] for t in result['tasks']], [open_task.id])

    def test_today_board_progress_and_location_filter(self):
        env = self.env
        workshop_1 = env['sn.wsd.device.location'].create(
            {'name': 'W1', 'kind': 'workshop'})
        workshop_2 = env['sn.wsd.device.location'].create(
            {'name': 'W2', 'kind': 'workshop'})
        equipment_b = env['sn.wsd.device.equipment'].create({
            'code': 'DEV-T02',
            'name': 'Printer',
            'equipment_type_id': self.equipment_type.id,
            'location_id': workshop_2.id,
        })
        self.equipment.location_id = workshop_1.id
        # The database already carries real tasks, so assert on deltas
        # against a baseline instead of absolute counters.
        baseline = self._service().today_board()['progress']
        baseline_w1 = self._service().today_board(
            location_id=workshop_1.id)['progress']
        baseline_w2 = self._service().today_board(
            location_id=workshop_2.id)['progress']

        yesterday = fields.Date.subtract(
            fields.Date.today(), days=1)
        self._create_task('check', [self._status_line()])
        self._create_task('maint', [self._status_line()],
                          task_date=yesterday, status='overdue')
        done = self._create_task('check', [self._status_line()],
                                 equipment=equipment_b)
        done.write({
            'task_status': 'completed',
            'overall_result': 'pass',
            'executed_time': fields.Datetime.now(),
        })

        def assert_delta(actual, base, delta):
            self.assertEqual(
                actual, {k: base[k] + delta[k] for k in base})

        board = self._service().today_board()
        assert_delta(board['progress'], baseline,
                     {'due': 3, 'done': 1, 'todo': 2, 'overdue': 1})
        group = next(g for g in board['groups']
                     if g['equipment']['code'] == 'DEV-T01')
        self.assertEqual(len(group['tasks']), 2)

        assert_delta(
            self._service().today_board(location_id=workshop_1.id
                                        )['progress'],
            baseline_w1, {'due': 2, 'done': 0, 'todo': 2, 'overdue': 1})
        assert_delta(
            self._service().today_board(location_id=workshop_2.id
                                        )['progress'],
            baseline_w2, {'due': 1, 'done': 1, 'todo': 0, 'overdue': 0})

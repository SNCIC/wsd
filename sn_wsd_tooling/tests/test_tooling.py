from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase


class TestTooling(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def _get_or_create_type(name, code, **kw):
            existing = cls.env['sn.tooling.type'].search(
                ['|', ('name', '=', name), ('code', '=', code)], limit=1)
            return existing or cls.env['sn.tooling.type'].create({'name': name, 'code': code, **kw})

        cls.type_stencil = _get_or_create_type(
            'Stencil', 'STENCIL',
            has_tension=True, has_thickness=True, has_flatness=True)
        cls.type_mold = _get_or_create_type('Mold', 'MOLD')
        cls.template = cls.env['sn.tooling.template'].create({
            'code': 'TOOL-T-001',
            'name': 'Test Stencil',
            'spec': '500x400',
            'type_id': cls.type_stencil.id,
            'maintenance_by_count': True,
            'maintenance_count_limit': 100,
            'maintenance_count_reminder': 10,
            'default_tension': 35.0,
            'default_thickness': 0.12,
            'default_flatness': 0.05,
            'maintenance_item_ids': [
                (0, 0, {'name': 'Tension check', 'default_result': 'done'}),
                (0, 0, {'name': 'Surface check', 'default_result': 'issue'}),
            ],
        })

    def _create_tooling(self, sn='TOOL-0001', **kw):
        vals = {'sn': sn, 'template_id': self.template.id}
        vals.update(kw)
        return self.env['sn.tooling'].create(vals)

    # ------------------------------------------------------------------
    # Type
    # ------------------------------------------------------------------

    def test_type_name_unique(self):
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.tooling.type'].create({'name': self.type_stencil.name})

    def test_type_code_unique(self):
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env['sn.tooling.type'].create(
                    {'name': 'Type %s' % self.type_stencil.code, 'code': self.type_stencil.code})

    # ------------------------------------------------------------------
    # Template
    # ------------------------------------------------------------------

    def test_template_reminder_exceeds_limit(self):
        with self.assertRaises(ValidationError):
            self.env['sn.tooling.template'].create({
                'code': 'TOOL-T-002',
                'name': 'Bad',
                'type_id': self.type_stencil.id,
                'maintenance_by_count': True,
                'maintenance_count_limit': 100,
                'maintenance_count_reminder': 120,
            })

    def test_template_cycle_reminder_exceeds_days(self):
        with self.assertRaises(ValidationError):
            self.env['sn.tooling.template'].create({
                'code': 'TOOL-T-003',
                'name': 'Bad Cycle',
                'type_id': self.type_stencil.id,
                'maintenance_by_cycle': True,
                'maintenance_cycle_days': 30,
                'maintenance_cycle_reminder_days': 40,
            })

    def test_template_negative_reminder(self):
        with self.assertRaises(ValidationError):
            self.env['sn.tooling.template'].create({
                'code': 'TOOL-T-004',
                'name': 'Bad Negative',
                'type_id': self.type_stencil.id,
                'maintenance_count_reminder': -1,
            })

    def test_template_name_search(self):
        result = self.env['sn.tooling.template'].name_search('TOOL-T-001')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], self.template.id)

    # ------------------------------------------------------------------
    # Tooling instance
    # ------------------------------------------------------------------

    def test_tooling_sn_unique(self):
        self._create_tooling('TOOL-DUP')
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._create_tooling('TOOL-DUP')

    def test_tooling_create_copies_param_defaults(self):
        tooling = self._create_tooling()
        self.assertEqual(tooling.tension, 35.0)
        self.assertEqual(tooling.thickness, 0.12)
        self.assertEqual(tooling.flatness, 0.05)
        self.assertEqual(tooling.state, 'idle')
        self.assertEqual(tooling.type_id, self.type_stencil)

    def test_tooling_param_defaults_overridable(self):
        tooling = self._create_tooling(tension=40.0)
        self.assertEqual(tooling.tension, 40.0)

    def test_tooling_create_explicit_zeros_prefilled(self):
        # The web client submits untouched numeric fields as 0; zeros must
        # still fall back to the template defaults.
        tooling = self.env['sn.tooling'].create({
            'sn': 'TOOL-ZERO-1',
            'template_id': self.template.id,
            'tension': 0,
            'thickness': 0,
            'flatness': 0,
        })
        self.assertEqual(tooling.tension, 35.0)
        self.assertEqual(tooling.thickness, 0.12)
        self.assertEqual(tooling.flatness, 0.05)

    def test_tooling_name_search(self):
        tooling = self._create_tooling('TOOL-SEARCH-1')
        result = self.env['sn.tooling'].name_search('TOOL-SEARCH-1')
        self.assertIn(tooling.id, [rid for rid, _name in result])
        result = self.env['sn.tooling'].name_search('Test Stencil')
        self.assertIn(tooling.id, [rid for rid, _name in result])

    # ------------------------------------------------------------------
    # Lifecycle: issue / online / offline / return
    # ------------------------------------------------------------------

    def test_issue_online_offline_return(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        self.assertEqual(tooling.state, 'issued')
        self.assertEqual(tooling.issued_user_id, self.env.user)
        self.assertTrue(tooling.issued_date)
        tooling.action_online()
        self.assertEqual(tooling.state, 'online')
        tooling.action_offline()
        self.assertEqual(tooling.state, 'issued')
        tooling.action_return()
        self.assertEqual(tooling.state, 'idle')
        self.assertFalse(tooling.issued_user_id)
        self.assertFalse(tooling.issued_date)
        actions = tooling.record_ids.mapped('action')
        self.assertEqual(
            actions, ['issue', 'online', 'offline', 'return'])

    def test_issue_requires_idle(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        with self.assertRaises(UserError):
            tooling.action_issue()

    def test_online_requires_issued(self):
        tooling = self._create_tooling()
        with self.assertRaises(UserError):
            tooling.action_online()

    def test_return_requires_issued(self):
        tooling = self._create_tooling()
        with self.assertRaises(UserError):
            tooling.action_return()

    # ------------------------------------------------------------------
    # Maintenance status
    # ------------------------------------------------------------------

    def test_maintenance_status_by_count(self):
        tooling = self._create_tooling()
        self.assertEqual(tooling.maintenance_status, 'normal')
        tooling.cycle_usage_count = 90
        self.assertEqual(tooling.maintenance_status, 'due')
        tooling.cycle_usage_count = 100
        self.assertEqual(tooling.maintenance_status, 'expired')

    def test_maintenance_status_by_cycle(self):
        tooling = self._create_tooling()
        self.template.write({
            'maintenance_by_count': False,
            'maintenance_by_cycle': True,
            'maintenance_cycle_days': 180,
            'maintenance_cycle_reminder_days': 30,
        })
        today = fields.Date.context_today(tooling)
        tooling.last_maintenance_date = fields.Date.subtract(today, days=160)
        self.assertEqual(tooling.maintenance_status, 'due')
        tooling.last_maintenance_date = fields.Date.subtract(today, days=200)
        self.assertEqual(tooling.maintenance_status, 'expired')

    def test_issue_blocked_when_expired(self):
        tooling = self._create_tooling()
        tooling.cycle_usage_count = 100
        self.assertEqual(tooling.maintenance_status, 'expired')
        with self.assertRaises(UserError):
            tooling.action_issue()

    def test_online_blocked_when_expired(self):
        tooling = self._create_tooling()
        tooling.cycle_usage_count = 95  # due, not expired
        tooling.action_issue()
        tooling.cycle_usage_count = 100
        with self.assertRaises(UserError):
            tooling.action_online()

    # ------------------------------------------------------------------
    # Maintenance flow
    # ------------------------------------------------------------------

    def test_maintain_flow(self):
        tooling = self._create_tooling()
        tooling.cycle_usage_count = 100
        tooling.action_maintain_start()
        self.assertEqual(tooling.state, 'maintaining')
        line_vals = [
            (0, 0, {'name': 'Tension check', 'result': 'done'}),
            (0, 0, {'name': 'Surface check', 'result': 'issue', 'note': 'scratch'}),
        ]
        tooling.action_maintain_done(
            line_vals=line_vals, params={'tension': 36.5})
        self.assertEqual(tooling.state, 'idle')
        self.assertEqual(tooling.cycle_usage_count, 0)
        self.assertEqual(tooling.tension, 36.5)
        self.assertEqual(tooling.last_maintenance_date, fields.Date.context_today(tooling))
        self.assertEqual(tooling.maintenance_status, 'normal')
        maintain_records = tooling.record_ids.filtered(
            lambda r: r.action == 'maintain')
        self.assertEqual(len(maintain_records), 2)  # start + done
        done_record = maintain_records.filtered(lambda r: r.line_ids)
        self.assertEqual(len(done_record), 1)
        self.assertEqual(len(done_record.line_ids), 2)
        self.assertIn('issue', done_record.line_ids.mapped('result'))

    def test_maintain_start_requires_idle(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        with self.assertRaises(UserError):
            tooling.action_maintain_start()

    def test_maintain_done_requires_maintaining(self):
        tooling = self._create_tooling()
        with self.assertRaises(UserError):
            tooling.action_maintain_done()

    # ------------------------------------------------------------------
    # Repair flow
    # ------------------------------------------------------------------

    def test_repair_flow_fixed(self):
        tooling = self._create_tooling()
        tooling.action_repair_start('torn mesh')
        self.assertEqual(tooling.state, 'repairing')
        fault_records = tooling.record_ids.filtered(
            lambda r: r.action == 'repair' and r.fault == 'torn mesh')
        self.assertEqual(len(fault_records), 1)
        tooling.action_repair_done('fixed')
        self.assertEqual(tooling.state, 'idle')

    def test_repair_flow_scrap(self):
        tooling = self._create_tooling()
        tooling.action_repair_start('broken frame')
        with self.assertRaises(UserError):
            tooling.action_repair_done('scrap')  # reason required
        tooling.action_repair_done('scrap', reason='not repairable')
        self.assertEqual(tooling.state, 'scrapped')
        self.assertEqual(tooling.scrap_reason, 'not repairable')

    def test_repair_start_requires_fault(self):
        tooling = self._create_tooling()
        with self.assertRaises(UserError):
            tooling.action_repair_start(False)

    def test_repair_start_requires_idle(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        with self.assertRaises(UserError):
            tooling.action_repair_start('something')

    # ------------------------------------------------------------------
    # Disable / enable / scrap
    # ------------------------------------------------------------------

    def test_disable_enable(self):
        tooling = self._create_tooling()
        with self.assertRaises(UserError):
            tooling.action_disable()  # reason required
        tooling.action_disable('waiting inspection')
        self.assertEqual(tooling.state, 'disabled')
        self.assertEqual(tooling.disable_reason, 'waiting inspection')
        tooling.action_enable()
        self.assertEqual(tooling.state, 'idle')
        self.assertFalse(tooling.disable_reason)

    def test_disable_requires_idle(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        with self.assertRaises(UserError):
            tooling.action_disable('nope')

    def test_scrap_from_issued_blocked(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        with self.assertRaises(UserError):
            tooling.action_scrap('nope')

    def test_scrap_from_online_blocked(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        tooling.action_online()
        with self.assertRaises(UserError):
            tooling.action_scrap('nope')

    def test_scrap_ok(self):
        tooling = self._create_tooling()
        with self.assertRaises(UserError):
            tooling.action_scrap()  # reason required
        tooling.action_scrap('worn out')
        self.assertEqual(tooling.state, 'scrapped')
        self.assertEqual(tooling.scrap_reason, 'worn out')

    def test_scrap_from_disabled(self):
        tooling = self._create_tooling()
        tooling.action_disable('old')
        tooling.action_scrap('dispose')
        self.assertEqual(tooling.state, 'scrapped')

    # ------------------------------------------------------------------
    # Usage counting
    # ------------------------------------------------------------------

    def test_register_usage(self):
        tooling = self._create_tooling()
        with self.assertRaises(UserError):
            tooling.register_usage(10)  # idle, not online
        tooling.action_issue()
        tooling.action_online()
        tooling.register_usage(500)
        self.assertEqual(tooling.total_usage_count, 500)
        self.assertEqual(tooling.cycle_usage_count, 500)
        usage_records = tooling.record_ids.filtered(lambda r: r.action == 'usage')
        self.assertEqual(len(usage_records), 1)
        self.assertEqual(usage_records.qty, 500)
        tooling.register_usage(3)
        self.assertEqual(tooling.total_usage_count, 503)

    def test_register_usage_invalid_qty(self):
        tooling = self._create_tooling()
        tooling.action_issue()
        tooling.action_online()
        with self.assertRaises(UserError):
            tooling.register_usage(0)
        with self.assertRaises(UserError):
            tooling.register_usage(-5)

    # ------------------------------------------------------------------
    # PDA service
    # ------------------------------------------------------------------

    def test_service_resolve_unknown(self):
        with self.assertRaises(UserError):
            self.env['sn.tooling.service'].resolve('NOPE-404')

    def test_service_full_flow(self):
        service = self.env['sn.tooling.service']
        tooling = self._create_tooling('TOOL-PDA-1')
        info = service.resolve('TOOL-PDA-1')
        self.assertEqual(info['state'], 'idle')
        self.assertEqual(info['template'], self.template.display_name)
        service.issue('TOOL-PDA-1')
        self.assertEqual(tooling.state, 'issued')
        service.online('TOOL-PDA-1')
        service.register_usage('TOOL-PDA-1', 100)
        self.assertEqual(tooling.total_usage_count, 100)
        service.offline('TOOL-PDA-1')
        service.return_('TOOL-PDA-1')
        self.assertEqual(tooling.state, 'idle')
        service.maintain_start('TOOL-PDA-1')
        service.maintain_done(
            'TOOL-PDA-1',
            results=[{'name': 'Tension check', 'result': 'done'}],
            params={'tension': 38.0})
        self.assertEqual(tooling.state, 'idle')
        self.assertEqual(tooling.tension, 38.0)
        self.assertEqual(tooling.cycle_usage_count, 0)
        service.repair_start('TOOL-PDA-1', 'bent frame')
        self.assertEqual(tooling.state, 'repairing')
        service.repair_done('TOOL-PDA-1', 'scrap', reason='beyond repair')
        self.assertEqual(tooling.state, 'scrapped')
        with self.assertRaises(UserError):
            # scrapped tooling cannot be issued again
            service.issue('TOOL-PDA-1')

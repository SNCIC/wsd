from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExceptionTicket(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'Test Workshop'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'Test Line',
            'workshop_id': cls.workshop.id,
        })
        cls.category_equipment = cls.env.ref('sn_wsd_exception.exception_category_equipment')
        cls.category_material = cls.env.ref('sn_wsd_exception.exception_category_material')
        cls.category_other = cls.env.ref('sn_wsd_exception.exception_category_other')
        # Clean up same-name leftovers from manual/GUI testing sessions.
        cls.env['sn.wsd.exception.reason'].search([
            ('name', '=', 'Feeder maintenance overdue'),
        ]).unlink()
        cls.reason = cls.env['sn.wsd.exception.reason'].create({'name': 'Feeder maintenance overdue'})
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('sn_wsd_exception.escalation_enabled', 'False')
        icp.set_param('sn_wsd_exception.level_normal_need_confirm', 'False')
        icp.set_param('sn_wsd_exception.level_urgent_need_confirm', 'True')

    def _create_ticket(self, category=None, **kwargs):
        vals = {
            'production_line_id': self.line.id,
            'category_id': (category or self.category_equipment).id,
            'description': 'Frequent pick error mid line',
        }
        vals.update(kwargs)
        return self.env['sn.wsd.exception.ticket'].create(vals)

    def _fill_closure(self, ticket, **kwargs):
        vals = {
            'reason_id': self.reason.id,
            'temp_action': 'Swapped the feeder with a spare one',
            'root_cause': 'Feeder maintenance overdue',
            'corrective_action': 'Re-plan the feeder maintenance thresholds',
        }
        vals.update(kwargs)
        ticket.write(vals)

    def test_01_create_defaults(self):
        ticket = self._create_ticket()
        self.assertTrue(ticket.name and ticket.name != 'New')
        self.assertEqual(ticket.state, 'pending')
        self.assertEqual(
            ticket.team_id,
            self.env.ref('sn_wsd_exception.exception_team_equipment'),
        )
        self.assertEqual(ticket.level, 'urgent')
        self.assertTrue(ticket.reported_at)
        self.assertEqual(ticket.workshop_id, self.workshop)

    def test_02_claim_flow_and_double_claim(self):
        ticket = self._create_ticket()
        ticket.action_claim()
        self.assertEqual(ticket.state, 'processing')
        self.assertEqual(ticket.responsible_user_id, self.env.user)
        self.assertTrue(ticket.respond_at)
        with self.assertRaises(UserError):
            ticket.action_claim()

    def test_03_suspend_resume(self):
        ticket = self._create_ticket()
        ticket.action_claim()
        ticket.action_suspend('spare_part')
        self.assertEqual(ticket.state, 'suspended')
        self.assertEqual(len(ticket.pause_line_ids), 1)
        self.assertFalse(ticket.pause_line_ids[0].ended_at)
        ticket.action_resume()
        self.assertEqual(ticket.state, 'processing')
        self.assertTrue(ticket.pause_line_ids[0].ended_at)

    def test_04_closure_validation(self):
        ticket = self._create_ticket()
        ticket.action_claim()
        with self.assertRaises(ValidationError):
            ticket.action_submit_close()

    def test_05_close_without_confirmation_and_mttr(self):
        now = fields.Datetime.now()
        ticket = self._create_ticket(level='normal')
        ticket.reported_at = now - timedelta(minutes=180)
        ticket.action_claim()
        ticket.action_suspend('spare_part')
        pause = ticket.pause_line_ids[0]
        pause.write({
            'started_at': now - timedelta(minutes=120),
            'ended_at': now - timedelta(minutes=60),
        })
        ticket.action_resume()
        self._fill_closure(ticket)
        ticket.action_submit_close()
        self.assertEqual(ticket.state, 'done')
        self.assertEqual(ticket.confirm_user_id, self.env.user)
        self.assertTrue(ticket.closed_at)
        self.assertEqual(ticket.suspended_minutes, 60)
        total = int((ticket.closed_at - ticket.reported_at).total_seconds() // 60)
        self.assertEqual(ticket.mttr_minutes, total - 60)

    def test_06_confirm_and_reject(self):
        ticket = self._create_ticket()
        ticket.action_claim()
        self._fill_closure(ticket)
        ticket.action_submit_close()
        self.assertEqual(ticket.state, 'pending_confirm')
        ticket.action_reject('Root cause is not convincing')
        self.assertEqual(ticket.state, 'processing')
        ticket.action_submit_close()
        ticket.action_confirm()
        self.assertEqual(ticket.state, 'done')
        self.assertEqual(ticket.confirm_user_id, self.env.user)

    def test_07_reject_requires_note(self):
        ticket = self._create_ticket()
        ticket.action_claim()
        self._fill_closure(ticket)
        ticket.action_submit_close()
        with self.assertRaises(UserError):
            ticket.action_reject('')

    def test_08_category_reroute(self):
        ticket = self._create_ticket(category=self.category_equipment)
        old_team = ticket.team_id
        ticket.category_id = self.category_material
        self.assertNotEqual(ticket.team_id, old_team)
        self.assertEqual(ticket.team_id, self.env.ref('sn_wsd_exception.exception_team_material'))
        self.assertEqual(ticket.level, 'normal')
        self.assertTrue(ticket.reroute_at)

    def test_09_cancel(self):
        ticket = self._create_ticket(level='normal')
        ticket.action_claim()
        ticket.action_cancel(note='False alarm')
        self.assertEqual(ticket.state, 'cancelled')
        closed = self._create_ticket(level='normal')
        closed.action_claim()
        self._fill_closure(closed)
        closed.action_submit_close()
        with self.assertRaises(UserError):
            closed.action_cancel(note='too late')

    def test_10_downtime_span_constraint(self):
        ticket = self._create_ticket(level='normal')
        ticket.reported_at = fields.Datetime.now() - timedelta(minutes=120)
        ticket.action_claim()
        self._fill_closure(ticket)
        ticket.action_submit_close()
        ticket.downtime_minutes = 10
        with self.assertRaises(ValidationError):
            ticket.downtime_minutes = 100000

    def test_11_repeat_link(self):
        first = self._create_ticket(level='normal')
        first.action_claim()
        self._fill_closure(first)
        first.action_submit_close()
        second = self._create_ticket(repeat_of_id=first.id)
        self.assertTrue(second.is_repeat)
        self.assertEqual(second.repeat_of_id, first)

    def test_12_cron_disabled_noop(self):
        ticket = self._create_ticket()
        ticket.action_claim()
        self.env['sn.wsd.exception.ticket'].cron_escalate()
        self.assertEqual(len(ticket.escalation_log_ids), 0)

    def test_13_service_report_and_claim(self):
        service = self.env['sn.wsd.exception.service']
        result = service.report(
            line_id=self.line.id,
            category_id=self.category_other.id,
            note='Solder paste expired on line',
        )
        self.assertIn('ticket_id', result)
        claimed = service.claim(result['ticket_id'])
        self.assertEqual(claimed['state'], 'processing')
        open_list = service.open_list(line_id=self.line.id)
        self.assertTrue(any(item['ticket_id'] == result['ticket_id'] for item in open_list))

    def test_14_category_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.exception.category'].create({
                'name': 'Equipment',
                'parent_id': False,
                'company_id': self.env.company.id,
            })
        root = self.env.ref('sn_wsd_exception.exception_category_equipment')
        child = self.env['sn.wsd.exception.category'].create({
            'name': 'Feeder Trouble',
            'parent_id': root.id,
        })
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.exception.category'].create({
                'name': 'Deep Level',
                'parent_id': child.id,
            })

    def test_15_team_members_and_unlink_guard(self):
        ticket = self._create_ticket()
        with self.assertRaises(UserError):
            ticket.unlink()
        cancelled = self._create_ticket()
        cancelled.action_cancel(note='False alarm')
        cancelled.unlink()

    def test_16_needs_confirm_fallback_when_unset(self):
        # Settings never saved: the design defaults (urgent needs confirmation)
        # must apply even though the config parameter key is missing.
        self.env['ir.config_parameter'].search([
            ('key', '=', 'sn_wsd_exception.level_urgent_need_confirm'),
        ]).unlink()
        ticket = self._create_ticket()
        ticket.action_claim()
        self._fill_closure(ticket)
        ticket.action_submit_close()
        self.assertEqual(ticket.state, 'pending_confirm')
        ticket.action_confirm()
        self.assertEqual(ticket.state, 'done')

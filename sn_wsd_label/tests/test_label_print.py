import base64
import json

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLabelPrint(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={'lang': 'en_US'})
        cls.wizard_model = cls.env['sn.label.print.wizard']
        cls.log_model = cls.env['sn.label.print.log']
        cls.partner_model_id = cls.env['ir.model']._get_id('res.partner')
        cls.template = cls.env['sn.label.template'].create({
            'name': 'Partner Label',
            'model_id': cls.partner_model_id,
            'sn_field': 'name',
            'element_ids': [
                Command.create({
                    'element_type': 'text', 'content': 'fixed',
                    'fixed_text': '工具码', 'x': 20, 'y': 20,
                    'width': 150, 'height': 30, 'font_size': 24,
                }),
                Command.create({
                    'element_type': 'text', 'content': 'field',
                    'field_path': 'name', 'x': 20, 'y': 60,
                    'width': 300, 'height': 30, 'font_size': 26,
                }),
                Command.create({
                    'element_type': 'qrcode', 'content': 'field',
                    'field_path': 'name', 'x': 400, 'y': 100,
                    'width': 120, 'height': 120,
                }),
            ],
        })
        cls.partner = cls.env['res.partner'].create({
            'name': '钢网 GW-PRINT-0001',
            'company_id': cls.env.company.id,
        })

    def _create_wizard(self, res_ids, copies=1, template=None,
                       res_model='res.partner'):
        return self.wizard_model.create({
            'template_id': (template or self.template).id,
            'res_model': res_model,
            'res_ids': json.dumps(res_ids),
            'copies': copies,
        })

    def _logs(self, template=None):
        return self.log_model.search([
            ('template_id', '=', (template or self.template).id)])

    # ------------------------------------------------------------------
    # action_print: report action, ZPL and audit
    # ------------------------------------------------------------------
    def test_action_print_returns_report_and_logs(self):
        wizard = self._create_wizard([self.partner.id])
        action = wizard.action_print()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertEqual(action['report_type'], 'qweb-text')
        self.assertEqual(action['report_name'],
                         'sn_wsd_label.report_label_zpl')
        self.assertEqual(action['close_on_report_download'], True)
        self.assertIn('^XA', wizard.zpl_data)
        self.assertIn('^XZ', wizard.zpl_data)
        self.assertIn('^GFA', wizard.zpl_data)   # Chinese fixed text bitmap
        self.assertIn('^BQ', wizard.zpl_data)    # native QR command
        self.assertIn('^PW', wizard.zpl_data)
        self.assertIn('^LL', wizard.zpl_data)

        logs = self._logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.res_model, 'res.partner')
        self.assertEqual(logs.res_id, self.partner.id)
        self.assertEqual(logs.copies, 1)
        self.assertEqual(logs.user_id, self.env.user)
        self.assertEqual(logs.company_id, self.env.company)

    def test_action_print_report_renders_zpl_text(self):
        wizard = self._create_wizard([self.partner.id])
        wizard.action_print()
        report = self.env.ref('sn_wsd_label.action_report_label_zpl')
        content, filetype = report._render_qweb_text(report, wizard.ids)
        self.assertEqual(filetype, 'text')
        self.assertIn(b'^XA', content)
        self.assertIn(b'^XZ', content)
        self.assertIn(bytes(wizard.zpl_data, 'utf-8'), content)

    def test_action_print_multiple_copies(self):
        wizard = self._create_wizard([self.partner.id], copies=3)
        wizard.action_print()
        self.assertIn('^PQ3', wizard.zpl_data)
        log = self._logs()
        self.assertEqual(len(log), 1)
        self.assertEqual(log.copies, 3)

    def test_action_print_multiple_records(self):
        other = self.env['res.partner'].create({'name': '第二张'})
        wizard = self._create_wizard([self.partner.id, other.id])
        wizard.action_print()
        self.assertEqual(wizard.zpl_data.count('^XA'), 2)
        self.assertEqual(wizard.zpl_data.count('^XZ'), 2)
        logs = self._logs()
        self.assertEqual(len(logs), 2)
        self.assertEqual(
            set(logs.mapped('res_id')), {self.partner.id, other.id})

    def test_action_print_copies_must_be_positive(self):
        wizard = self._create_wizard([self.partner.id], copies=0)
        with self.assertRaisesRegex(
                UserError, 'number of copies must be a positive integer'):
            wizard.action_print()
        self.assertEqual(len(self._logs()), 0)

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    def test_action_print_model_mismatch(self):
        wizard = self.wizard_model.create({
            'template_id': self.template.id,
            'res_model': 'res.users',
            'res_ids': json.dumps([self.env.user.id]),
        })
        with self.assertRaisesRegex(
                UserError, 'cannot print records of model res.users'):
            wizard.action_print()
        self.assertEqual(len(self._logs()), 0)

    def test_action_print_missing_record(self):
        wizard = self._create_wizard([999999999])
        with self.assertRaisesRegex(
                UserError, 'records no longer exist'):
            wizard.action_print()
        self.assertEqual(len(self._logs()), 0)

    def test_action_print_invalid_res_ids(self):
        wizard = self.wizard_model.create({
            'template_id': self.template.id,
            'res_model': 'res.partner',
            'res_ids': 'not-json',
        })
        with self.assertRaisesRegex(
                UserError, 'JSON list of integers'):
            wizard.action_print()

    def test_action_print_unknown_model(self):
        wizard = self.wizard_model.create({
            'template_id': self.template.id,
            'res_model': 'not.a.model',
            'res_ids': json.dumps([1]),
        })
        with self.assertRaisesRegex(UserError, 'Unknown model'):
            wizard.action_print()

    # ------------------------------------------------------------------
    # Record read access gate
    # ------------------------------------------------------------------
    def test_action_print_denied_without_read_access(self):
        cron_template = self.env['sn.label.template'].create({
            'name': 'Cron Label',
            'model_id': self.env['ir.model']._get_id('ir.cron'),
            'sn_field': 'name',
            'element_ids': [
                Command.create({
                    'element_type': 'text', 'content': 'fixed',
                    'fixed_text': 'X', 'x': 20, 'y': 20,
                    'width': 100, 'height': 30,
                }),
            ],
        })
        cron = self.env['ir.cron'].create({
            'name': 'Label Print Test Cron',
            'state': 'code',
            'code': 'True',
            'model_id': self.env.ref('base.model_res_partner').id,
            'interval_number': 1,
        })
        demo = self.env.ref('base.user_demo')
        wizard = self.wizard_model.with_user(demo).create({
            'template_id': cron_template.id,
            'res_model': 'ir.cron',
            'res_ids': json.dumps([cron.id]),
        })
        with self.assertRaises(AccessError):
            wizard.action_print()
        self.assertEqual(
            self.log_model.search_count([('res_model', '=', 'ir.cron')]), 0)

    # ------------------------------------------------------------------
    # Permissions: printing is not restricted to designers
    # ------------------------------------------------------------------
    def test_regular_user_can_print_but_not_design(self):
        demo = self.env.ref('base.user_demo')
        # can read the template
        self.assertEqual(self.template.with_user(demo).name, 'Partner Label')
        # cannot edit it
        with self.assertRaises(AccessError):
            self.template.with_user(demo).write({'name': 'Nope'})
        # can run the wizard end to end
        wizard = self.wizard_model.with_user(demo).create({
            'template_id': self.template.id,
            'res_model': 'res.partner',
            'res_ids': json.dumps([self.partner.id]),
        })
        action = wizard.action_print()
        self.assertEqual(action['type'], 'ir.actions.report')
        self.assertIn('^XA', wizard.zpl_data)
        logs = self._logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.user_id, demo)
        # and read the audit trail afterwards
        self.assertEqual(logs.with_user(demo).copies, 1)
        with self.assertRaises(AccessError):
            logs.with_user(demo).write({'copies': 99})

    # ------------------------------------------------------------------
    # Defaults / onchange contract for connector modules
    # ------------------------------------------------------------------
    def test_default_get_with_default_context_keys(self):
        defaults = self.wizard_model.with_context(
            default_res_model='res.partner',
            default_res_ids=json.dumps([self.partner.id]),
        ).default_get(['res_model', 'res_ids', 'template_id', 'copies'])
        self.assertEqual(defaults['res_model'], 'res.partner')
        self.assertEqual(defaults['res_ids'], json.dumps([self.partner.id]))
        self.assertEqual(defaults['template_id'], self.template.id)
        self.assertEqual(defaults['copies'], 1)

    def test_default_get_with_active_model_and_ids(self):
        defaults = self.wizard_model.with_context(
            active_model='res.partner',
            active_ids=[self.partner.id],
        ).default_get(['res_model', 'res_ids', 'template_id'])
        self.assertEqual(defaults['res_model'], 'res.partner')
        self.assertEqual(json.loads(defaults['res_ids']), [self.partner.id])
        self.assertEqual(defaults['template_id'], self.template.id)

    def test_default_get_no_autofill_with_several_templates(self):
        self.env['sn.label.template'].create({
            'name': 'Partner Label 2',
            'model_id': self.partner_model_id,
            'sn_field': 'name',
        })
        defaults = self.wizard_model.with_context(
            active_model='res.partner',
            active_ids=[self.partner.id],
        ).default_get(['template_id'])
        self.assertFalse(defaults.get('template_id'))

    def test_onchange_res_model_autofills_single_template(self):
        wizard = self.wizard_model.new({'res_model': 'res.partner'})
        wizard._onchange_res_model()
        self.assertEqual(wizard.template_id, self.template)

    def test_wizard_and_report_action_xmlids(self):
        action = self.env.ref('sn_wsd_label.action_sn_label_print_wizard')
        self.assertEqual(action.res_model, 'sn.label.print.wizard')
        self.assertEqual(action.target, 'new')
        report = self.env.ref('sn_wsd_label.action_report_label_zpl')
        self.assertEqual(report.model, 'sn.label.print.wizard')
        self.assertEqual(report.report_type, 'qweb-text')
        self.assertFalse(report.binding_model_id)

    def test_preview_png_renders_first_record(self):
        wizard = self._create_wizard([self.partner.id])
        self.assertTrue(wizard.preview_png)
        self.assertTrue(base64.b64decode(wizard.preview_png)
                        .startswith(b'\x89PNG'))

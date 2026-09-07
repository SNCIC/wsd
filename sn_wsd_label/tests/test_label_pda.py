import json

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

CPCL_CONTRACT_TAGS = {
    'INIT', 'PAGE-WIDTH', 'TEXT', 'BOX', 'LINE', 'QRCODE', 'BITMAP',
    'BARCODE', 'PRINT',
}


@tagged('post_install', '-at_install')
class TestLabelPda(TransactionCase):
    """PDA print channel: service, controller contract and audit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={'lang': 'en_US'})
        cls.service = cls.env['sn.label.pda.service']
        cls.log_model = cls.env['sn.label.print.log']
        cls.template = cls.env['sn.label.template'].create({
            'name': 'Partner PDA Label',
            'model_id': cls.env['ir.model']._get_id('res.partner'),
            'sn_field': 'name',
            'element_ids': [
                Command.create({
                    'element_type': 'box', 'x': 8, 'y': 8,
                    'width': 544, 'height': 304,
                }),
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
            'name': '钢网 PDA-0001',
            'company_id': cls.env.company.id,
        })
        cls.other_partner = cls.env['res.partner'].create({
            'name': '钢网 PDA-0002',
            'company_id': cls.env.company.id,
        })

    def _logs(self, template=None):
        return self.log_model.search([
            ('template_id', '=', (template or self.template).id)])

    # ------------------------------------------------------------------
    # Command payload contract (PrintServer APP `content` scheme)
    # ------------------------------------------------------------------
    def test_print_commands_contract(self):
        result = self.service.print_commands(
            self.template.id, [self.partner.id], copies=2)
        self.assertEqual(result['copies'], 2)
        commands = result['commands']
        self.assertTrue(commands)
        tags = [command['tag'] for command in commands]
        self.assertTrue(set(tags) <= CPCL_CONTRACT_TAGS)
        self.assertEqual(tags[0], 'INIT')
        self.assertEqual(commands[0]['height'], self.template.height_dots)
        self.assertEqual(commands[0]['copies'], 2)
        self.assertEqual(tags[-1], 'PRINT')
        self.assertIn('PAGE-WIDTH', tags)
        self.assertIn('QRCODE', tags)
        self.assertIn('BOX', tags)
        # Chinese text elements are server-side bitmaps
        bitmaps = [c for c in commands if c['tag'] == 'BITMAP']
        self.assertTrue(bitmaps)
        for bitmap in bitmaps:
            self.assertTrue(
                bitmap['value'].startswith('data:image/png;base64,'))
        # the payload must survive JSON.stringify for the URL scheme
        json.dumps(result['commands'])

    def test_print_commands_copies_default_one(self):
        result = self.service.print_commands(self.template.id, [self.partner.id])
        self.assertEqual(result['copies'], 1)
        self.assertEqual(result['commands'][0]['copies'], 1)

    # ------------------------------------------------------------------
    # Multiple records: page framing and audit
    # ------------------------------------------------------------------
    def test_print_commands_multiple_records_and_logs(self):
        result = self.service.print_commands(
            self.template.id, [self.partner.id, self.other_partner.id], copies=3)
        tags = [command['tag'] for command in result['commands']]
        self.assertEqual(tags.count('INIT'), 2)
        self.assertEqual(tags.count('PRINT'), 2)
        logs = self._logs()
        self.assertEqual(len(logs), 2)
        self.assertEqual(set(logs.mapped('res_id')),
                         {self.partner.id, self.other_partner.id})
        self.assertTrue(all(log.copies == 3 for log in logs))
        self.assertTrue(all(log.template_id == self.template for log in logs))
        self.assertTrue(all(log.user_id == self.env.user for log in logs))
        self.assertTrue(all(log.res_model == 'res.partner' for log in logs))

    def test_print_commands_logs_the_real_user(self):
        demo = self.env.ref('base.user_demo')
        self.service.with_user(demo).print_commands(
            self.template.id, [self.partner.id])
        logs = self._logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.user_id, demo)
        self.assertEqual(logs.company_id, self.env.company)

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    def test_print_commands_unknown_template(self):
        with self.assertRaisesRegex(UserError, 'does not exist'):
            self.service.print_commands(999999999, [self.partner.id])
        self.assertEqual(len(self._logs()), 0)

    def test_print_commands_missing_record(self):
        with self.assertRaisesRegex(UserError, 'no longer exist'):
            self.service.print_commands(
                self.template.id, [self.partner.id, 999999999])
        self.assertEqual(len(self._logs()), 0)

    def test_print_commands_empty_ids(self):
        with self.assertRaisesRegex(UserError, 'No records were selected'):
            self.service.print_commands(self.template.id, [])
        self.assertEqual(len(self._logs()), 0)

    def test_print_commands_invalid_copies(self):
        for copies in (0, -1):
            with self.assertRaisesRegex(
                    UserError, 'number of copies must be a positive integer'):
                self.service.print_commands(self.template.id, [self.partner.id],
                                            copies=copies)
        self.assertEqual(len(self._logs()), 0)

    # ------------------------------------------------------------------
    # Record read access gate
    # ------------------------------------------------------------------
    def test_print_commands_denied_without_read_access(self):
        cron_template = self.env['sn.label.template'].create({
            'name': 'Cron PDA Label',
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
            'name': 'Label PDA Test Cron',
            'state': 'code',
            'code': 'True',
            'model_id': self.env.ref('base.model_res_partner').id,
            'interval_number': 1,
        })
        demo = self.env.ref('base.user_demo')
        with self.assertRaises(AccessError):
            self.service.with_user(demo).print_commands(
                cron_template.id, [cron.id])
        self.assertEqual(
            self.log_model.search_count([('res_model', '=', 'ir.cron')]), 0)

    # ------------------------------------------------------------------
    # Client action / route wiring
    # ------------------------------------------------------------------
    def test_action_and_menu_xmlids(self):
        action = self.env.ref('sn_wsd_label.action_label_print_screen')
        self.assertEqual(action.tag, 'sn_wsd_label.label_print_screen')
        menu = self.env.ref('sn_wsd_label.menu_label_print_screen')
        self.assertEqual(
            menu.parent_id, self.env.ref('sn_wsd_label.menu_label_center'))
        self.assertIn(self.env.ref('base.group_user'), menu.group_ids)

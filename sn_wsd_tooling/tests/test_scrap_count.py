from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestScrapCount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.type = cls.env['sn.tooling.type'].create({'name': 'Scrrap Test Type'})
        cls.template = cls.env['sn.tooling.template'].create({
            'name': 'Scrap Test Template',
            'code': 'SCRAP-TPL',
            'type_id': cls.type.id,
            'scrap_count_limit': 1000,
            'scrap_count_reminder': 950,
        })

    def _create_tooling(self, **kwargs):
        values = {
            'sn': 'SCRAP-SN-%s' % fields.Datetime.now().strftime('%H%M%S%f'),
            'template_id': self.template.id,
            'state': 'online',
        }
        values.update(kwargs)
        return self.env['sn.tooling'].create(values)

    # ------------------------------------------------------------------
    # Template parameter validation
    # ------------------------------------------------------------------
    def test_reminder_cannot_exceed_limit(self):
        with self.assertRaises(ValidationError):
            self.template.write({'scrap_count_reminder': 1200})

    def test_negative_scrap_values_rejected(self):
        with self.assertRaises(ValidationError):
            self.template.write({'scrap_count_limit': -1})

    # ------------------------------------------------------------------
    # Status boundaries 949 / 950 / 999 / 1000
    # ------------------------------------------------------------------
    def test_status_boundaries(self):
        tooling = self._create_tooling(total_usage_count=949)
        self.assertEqual(tooling.scrap_status, 'normal')
        self.assertEqual(tooling.remaining_scrap_count, 51)
        tooling.total_usage_count = 950
        self.assertEqual(tooling.scrap_status, 'due')
        self.assertEqual(tooling.remaining_scrap_count, 50)
        tooling.total_usage_count = 999
        self.assertEqual(tooling.scrap_status, 'due')
        tooling.total_usage_count = 1000
        self.assertEqual(tooling.scrap_status, 'expired')
        self.assertEqual(tooling.remaining_scrap_count, 0)

    def test_disabled_limit_stays_normal(self):
        self.template.write({'scrap_count_limit': 0, 'scrap_count_reminder': 0})
        tooling = self._create_tooling(total_usage_count=99999)
        self.assertEqual(tooling.scrap_status, 'normal')
        self.assertFalse(tooling.remaining_scrap_count)

    # ------------------------------------------------------------------
    # Station-pass gate at register_usage
    # ------------------------------------------------------------------
    def test_usage_blocked_at_limit(self):
        tooling = self._create_tooling(total_usage_count=1000)
        with self.assertRaises(UserError):
            tooling.register_usage(1)
        self.assertEqual(tooling.total_usage_count, 1000)

    def test_usage_allowed_in_reminder_zone(self):
        tooling = self._create_tooling(total_usage_count=950)
        tooling.register_usage(1)
        self.assertEqual(tooling.total_usage_count, 951)

    def test_usage_allowed_without_limit(self):
        self.template.write({'scrap_count_limit': 0, 'scrap_count_reminder': 0})
        tooling = self._create_tooling(total_usage_count=5000)
        tooling.register_usage(10)
        self.assertEqual(tooling.total_usage_count, 5010)

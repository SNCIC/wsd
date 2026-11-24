from odoo.exceptions import AccessError
from odoo.tests import TransactionCase


class TestNqiDictionary(TransactionCase):
    """Dictionaries update by natural key on import; the integration
    config is readable by managers only."""

    def _user(self, login, *groups):
        values = {
            'name': login, 'login': login, 'email': '%s@example.com' % login,
            'group_ids': [(4, self.env.ref('base.group_user').id)],
        }
        for group in groups:
            values['group_ids'].append((4, self.env.ref(group).id))
        return self.env['res.users'].create(values)

    def test_code_import_updates_by_natural_key_and_creates_new(self):
        Code = self.env['sn.wsd.nqi.code']
        existing = Code.search([
            ('code_type', '=', 'PRODUCT_CATEGID'),
            ('code_id', '=', '101')], limit=1)
        self.assertTrue(existing)
        before = Code.search_count([])
        result = Code.load(['code_type', 'code_id', 'value', 'name'], [
            ['PRODUCT_CATEGID', '101', '1', 'Meter (revised)'],
            ['PRODUCT_CATEGID', '1999', '1999', 'Brand new'],
        ])
        self.assertFalse(result['messages'], result['messages'])
        self.assertEqual(existing.name, 'Meter (revised)')
        self.assertEqual(Code.search_count([]), before + 1)
        created = Code.search([
            ('code_type', '=', 'PRODUCT_CATEGID'), ('code_id', '=', '1999')])
        self.assertEqual(len(created), 1)
        # a second import of the same workbook changes nothing
        result = Code.load(['code_type', 'code_id', 'value', 'name'], [
            ['PRODUCT_CATEGID', '101', '1', 'Meter (revised)'],
            ['PRODUCT_CATEGID', '1999', '1999', 'Brand new']])
        self.assertFalse(result['messages'], result['messages'])
        self.assertEqual(Code.search_count([]), before + 1)
        created.unlink()

    def test_component_import_updates_by_code(self):
        Component = self.env['sn.wsd.nqi.component']
        existing = Component.search([], order='code', limit=1)
        before = Component.search_count([])
        result = Component.load(['code', 'name'], [[existing.code, 'Renamed']])
        self.assertFalse(result['messages'], result['messages'])
        self.assertEqual(existing.name, 'Renamed')
        self.assertEqual(Component.search_count([]), before)

    def test_config_needs_the_manager_group(self):
        config = self.env['sn.wsd.nqi.config'].search([], limit=1)
        plain = self._user('nqi_probe_user', 'sn_wsd_nqi.group_nqi_user')
        manager = self._user(
            'nqi_probe_manager', 'sn_wsd_nqi.group_nqi_user',
            'sn_wsd_nqi.group_nqi_manager')
        with self.assertRaises(AccessError):
            self.env['sn.wsd.nqi.config'].with_user(plain).search([])
        self.assertEqual(
            self.env['sn.wsd.nqi.config'].with_user(manager).browse(
                config.ids).enterprise_code,
            config.enterprise_code)
        # a plain user's rows still get the enterprise code
        row = self.env['sn.wsd.nqi.rd.product.info'].with_user(plain).create(
            {'product_code': 'NQI-ACL-PROBE'})
        self.assertEqual(row.enterprise_code, config.enterprise_code)

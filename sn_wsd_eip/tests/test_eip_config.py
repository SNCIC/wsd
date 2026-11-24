"""Batch 1 of the eip-order-push change: standalone-app skeleton,
config tables, preset dictionaries, menus and security.

Covers every scenario of the eip-integration-config spec that belongs
to this batch: root menu and menu moves, preset interfaces and
dictionaries, material mapping company isolation, page size cap,
missing-config guard, adjustable operatetype literals, disabled
interface guard, ACLs and cross-company record rules.
"""

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestEipConfig(TransactionCase):

    def setUp(self):
        super().setUp()
        # The DB admin speaks zh_CN while the assertions below expect
        # the English source strings: pin the language for this test.
        self.env = self.env(context=dict(self.env.context, lang='en_US'))

    def _config_values(self, company=None):
        values = {
            'supplier_code': 'SUP-1',
            'supplier_name': 'Supplier One',
            'base_url': 'https://eip.example.com',
        }
        if company:
            values['company_id'] = company.id
        return values

    # ------------------------------------------------------------------
    # menus: standalone app, five groups, phase-1 menus moved
    # ------------------------------------------------------------------

    def test_10_root_menu_and_groups(self):
        root = self.env.ref('sn_wsd_eip.menu_eip_root')
        self.assertFalse(root.parent_id)
        self.assertIn(self.env.ref('mrp.group_mrp_user'), root.group_ids)
        for xmlid in ('menu_eip_pass_config', 'menu_eip_order_data',
                      'menu_eip_inventory', 'menu_eip_push_center',
                      'menu_eip_config'):
            menu = self.env.ref('sn_wsd_eip.%s' % xmlid)
            self.assertEqual(menu.parent_id, root)
        # the configuration group is manager-only
        config_menu = self.env.ref('sn_wsd_eip.menu_eip_config')
        self.assertIn(self.env.ref('mrp.group_mrp_manager'),
                      config_menu.group_ids)
        # phase-1 menus moved under the pass-data collection group
        pass_menu = self.env.ref('sn_wsd_eip.menu_eip_pass_config')
        self.assertEqual(
            self.env.ref('sn_wsd_eip.menu_eip_operation_mapping').parent_id,
            pass_menu)
        self.assertEqual(
            self.env.ref('sn_wsd_eip.menu_eip_value_mapping').parent_id,
            pass_menu)

    # ------------------------------------------------------------------
    # preset interfaces: 11 rows, paths, directions, literals
    # ------------------------------------------------------------------

    def test_20_preset_interfaces(self):
        Interface = self.env['sn.wsd.eip.interface']
        self.assertEqual(len(Interface.search([])), 11)
        expected = {
            'purchase_order': ('Grid Purchase Orders',
                               '/api/supplier-send', 'pull'),
            'sale_order': ('Sales Orders', '/api/supplier-so', 'push'),
            'production_order': ('Production Orders',
                                 '/api/supplier-ipo', 'push'),
            'work_order': ('Work Orders', '/api/Eipsupplier-wo', 'push'),
            'schedule': ('Production Schedules',
                         '/api/supplier-production-schedule', 'push'),
            'process_work': ('Process Work Reports',
                             '/api/supplier-process-work', 'push'),
            'raw_inventory': ('Key Raw Material Inventory',
                              '/api/eipmatinventory', 'push'),
            'entity': ('Entity IDs', '/api/entity-maintenance', 'push'),
            'supply_note': ('Supply Notes', '/api/supply-add', 'push'),
            'spare_inventory': ('Spare Parts Inventory',
                                '/api/eip_spare_product', 'push'),
            'finished_inventory': ('Finished Goods Inventory',
                                   '/api/eip-prod-store', 'push'),
        }
        for code, (name, path, direction) in expected.items():
            interface = Interface.search([('code', '=', code)], limit=1)
            self.assertTrue(interface, 'interface %s missing' % code)
            self.assertEqual(interface.name, name)
            self.assertEqual(interface.path, path)
            self.assertEqual(interface.direction, direction)
            self.assertTrue(interface.active)
            self.assertEqual(interface.operatetype_add, 'ADD')
            self.assertEqual(interface.operatetype_update, 'UPDATE')
            self.assertEqual(interface.operatetype_query, 'QUERY')

    # ------------------------------------------------------------------
    # preset dictionaries: 10 categories, 36 subclasses, 30002 -> 30
    # ------------------------------------------------------------------

    def test_30_preset_dictionaries(self):
        Category = self.env['sn.wsd.eip.category']
        Subclass = self.env['sn.wsd.eip.subclass']
        self.assertEqual(len(Category.search([])), 10)
        self.assertEqual(len(Subclass.search([])), 36)
        meter = Subclass.search([('code', '=', '30002')], limit=1)
        meters = Category.search([('code', '=', '30')], limit=1)
        self.assertEqual(meter.name, '电能表')
        self.assertEqual(meter.category_id, meters)
        self.assertEqual(meters.name, '表计')
        self.assertEqual(meter.display_name, '30002 / 电能表')

    # ------------------------------------------------------------------
    # material mapping: unique per company only
    # ------------------------------------------------------------------

    def test_40_material_mapping_company_isolation(self):
        Mapping = self.env['sn.wsd.eip.material.mapping']
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'EIP Co B'})
        Mapping.create({
            'company_id': company_a.id, 'eip_material_code': 'M1'})
        # same EIP code in another company is allowed
        Mapping.create({
            'company_id': company_b.id, 'eip_material_code': 'M1'})
        # a duplicate inside one company hits the unique constraint
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                Mapping.create({
                    'company_id': company_a.id,
                    'eip_material_code': 'M1'})

    # ------------------------------------------------------------------
    # pull page size cap (and floor)
    # ------------------------------------------------------------------

    def test_50_pull_page_size_capped(self):
        Config = self.env['sn.wsd.eip.config']
        config = Config.create(self._config_values())
        with self.assertRaisesRegex(ValidationError,
                                    'Page size cannot exceed 1000.'):
            config.write({'pull_page_size': 5000})
        with self.assertRaises(ValidationError):
            config.write({'pull_page_size': 0})
        # create path is guarded as well; a fresh company keeps the
        # unique(company_id) SQL constraint out of the way
        cap_company = self.env['res.company'].create({'name': 'EIP Cap Co'})
        with self.assertRaises(ValidationError):
            Config.create(dict(self._config_values(cap_company),
                               pull_page_size=5000))
        # boundaries themselves pass
        config.write({'pull_page_size': 1})
        config.write({'pull_page_size': 1000})
        self.assertEqual(config.pull_page_size, 1000)

    # ------------------------------------------------------------------
    # missing active config blocks before any call
    # ------------------------------------------------------------------

    def test_60_config_for_company_guard(self):
        Config = self.env['sn.wsd.eip.config']
        with self.assertRaisesRegex(
                UserError, 'No active EIP integration config'):
            Config._eip_config_for()
        config = Config.create(self._config_values())
        self.assertEqual(Config._eip_config_for(), config)
        self.assertEqual(
            Config._eip_config_for(config.company_id), config)
        config.active = False
        with self.assertRaisesRegex(
                UserError, 'No active EIP integration config'):
            Config._eip_config_for()

    # ------------------------------------------------------------------
    # operatetype literals are data, adjustable without code
    # ------------------------------------------------------------------

    def test_70_operatetype_literals_editable(self):
        Interface = self.env['sn.wsd.eip.interface']
        interface = Interface._eip_interface('sale_order')
        interface.write({'operatetype_add': 'add',
                         'operatetype_update': 'update'})
        Interface.invalidate_recordset()
        stored = Interface.search([('code', '=', 'sale_order')], limit=1)
        self.assertEqual(stored.operatetype_add, 'add')
        self.assertEqual(stored.operatetype_update, 'update')

    # ------------------------------------------------------------------
    # disabled or unknown interfaces never get called
    # ------------------------------------------------------------------

    def test_80_interface_guards(self):
        Interface = self.env['sn.wsd.eip.interface']
        interface = Interface._eip_interface('sale_order')
        self.assertEqual(interface.code, 'sale_order')
        interface.active = False
        with self.assertRaisesRegex(UserError, 'is disabled'):
            Interface._eip_interface('sale_order')
        with self.assertRaisesRegex(UserError, 'is not configured'):
            Interface._eip_interface('no_such_interface')

    # ------------------------------------------------------------------
    # ACLs: MRP user read-only, MRP manager full; cross-company rules
    # ------------------------------------------------------------------

    def test_90_acl_and_multi_company(self):
        Config = self.env['sn.wsd.eip.config']
        Mapping = self.env['sn.wsd.eip.material.mapping']
        company_a = self.env.company
        company_b = self.env['res.company'].create({'name': 'EIP Co B'})
        mrp_users = self.env.ref('mrp.group_mrp_user')
        mrp_managers = self.env.ref('mrp.group_mrp_manager')
        # (4, id) appends the group, base.group_user stays on board
        user = self.env['res.users'].create({
            'name': 'EIP MRP User',
            'login': 'eip_order_mrp_user',
            'email': 'eip_order_mrp_user@example.com',
            'group_ids': [(4, mrp_users.id)],
        })
        manager = self.env['res.users'].create({
            'name': 'EIP MRP Manager',
            'login': 'eip_order_mrp_manager',
            'email': 'eip_order_mrp_manager@example.com',
            'group_ids': [(4, mrp_managers.id)],
        })
        config_a = Config.create(self._config_values(company_a))
        config_b = Config.create(self._config_values(company_b))
        mapping_a = Mapping.create({
            'company_id': company_a.id, 'eip_material_code': 'MA'})
        mapping_b = Mapping.create({
            'company_id': company_b.id, 'eip_material_code': 'MB'})

        # MRP user reads but cannot write
        self.assertEqual(
            config_a.with_user(user).read(['supplier_code'])[0]
            ['supplier_code'], 'SUP-1')
        with self.assertRaises(AccessError):
            config_a.with_user(user).write({'timeout_sec': 60})
        with self.assertRaises(AccessError):
            Config.with_user(user).create(self._config_values(company_b))
        # MRP manager has full rights
        config_a.with_user(manager).write({'timeout_sec': 60})
        self.assertEqual(
            config_a.with_user(manager).read(['timeout_sec'])[0]
            ['timeout_sec'], 60)

        # a user bound to company A only sees company A records
        user.write({'company_ids': [(6, 0, company_a.ids)]})
        visible_configs = Config.with_user(user).search([])
        self.assertIn(config_a, visible_configs)
        self.assertNotIn(config_b, visible_configs)
        visible_mappings = Mapping.with_user(user).search([])
        self.assertIn(mapping_a, visible_mappings)
        self.assertNotIn(mapping_b, visible_mappings)

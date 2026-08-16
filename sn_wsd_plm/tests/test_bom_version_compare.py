from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestBomVersionCompare(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'Comparison Finished Product',
            'default_code': 'CMP-FG',
            'is_storable': True,
        })
        cls.component = cls.env['product.product'].create({
            'name': 'Comparison Component',
            'default_code': 'CMP-COMP',
            'is_storable': True,
        })
        cls.component_added = cls.env['product.product'].create({
            'name': 'Comparison Added Component',
            'default_code': 'CMP-ADD',
            'is_storable': True,
        })
        cls.byproduct = cls.env['product.product'].create({
            'name': 'Comparison By-product',
            'default_code': 'BY-REMOVE',
            'is_storable': True,
        })
        cls.workcenter = cls.env['mrp.workcenter'].create({
            'name': 'Comparison Work Center',
        })
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'Comparison Workshop',
            'code': 'PLM-CMP-WS',
        })
        cls.workcenter.write({
            'x_workcenter_type': 'workshop',
            'x_workshop_id': cls.workshop.id,
        })
        cls.route_operation_template = cls.env['sn.wsd.operation'].create({
            'code': 'PLM-CMP-ASSY',
            'name': 'Comparison Route Assembly',
            'time_cycle_manual': 10.0,
        })
        cls.base_route = cls.env['sn.wsd.process.route'].create({
            'name': 'Comparison Route',
            'code': 'PLM-CMP-ROUTE',
            'version': '1.0',
            'x_revision': 'A.0',
            'x_plm_state': 'released',
            'x_workshop_id': cls.workshop.id,
            'route_operation_ids': [fields.Command.create({
                'sequence': 10,
                'operation_id': cls.route_operation_template.id,
                'workcenter_id': cls.workcenter.id,
                'time_cycle_manual': 10.0,
                'x_allow_entry': True,
            })],
        })
        cls.target_route = cls.base_route.copy(default={
            'version': '1.1',
            'x_plm_state': 'draft',
            'x_revision': 'A.1',
            'x_previous_route_id': cls.base_route.id,
            'active': True,
        })
        cls.target_route.route_operation_ids.time_cycle_manual = 15.0
        cls.target_route.route_operation_ids.x_allow_reentry = True
        cls.base_bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_qty': 1.0,
            'product_uom_id': cls.product.uom_id.id,
            'x_bom_stage_type': 'engineering',
            'x_plm_state': 'draft',
            'x_revision': 'A.0',
            'x_workshop_id': cls.workshop.id,
            'bom_line_ids': [fields.Command.create({
                'product_id': cls.component.id,
                'product_qty': 2.0,
                'product_uom_id': cls.component.uom_id.id,
            })],
            'byproduct_ids': [fields.Command.create({
                'product_id': cls.byproduct.id,
                'product_qty': 1.0,
                'product_uom_id': cls.byproduct.uom_id.id,
            })],
            'operation_ids': [fields.Command.create({
                'name': 'Assembly',
                'x_step_code': 'ASSY',
                'workcenter_id': cls.workcenter.id,
                'time_cycle_manual': 10.0,
            })],
        })
        cls.base_bom.x_plm_state = 'released'
        cls.target_bom = cls.base_bom.copy(default={
            'x_plm_state': 'draft',
            'x_revision': 'A.1',
            'x_previous_bom_id': cls.base_bom.id,
            'active': True,
        })
        cls.target_bom.bom_line_ids.filtered(
            lambda line: line.product_id == cls.component
        ).product_qty = 3.0
        cls.env['mrp.bom.line'].create({
            'bom_id': cls.target_bom.id,
            'product_id': cls.component_added.id,
            'product_qty': 4.0,
            'product_uom_id': cls.component_added.uom_id.id,
        })
        cls.target_bom.byproduct_ids.unlink()
        cls.target_bom.operation_ids.time_cycle_manual = 15.0

    def test_version_comparison_detects_all_difference_types(self):
        wizard = self.env['sn.wsd.bom.version.compare.wizard'].create({
            'base_bom_id': self.base_bom.id,
            'target_bom_id': self.target_bom.id,
        })
        wizard._rebuild_comparison()

        component_lines = wizard.line_ids.filtered(lambda line: line.category == 'component')
        added_line = component_lines.filtered(lambda line: line.product_id == self.component_added)
        updated_line = component_lines.filtered(lambda line: line.product_id == self.component)
        self.assertRecordValues(added_line, [{
            'product_code': 'CMP-ADD',
            'change_type': 'add',
            'old_qty': 0.0,
            'new_qty': 4.0,
        }])
        self.assertRecordValues(updated_line, [{
            'change_type': 'update',
            'old_qty': 2.0,
            'new_qty': 3.0,
        }])
        self.assertFalse(wizard.line_ids.filtered(lambda line: line.category == 'byproduct'))
        self.assertEqual(wizard.added_count, 1)
        self.assertEqual(wizard.removed_count, 0)
        self.assertEqual(wizard.updated_count, 1)
        self.assertFalse(wizard.line_ids.filtered(lambda line: line.item_name == 'Effective Date'))
        self.assertEqual(set(wizard.component_line_ids.mapped('category')), {'component'})
        self.assertFalse(wizard.line_ids.filtered(lambda line: line.category == 'operation'))
        self.assertFalse(wizard.line_ids.filtered(lambda line: line.category == 'route_operation'))

    def test_comparison_excludes_unchanged_rows(self):
        wizard = self.env['sn.wsd.bom.version.compare.wizard'].create({
            'base_bom_id': self.base_bom.id,
            'target_bom_id': self.target_bom.id,
        })
        wizard._rebuild_comparison()

        self.assertFalse(wizard.line_ids.filtered(lambda line: line.change_type == 'unchanged'))
        self.assertEqual(wizard.unchanged_count, 0)

    def test_bom_action_defaults_to_previous_revision(self):
        action = self.target_bom.action_compare_revisions()
        wizard = self.env['sn.wsd.bom.version.compare.wizard'].browse(action['res_id'])

        self.assertEqual(wizard.base_bom_id, self.base_bom)
        self.assertEqual(wizard.target_bom_id, self.target_bom)
        self.assertEqual(action['target'], 'new')

    def test_route_action_compares_route_revision_operations(self):
        action = self.target_route.action_compare_revisions()
        wizard = self.env['sn.wsd.bom.version.compare.wizard'].browse(action['res_id'])

        self.assertEqual(wizard.comparison_mode, 'route')
        self.assertEqual(wizard.base_route_id, self.base_route)
        self.assertEqual(wizard.target_route_id, self.target_route)
        route_line = wizard.line_ids.filtered(lambda line: line.category == 'route_operation')
        self.assertEqual(route_line.change_type, 'update')
        self.assertEqual(route_line.operation_code, 'PLM-CMP-ASSY')
        self.assertEqual(route_line.old_duration, 10.0)
        self.assertEqual(route_line.new_duration, 15.0)
        self.assertIn('Allow Reentry', route_line.new_value)
        self.assertEqual(wizard.route_operation_line_ids, route_line)

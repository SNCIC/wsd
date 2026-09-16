from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSubstituteRule(TransactionCase):
    """substitute-rule R1：替代料规则主数据——全局默认/可选限定制令单、
    约束（原≠替、同对全局唯一、scope=orders 必选单）、权限（user 只读）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.workshop = cls.env['sn.mrp.workshop'].create({
            'name': 'WS-SUB', 'code': 'WSUB'})
        cls.line = cls.env['sn.mrp.production.line'].create({
            'name': 'SUB', 'code': 'SUB', 'workshop_id': cls.workshop.id})
        # 预建路线+图号绑定，避免 MO 创建走自动绑图号（drawing 唯一约束冲突）
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-SUB', 'code': 'RTSUB',
                'x_workshop_id': cls.workshop.id,
            })
        Operation = cls.env['sn.wsd.operation']
        cls.op_in = Operation.create({
            'name': 'SUB-IN', 'code': 'SIN', 'x_station_type': 'assembly'})
        cls.op_out = Operation.create({
            'name': 'SUB-OUT', 'code': 'SOUT', 'x_station_type': 'final_test'})
        cls.route.write({
            'state': 'confirmed',
            'x_production_side': 'single',
            'route_operation_ids': [
                (0, 0, {'operation_id': cls.op_in.id, 'sequence': 10}),
                (0, 0, {'operation_id': cls.op_out.id, 'sequence': 20}),
            ],
            'x_daily_input_operation_id': cls.op_in.id,
            'x_daily_output_operation_id': cls.op_out.id,
            'x_workorder_input_operation_id': cls.op_in.id,
        })
        cls.product_a = cls._component(cls, 'A-SUB')
        cls.product_a1 = cls._component(cls, 'A1-SUB')
        cls.product_b = cls._component(cls, 'B-SUB')
        cls.mes_order = cls._mes_order(cls)

        rule_model = cls.env['sn.wsd.substitute.rule']
        cls.rule_vals = {
            'original_product_id': cls.product_a.id,
            'substitute_product_id': cls.product_a1.id,
        }
        # 供权限断言的普通制造用户（无 manager 组）
        cls.mrp_user = cls.env['res.users'].create({
            'name': 'Substitute Rule User',
            'login': 'substitute_rule_user',
            'email': 'substitute_rule_user@example.com',
            'group_ids': [(6, 0, [cls.env.ref('mrp.group_mrp_user').id])],
        })

    def _component(self, name):
        return self.env['product.product'].create({
            'name': name, 'default_code': name,
            'uom_id': self.uom_unit.id, 'is_storable': True,
        })

    def _mes_order(cls):
        product = cls.env['product.product'].create({
            'name': 'P-SUB', 'default_code': 'DWG-SUB',
            'uom_id': cls.uom_unit.id, 'x_board_side': 'single',
        })
        cls.env['sn.wsd.process.route.drawing'].create({
            'route_id': cls.route.id, 'x_drawing_no': 'DWG-SUB'})
        bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id,
            'product_uom_id': cls.uom_unit.id,
            'product_qty': 10.0,
            'type': 'normal',
            'x_workshop_id': cls.workshop.id,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.product_a.id,
                'product_qty': 3.0,
                'product_uom_id': cls.uom_unit.id,
                'x_board_side': 'single',
            })],
        })
        mo = cls.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 10.0,
            'bom_id': bom.id, 'company_id': cls.company.id,
        })
        return cls.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': cls.line.id,
            'date_plan': fields.Date.today(),
            'planned_qty': 10.0,
        })

    # ------------------------------------------------------------------
    # R1 scenarios
    # ------------------------------------------------------------------

    def test_global_rule(self):
        rule = self.env['sn.wsd.substitute.rule'].create(dict(self.rule_vals))
        self.assertEqual(rule.scope, 'all')
        self.assertEqual(
            rule.name, '%s → %s' % (
                self.product_a.display_name, self.product_a1.display_name))

    def test_order_scoped_rule(self):
        rule = self.env['sn.wsd.substitute.rule'].create(dict(
            self.rule_vals, scope='orders',
            mes_order_ids=[(6, 0, [self.mes_order.id])]))
        self.assertEqual(rule.mes_order_count, 1)
        # 同料号对：单级与全局可并存（全局已覆盖，冗余无害）
        self.env['sn.wsd.substitute.rule'].create(dict(self.rule_vals))

    def test_self_substitution_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.substitute.rule'].create({
                'original_product_id': self.product_a.id,
                'substitute_product_id': self.product_a.id,
            })

    def test_duplicate_global_rejected(self):
        self.env['sn.wsd.substitute.rule'].create(dict(self.rule_vals))
        with self.assertRaises(IntegrityError):
            self.env['sn.wsd.substitute.rule'].create(dict(
                self.rule_vals, note='duplicate'))

    def test_order_scope_requires_orders(self):
        with self.assertRaises(ValidationError):
            self.env['sn.wsd.substitute.rule'].create(dict(
                self.rule_vals, scope='orders'))

    def test_mrp_user_readonly(self):
        rules = self.env['sn.wsd.substitute.rule'].create(dict(self.rule_vals))
        rules.flush_model()
        user_rules = rules.with_user(self.mrp_user)
        self.assertTrue(user_rules.read(['id']))
        with self.assertRaises(AccessError):
            self.env['sn.wsd.substitute.rule'].with_user(self.mrp_user).create(
                dict(self.rule_vals, substitute_product_id=self.product_b.id))

    def test_migrate_product_substitute_rules(self):
        """R4：产品级关系迁移为全局规则，幂等且双向数据生成两条。"""
        self.product_a.write({'substitute_ids': [(6, 0, [self.product_a1.id])]})
        self.product_b.write({'substitute_ids': [(6, 0, [self.product_a.id])]})
        rules = self.env['sn.wsd.substitute.rule']._migrate_product_substitute_rules()
        self.assertEqual(
            set((r.original_product_id, r.substitute_product_id) for r in rules),
            {(self.product_a, self.product_a1), (self.product_b, self.product_a)},
        )
        self.assertTrue(all(r.scope == 'all' for r in rules))
        # 幂等：重跑不再生成
        self.assertFalse(
            self.env['sn.wsd.substitute.rule']._migrate_product_substitute_rules())

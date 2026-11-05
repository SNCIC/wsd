from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCodeRuleEngine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rule_model = cls.env['sn.code.rule']
        cls.partner_model_id = cls.env['ir.model']._get_id('res.partner')

    def _create_rule(self, segments, **kwargs):
        values = {
            'name': 'Test Rule',
            'model_id': self.partner_model_id,
            'target_field': 'ref',
            'separator': '-',
        }
        values.update(kwargs)
        # TransactionCase keeps rows across tests: archive old rules with
        # the same uniqueness key (model/company/picking_type) first
        domain = [('model_id', '=', values['model_id'])]
        if values.get('picking_type_id'):
            domain.append(('picking_type_id', '=', values['picking_type_id']))
        else:
            domain.append(('picking_type_id', '=', False))
        self.rule_model.search(domain).write({'active': False})
        values['segment_ids'] = [
            (0, 0, dict(segment)) for segment in segments
        ]
        return self.rule_model.create(values)

    # ------------------------------------------------------------------
    # Segment rendering
    # ------------------------------------------------------------------
    def test_fixed_field_date_render(self):
        rule = self._create_rule([
            {'segment_type': 'fixed', 'text_value': 'MI'},
            {'segment_type': 'field', 'field_path': 'name'},
            {'segment_type': 'date', 'date_format': '%Y'},
        ])
        partner = self.env['res.partner'].create({'name': 'Alpha'})
        code = rule.render(partner)
        self.assertEqual(code, 'MI-Alpha-%s' % fields.Date.today().year)

    def test_cross_model_field_segment(self):
        rule = self._create_rule([
            {'segment_type': 'field',
             'field_path': 'company_id.partner_id.name'},
        ])
        partner = self.env['res.partner'].create({
            'name': 'X', 'company_id': self.env.company.id})
        code = rule.render(partner)
        self.assertTrue(code)

    def test_empty_field_policy(self):
        partner = self.env['res.partner'].create({'name': 'NoRef', 'ref': False})
        strict = self._create_rule([
            {'segment_type': 'field', 'field_path': 'ref',
             'empty_policy': 'error'},
        ])
        with self.assertRaises(ValidationError):
            strict.render(partner)
        strict.write({'active': False})
        lax = self._create_rule([
            {'segment_type': 'field', 'field_path': 'ref',
             'empty_policy': 'blank'},
        ])
        self.assertEqual(lax.render(partner), '')

    def test_lookup_segment_hit_and_miss(self):
        """Lookup target found by name matching the coded record's ref."""
        self.env['res.partner'].create({'name': 'LT-01', 'ref': 'LOOKUP-HIT-42'})
        coded = self.env['res.partner'].create(
            {'name': 'Source', 'ref': 'LT-01'})
        rule = self._create_rule([
            {'segment_type': 'lookup',
             'lookup_model_id': self.partner_model_id,
             'lookup_domain': "[('name', '=', {{ref}})]",
             'lookup_field_path': 'ref'},
        ], target_field='street')
        # coded.ref='LT-01' → domain finds partner named 'LT-01' → ref='Found'
        code = rule.render(coded)
        self.assertEqual(code, 'LOOKUP-HIT-42')
        # no partner named 'NoPartnerNamedThis' → lookup miss
        other = self.env['res.partner'].create(
            {'name': 'X', 'ref': 'NoPartnerNamedThis'})
        with self.assertRaises(ValidationError):
            rule.render(other)


    def test_reset_by_group_field(self):
        rule = self._create_rule([
            {'segment_type': 'field', 'field_path': 'name'},
            {'segment_type': 'seq', 'padding': 3,
             'group_field_paths': 'name'},
        ])
        alpha = self.env['res.partner'].create({'name': 'Alpha'})
        beta = self.env['res.partner'].create({'name': 'Beta'})
        self.assertEqual(rule.render(alpha), 'Alpha-001')
        self.assertEqual(rule.render(alpha), 'Alpha-002')
        self.assertEqual(rule.render(beta), 'Beta-001')

    def test_reset_by_period(self):
        rule = self._create_rule([
            {'segment_type': 'seq', 'padding': 2, 'period': 'year'},
        ])
        partner = self.env['res.partner'].create({'name': 'P'})
        self.assertEqual(rule.render(partner), '01')
        self.assertEqual(rule.render(partner), '02')

    def test_counter_atomic_increment(self):
        rule = self._create_rule([
            {'segment_type': 'seq', 'padding': 1},
        ])
        partner = self.env['res.partner'].create({'name': 'P'})
        segment = rule.segment_ids
        counter_model = self.env['sn.code.counter']
        values = [counter_model._next_value(segment, partner) for _ in range(3)]
        self.assertEqual(values, [1, 2, 3])

    def test_sequence_implementation(self):
        self.env['ir.sequence'].create({
            'name': 'Code Rule Test Seq',
            'code': 'sn.code.rule.test',
            'padding': 4,
        })
        rule = self._create_rule([
            {'segment_type': 'seq', 'seq_impl': 'sequence',
             'sequence_code': 'sn.code.rule.test'},
        ])
        partner = self.env['res.partner'].create({'name': 'P'})
        self.assertEqual(rule.render(partner), '0001')
        self.assertEqual(rule.render(partner), '0002')

    # ------------------------------------------------------------------
    # Uniqueness and rule resolution
    # ------------------------------------------------------------------
    def test_duplicate_code_blocked(self):
        rule = self._create_rule([{'segment_type': 'fixed', 'text_value': 'DUP'}])
        first = self.env['res.partner'].create({'name': 'One'})
        code = rule.render(first)
        first.ref = code
        second = self.env['res.partner'].create({'name': 'Two'})
        with self.assertRaises(ValidationError):
            rule.render(second)

    def test_rule_uniqueness_constraint(self):
        first = self._create_rule([{'segment_type': 'fixed', 'text_value': 'X'}])
        # _create_rule archives old rules, so create the duplicate directly
        with self.assertRaises(ValidationError):
            self.rule_model.create({
                'name': 'Duplicate',
                'model_id': first.model_id.id,
                'target_field': 'ref',
                'segment_ids': [(0, 0, {
                    'segment_type': 'fixed', 'text_value': 'Y'})],
            })

    def test_picking_type_distinction(self):
        """Two rules on stock.picking distinguished by operation type."""
        picking_model_id = self.env['ir.model']._get_id('stock.picking')
        types = self.env['stock.picking.type'].search([], limit=2)
        if len(types) < 2:
            self.skipTest('needs two picking types')
        issue, other = types
        rule_a = self._create_rule(
            [{'segment_type': 'fixed', 'text_value': 'A'}],
            name='Rule A', model_id=picking_model_id,
            picking_type_id=issue.id)
        rule_b = self._create_rule(
            [{'segment_type': 'fixed', 'text_value': 'B'}],
            name='Rule B', model_id=picking_model_id,
            picking_type_id=other.id)
        rule_a.write({'active': True})
        rule_b.write({'active': True})
        rule_a_rule = self.rule_model._find_rule(
            self.env['stock.picking'].new({
                'picking_type_id': issue.id,
                'company_id': self.env.company.id}))
        self.assertEqual(rule_a_rule, rule_a)
        rule_b_rule = self.rule_model._find_rule(
            self.env['stock.picking'].new({
                'picking_type_id': other.id,
                'company_id': self.env.company.id}))
        self.assertEqual(rule_b_rule, rule_b)

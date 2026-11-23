from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase


class TestNqiEnvelope(TransactionCase):
    """Envelope behavior, exercised on the first real mirror model."""

    def _create(self, vals):
        return self.env['sn.wsd.nqi.rd.product.info'].create(vals)

    def _create_config(self):
        existing = self.env['sn.wsd.nqi.config'].search([
            ('company_id', '=', self.env.company.id)], limit=1)
        if existing:
            return existing
        return self.env['sn.wsd.nqi.config'].create({
            'company_id': self.env.company.id,
            'enterprise_code': '88888',
        })

    def test_enterprise_code_defaults_from_config_and_is_overridable(self):
        self._create_config()
        row = self._create({
            'product_code': 'P-1',
            'product_type': 'DDSU666',
            'product_name': 'Meter',
            'product_categid': '101',
            'product_design_basis': 'GB/T 17215',
        })
        self.assertEqual(row.enterprise_code, '88888')
        row.write({'enterprise_code': 'OVERRIDE'})
        self.assertEqual(row.enterprise_code, 'OVERRIDE')

    def test_missing_bookkeeping_on_create_and_write(self):
        row = self._create({
            'product_code': 'P-2',
            'product_type': 'DDSU666',
            'product_name': 'Meter',
            'product_categid': '101',
            # product_design_basis left empty
        })
        self.assertEqual(row.missing_count, 1)
        self.assertEqual(row.missing_fields, ['product_design_basis'])
        row.write({'product_design_basis': 'GB/T 17215'})
        self.assertEqual(row.missing_count, 0)
        self.assertFalse(row.missing_fields)  # NULL means nothing missing
        row.write({'product_design_basis': ''})
        self.assertEqual(row.missing_count, 1)

    def test_mark_to_push_requires_config_and_completeness(self):
        # drop any pre-existing config (e.g. created via the UI) so the
        # no-config phase is testable; rolled back on teardown
        self.env['sn.wsd.nqi.config'].search([]).unlink()
        complete_vals = {
            'product_code': 'P-3',
            'product_type': 'DDSU666',
            'product_name': 'Meter',
            'product_categid': '101',
            'product_design_basis': 'GB/T 17215',
        }
        # no config yet: complete row is still rejected
        row = self._create(dict(complete_vals))
        with self.assertRaises(UserError):
            row.action_mark_to_push()

        self._create_config()

        # incomplete row is rejected and names the missing column
        incomplete = self._create({
            'product_code': 'P-4',
            'product_type': 'DDSU666',
            'product_name': 'Meter',
            'product_categid': '101',
        })
        with self.assertRaises(UserError):
            incomplete.action_mark_to_push()

        # complete row passes the gate
        row.action_mark_to_push()
        self.assertEqual(row.push_state, 'to_push')

    def test_bring_in_fills_initial_values_only(self):
        product = self.env['product.product'].create({
            'name': 'Meter X', 'default_code': 'DDS-1',
        })
        with Form(self.env['sn.wsd.nqi.rd.product.info']) as form:
            form.product_id = product
            # bring-in fired: initial values from the anchor
            self.assertEqual(form.product_code, 'DDS-1')
            self.assertEqual(form.product_name, 'Meter X')
            # user input is never overwritten by bring-in
            form.product_name = 'Custom Name'

    def test_anchor_unlink_keeps_row_and_snapshot(self):
        product = self.env['product.product'].create({
            'name': 'Meter Y', 'default_code': 'DDS-2',
        })
        row = self.env['sn.wsd.nqi.rd.product.info'].create({
            'product_id': product.id,
            'product_code': 'DDS-2',
        })
        product.unlink()
        self.assertFalse(row.product_id)
        self.assertEqual(row.product_code, 'DDS-2')

    def _plan_products(self):
        machine = self.env['product.product'].search([
            ('nqi_product_kind', '=', 'machine')], limit=1)
        board = self.env['product.product'].search([
            ('nqi_product_kind', '=', 'board')], limit=1)
        return machine, board

    def test_plan_expand_details_per_manufacturing_order(self):
        machine, board = self._plan_products()
        if not machine or not board:
            self.skipTest('needs one machine-kind and one board-kind product')
        order = self.env['sale.order'].create({
            'partner_id': self.env.ref('base.res_partner_2').id,
        })
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': machine.id,
        })
        Production = self.env['mrp.production']
        Production.create({
            'product_id': machine.id,
            'product_qty': 100,
            'origin': order.name,
            'x_sn_segment_start': '100000000001',
            'x_sn_segment_end': '100000000100',
        })
        Production.create({
            'product_id': board.id,
            'product_qty': 100,
            'origin': order.name,
            'x_sn_segment_start': '200000000001',
            'x_sn_segment_end': '200000000100',
        })
        plan = self.env['sn.wsd.nqi.pt.plan'].create({
            'sale_order_id': order.id,
        })
        plan.action_expand_details()
        self.assertEqual(len(plan.detail_ids), 2)
        by_type = {detail.type: detail for detail in plan.detail_ids}
        self.assertEqual(by_type['01'].count, '100')
        self.assertEqual(by_type['01'].start_serial_no, '100000000001')
        self.assertEqual(by_type['02'].start_serial_no, '200000000001')
        # expansion is repeatable without duplicating lines
        plan.action_expand_details()
        self.assertEqual(len(plan.detail_ids), 2)

    def test_plan_expand_requires_sales_order(self):
        plan = self.env['sn.wsd.nqi.pt.plan'].create({})
        with self.assertRaises(UserError):
            plan.action_expand_details()

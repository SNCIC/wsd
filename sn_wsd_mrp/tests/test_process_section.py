from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from psycopg2 import IntegrityError

SEED_CODES = {'smt', 'dip', 'board_test', 'assembly', 'testing', 'inspection', 'packaging'}


@tagged('post_install', '-at_install')
class TestProcessSection(TransactionCase):
    """工段清单化（process-section-maintainable）：页面可建、种子可用、
    存量按 key 映射、统计行唯一口径不变、面板数据带清单字段。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')

    def _section(self, code):
        return self.env['sn.wsd.process.section'].search([
            ('company_id', '=', self.company.id), ('code', '=', code)], limit=1)

    def _operation(self, code, section=False):
        return self.env['sn.wsd.operation'].create({
            'name': 'PS-%s' % code, 'code': code,
            'company_id': self.company.id,
            'x_process_section': section.id if section else False,
        })

    def test_seeded_sections_available(self):
        # spec: process-section/spec/工段清单维护（页面可创建）/种子数据可用
        codes = set(self.env['sn.wsd.process.section'].search([
            ('company_id', '=', self.company.id)]).mapped('code'))
        self.assertTrue(
            SEED_CODES <= codes,
            'seeded sections missing: %s' % (SEED_CODES - codes))
        # seeds are selectable on operations
        op = self._operation('PS-SEED', self._section('smt'))
        self.assertEqual(op.x_process_section.code, 'smt')

    def test_create_section_usable_on_operation(self):
        # spec: process-section/spec/工段清单维护（页面可创建）/页面新建工段
        section = self.env['sn.wsd.process.section'].create({
            'name': 'Aging', 'code': 'aging', 'sequence': 65,
            'company_id': self.company.id,
        })
        op = self._operation('PS-NEW', section)
        self.assertEqual(op.x_process_section, section)

    def test_section_code_unique_per_company(self):
        self.env['sn.wsd.process.section'].create({
            'name': 'Dup', 'code': 'dup-section', 'company_id': self.company.id})
        with self.assertRaises(IntegrityError):
            self.env['sn.wsd.process.section'].create({
                'name': 'Dup 2', 'code': 'dup-section',
                'company_id': self.company.id})

    def test_legacy_keys_fully_mappable(self):
        # spec: process-section/spec/工序与工段统计挂接清单/存量迁移无损
        # 迁移按 key 映射：每个存量 key 在种子清单里必须有同 code 记录
        for key in SEED_CODES:
            self.assertTrue(
                self._section(key),
                'legacy key %s has no seeded section to map to' % key)

    def test_route_section_stat_unique_per_route(self):
        # spec: process-section/spec/工序与工段统计挂接清单/工段统计唯一口径不变
        op_start = self._operation('STAST')
        op_end = self._operation('ETAST')
        route = self.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-PS', 'code': 'RTPS',
                'x_workshop_id': self.env['sn.mrp.workshop'].create(
                    {'name': 'WS-PS', 'code': 'WSPS'}).id,
                'state': 'confirmed', 'x_production_side': 'single',
                'route_operation_ids': [
                    (0, 0, {'operation_id': op_start.id, 'sequence': 10,
                            'x_allow_entry': True}),
                    (0, 0, {'operation_id': op_end.id, 'sequence': 20,
                            'x_allow_exit': True}),
                ],
                'x_daily_input_operation_id': op_start.id,
                'x_daily_output_operation_id': op_end.id,
                'x_workorder_input_operation_id': op_start.id,
            })
        StatLine = self.env['sn.wsd.route.section.stat']
        StatLine.create({
            'route_id': route.id,
            'x_process_section': self._section('smt').id,
            'start_operation_id': op_start.id, 'end_operation_id': op_end.id,
        })
        with self.assertRaises(IntegrityError):
            StatLine.create({
                'route_id': route.id,
                'x_process_section': self._section('smt').id,
                'start_operation_id': op_start.id, 'end_operation_id': op_end.id,
            })

    def test_palette_carries_section_data_and_order(self):
        # spec: process-section/spec/流程图面板按清单分组/面板动态分组
        aging = self.env['sn.wsd.process.section'].create({
            'name': 'Aging', 'code': 'aging-pal', 'sequence': 65,
            'company_id': self.company.id,
        })
        inspection = self._section('inspection')  # seed sequence 60
        self._operation('PS-AGI', aging)
        self._operation('PS-INSP', inspection)
        self._operation('PS-NOSEC')
        ops = self.env['sn.wsd.process.route'].get_route_operations_for_company(
            self.company.id)
        mine = [o for o in ops if o['code'] in ('PS-AGI', 'PS-INSP', 'PS-NOSEC')]
        self.assertEqual(
            [o['code'] for o in mine], ['PS-INSP', 'PS-AGI', 'PS-NOSEC'])
        by_code = {o['code']: o for o in mine}
        self.assertEqual(by_code['PS-AGI']['section_name'], 'Aging')
        self.assertEqual(by_code['PS-AGI']['section_sequence'], 65)
        self.assertEqual(by_code['PS-INSP']['section_sequence'], 60)
        self.assertFalse(by_code['PS-NOSEC']['section_id'])

"""Equipment-tab tooling / consumable load-unload logging in the material log.

Covers the confirmed scope (2026-09-10): only load / unload actions are
logged (process actions like thawing are not); orders without a maintained
critical-material list are logged too as long as a live MES order can be
resolved; consumable exhaust counts as unload with note EXHAUST; split
drawing rows carry required_item_code == item_code."""

import json
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestEquipmentMaterialLog(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.drawing_no = 'DWG-EQLOG-001'
        cls.product_fg = cls.env['product.product'].create({
            'name': 'Eqlog Finished Good',
            'default_code': cls.drawing_no,
            'is_storable': True,
        })
        cls.workshop = cls.env['sn.mrp.workshop'].create({'name': 'EQLOG WS'})
        cls.production_line = cls.env['sn.mrp.production.line'].create({
            'name': 'EQLOG LINE',
            'workshop_id': cls.workshop.id,
            'company_id': cls.env.company.id,
        })
        cls.op_print = cls.env['sn.wsd.operation'].create({'name': 'EQLOG Print'})
        cls.op_place = cls.env['sn.wsd.operation'].create({'name': 'EQLOG Place'})
        cls.route = cls.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'EQLOG-RT',
                'code': 'EQLOG-RT',
                'x_process_type': 'machine',
                'x_workshop_id': cls.workshop.id,
            })
        cls.tooling_template = cls.env['sn.tooling.template'].create({
            'code': 'EQLOG-TL-T',
            'name': 'Eqlog Stencil',
            'type_id': cls.env['sn.tooling.type'].create({
                'name': 'Eqlog Stencil Type', 'code': 'EQLOG-ST'}).id,
        })
        cls.tooling = cls.env['sn.tooling'].create({
            'sn': 'EQLOG-TL-001', 'template_id': cls.tooling_template.id})
        # 模板不在任何清单里的制具：动作照样要记日志（无清单行可翻转）
        cls.orphan_tooling = cls.env['sn.tooling'].create({
            'sn': 'EQLOG-TL-002',
            'template_id': cls.env['sn.tooling.template'].create({
                'code': 'EQLOG-TL-ORPHAN',
                'name': 'Eqlog Orphan Stencil',
                'type_id': cls.env['sn.tooling.type'].create({
                    'name': 'Eqlog Orphan Type', 'code': 'EQLOG-STO'}).id,
            }).id,
        })
        cls.consumable_template = cls.env['sn.consumable.template'].create({
            'code': 'EQLOG-CS-T',
            'name': 'Eqlog Solder Paste',
            'type_id': cls.env['sn.consumable.type'].create({
                'name': 'Eqlog Solder Type'}).id,
            'shelf_life_days': 180,
            'expiry_remind_days': 30,
        })
        cls.consumable = cls.env['sn.consumable.info'].create({
            'sn': 'EQLOG-CS-001', 'template_id': cls.consumable_template.id})
        # 关键物料清单（贴片工序）：制具 + 辅料各一行
        cls.env['sn.wsd.drawing.material'].create({
            'workshop_id': cls.workshop.id,
            'x_drawing_no': cls.drawing_no,
            'operation_id': cls.op_place.id,
            'x_side': 'single',
            'line_ids': [
                (0, 0, {'material_ref':
                        'sn.tooling.template,%s' % cls.tooling_template.id,
                        'usage_times': 1}),
                (0, 0, {'material_ref':
                        'sn.consumable.template,%s' % cls.consumable_template.id,
                        'usage_times': 1}),
            ],
        })
        cls.order, cls.rop_print, cls.rop_place = cls._create_order_with_route(
            [(cls.op_print, 10), (cls.op_place, 20)])
        cls.order.x_online_date = fields.Datetime.now()
        cls.order._prepare_drawing_online_materials()
        cls.wc = cls.env['mrp.workcenter'].create({
            'name': 'EQLOG WC',
            'x_operation_id': cls.op_place.id,
            'x_production_line_id': cls.production_line.id,
            'x_workshop_id': cls.workshop.id,
        })
        # 个体走到可上线态：制具领用（issued）；辅料回温完成（ready）
        cls.tooling.action_issue()
        cls.orphan_tooling.action_issue()
        cls.consumable.action_issue()
        cls.consumable.action_thaw_start()
        cls.consumable.action_thaw_end()

    @classmethod
    def _create_order_with_route(cls, op_sequence):
        MesOrder = cls.env['sn.wsd.mes.order']
        production = cls.env['mrp.production'].create({
            'product_id': cls.product_fg.id,
            'product_qty': 10,
        })
        with patch.object(type(MesOrder), '_setup_route', lambda self: True):
            order = MesOrder.create({
                'production_id': production.id,
                'production_line_id': cls.production_line.id,
                'x_workshop_id': cls.workshop.id,
                'date_plan': fields.Date.today(),
                'planned_qty': 10,
            })
        private_route = cls.env['sn.wsd.mes.order.route'].create({
            'mes_order_id': order.id,
            'route_id': cls.route.id,
        })
        order.x_mes_route_id = private_route.id
        rops = []
        for operation, sequence in op_sequence:
            rops.append(cls.env['sn.wsd.mes.order.route.operation'].create({
                'mes_route_id': private_route.id,
                'operation_id': operation.id,
                'sequence': sequence,
            }))
        return (order, *rops)

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def _call(self, endpoint, action, **params):
        # opener 自带 allow_requests（test-cursor cookie）；这里把 JSON-RPC
        # 错误信封折成 {ok: False, message: <error>} 便于断言与定位
        response = self.url_open(
            '/sn_wsd_barcode/pda/%s/call' % endpoint,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': {'action': action, **params}}),
            headers={'Content-Type': 'application/json'},
        )
        payload = response.json()
        if 'result' not in payload:
            return {'ok': False, 'message': str(payload.get('error', payload))}
        return payload['result']

    def _equipment_logs(self):
        return self.env['sn.smt.material.log'].search([
            ('mes_order_id', '=', self.order.id),
            ('operation_type', 'in', (
                'tooling_load', 'tooling_unload',
                'consumable_load', 'consumable_unload')),
        ])

    # ------------------------------------------------------------------
    # 任务1回归：清单拆行的主料料号 = 实际料号
    # ------------------------------------------------------------------

    def test_drawing_rows_carry_required_item_code(self):
        rows = self.order.x_smt_online_material_ids.filtered(
            lambda line: line.source == 'drawing_list')
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row.required_item_code)
            self.assertEqual(row.required_item_code, row.item_code)

    # ------------------------------------------------------------------
    # 制具：上线/下线各记一条并联动清单行；无清单模板也记
    # ------------------------------------------------------------------

    def test_tooling_online_offline_logged(self):
        res = self._call('tooling', 'online', sn=self.tooling.sn,
                         workcenter_id=self.wc.id)
        self.assertTrue(res["ok"], res.get("message"))
        res = self._call('tooling', 'offline', sn=self.tooling.sn,
                         workcenter_id=self.wc.id)
        self.assertTrue(res["ok"], res.get("message"))
        logs = self._equipment_logs().filtered(
            lambda log: log.tooling_id == self.tooling)
        self.assertEqual(logs.mapped('operation_type'),
                         ['tooling_unload', 'tooling_load'])
        tooling_row = self.order.x_smt_online_material_ids.filtered(
            lambda line: line.drawing_material_type == 'tooling')
        self.assertEqual(logs.mapped('online_material_id'), tooling_row)
        # 下线后清单行熄灭、制具引用清空
        self.assertEqual(tooling_row.is_load, 'N')
        self.assertFalse(tooling_row.tooling_id)
        for log in logs:
            self.assertEqual(log.workcenter_id, self.wc)
            self.assertEqual(log.company_id, self.order.company_id)
            self.assertTrue(log.operator_id)
            self.assertTrue(log.operated_at)

    def test_tooling_without_list_still_logged(self):
        res = self._call('tooling', 'online', sn=self.orphan_tooling.sn,
                         workcenter_id=self.wc.id)
        self.assertTrue(res["ok"], res.get("message"))
        logs = self._equipment_logs().filtered(
            lambda log: log.tooling_id == self.orphan_tooling)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.operation_type, 'tooling_load')
        # 无清单行可翻转：日志仍生成，只是不挂 online_material
        self.assertFalse(logs.online_material_id)

    # ------------------------------------------------------------------
    # 辅料：过程动作不记；load/unload 记；exhaust 视作下线 note=EXHAUST
    # ------------------------------------------------------------------

    def test_consumable_process_actions_not_logged(self):
        # setUp 已走 issue/thaw（未记）；此处再补一条过程动作仍不记
        res = self._call('consumable', 'stir_start', sn=self.consumable.sn)
        self.assertFalse(res['ok'])  # 模板未开搅拌管控，动作本身失败
        self.assertFalse(self._equipment_logs())

    def test_consumable_load_unload_exhaust_logged(self):
        res = self._call('consumable', 'load', sn=self.consumable.sn,
                         workcenter_id=self.wc.id)
        self.assertTrue(res["ok"], res.get("message"))
        res = self._call('consumable', 'unload', sn=self.consumable.sn,
                         workcenter_id=self.wc.id)
        self.assertTrue(res["ok"], res.get("message"))
        logs = self._equipment_logs().filtered(
            lambda log: log.consumable_info_id == self.consumable)
        self.assertEqual(logs.mapped('operation_type'),
                         ['consumable_unload', 'consumable_load'])
        consumable_row = self.order.x_smt_online_material_ids.filtered(
            lambda line: line.drawing_material_type == 'consumable')
        self.assertEqual(logs.mapped('online_material_id'), consumable_row)
        # 重新回温-上线（状态机允许）后用尽：记下线且 note=EXHAUST
        self.consumable.action_thaw_start()
        self.consumable.action_thaw_end()
        res = self._call('consumable', 'load', sn=self.consumable.sn,
                         workcenter_id=self.wc.id)
        self.assertTrue(res["ok"], res.get("message"))
        res = self._call('consumable', 'exhaust', sn=self.consumable.sn,
                         workcenter_id=self.wc.id)
        self.assertTrue(res["ok"], res.get("message"))
        exhaust = self._equipment_logs().filtered(
            lambda log: log.note == 'EXHAUST')
        self.assertEqual(len(exhaust), 1)
        self.assertEqual(exhaust.operation_type, 'consumable_unload')
        self.assertEqual(exhaust.consumable_info_id, self.consumable)
        # 用尽后清单行熄灭、辅料引用清空
        self.assertEqual(consumable_row.is_load, 'N')
        self.assertFalse(consumable_row.consumable_info_id)

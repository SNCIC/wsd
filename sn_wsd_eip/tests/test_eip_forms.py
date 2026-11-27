"""Batch 6 of the eip-order-push change: single-table forms and the
two derivations.

Covers the single-table requirements of the eip-business-forms spec:
the master-detail table of 11 forms (the four single-table models
carry no child list), local EIP uniqueness rules, payload shapes of
the single-table interfaces, envelope fields, document numbers, and
the two derivations (purchase-order line -> production order ->
work order).
"""

import datetime

from psycopg2 import IntegrityError

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .eip_order_common import EipOrderCase, eip_envelope

from odoo.addons.sn_wsd_eip.models.eip_push import KIND_CHILDREN

SINGLE_TABLE_MODELS = (
    'sn.wsd.eip.production.order',
    'sn.wsd.eip.work.order',
    'sn.wsd.eip.process.work',
    'sn.wsd.eip.entity.id',
)

WORK_ORDER_KEYS = (
    'purchaserHqCode', 'ipoNo', 'supplierCode', 'supplierName', 'woNo',
    'categoryCode', 'subclassCode', 'materialsCode', 'materialsDescription',
    'materialsBatch', 'amount', 'unit', 'planStartDate', 'planFinishDate',
    'actualStartDate', 'actualFinishDate', 'woStatus', 'entityCode',
    'processRouteNo', 'dataSource', 'dataSourceCreateTime', 'ownerId',
    'openId', 'modelSpec',
)
PROCESS_WORK_KEYS = (
    'purchaserHqCode', 'supplierCode', 'ipoNo', 'insideNo', 'deviceNo',
    'productBatchNo', 'processName', 'categoryCode', 'subclassCode',
    'processCode', 'processNo', 'workshopId', 'workshopCode',
    'workshopName', 'woNo', 'productId', 'dataSource',
    'dataSourceCreateTime', 'planStartTime', 'planEndTime',
    'actualStartDate', 'actualFinishDate', 'orderStatus', 'buyerProvince',
    'wavyStatus', 'ownerId', 'openId',
)
ENTITY_KEYS = (
    'purchaserHqCode', 'supplierCode', 'supplierName', 'entityCode',
    'poItemId', 'entityStatus', 'dataSource', 'dataSourceCreateTime',
    'remark', 'ownerId', 'openId',
)


@tagged('post_install', '-at_install')
class TestEipForms(EipOrderCase):

    def _mes_order(self, suffix):
        """A plain MES order under a manufacturing order: enough to
        carry the two numbers the ledger copies. The order needs a
        released route bound to its drawing number, built here."""
        product = self.env['product.product'].create({
            'name': 'P-%s' % suffix, 'default_code': 'DWG-%s' % suffix,
            'x_board_side': 'single'})
        mo = self.env['mrp.production'].create({
            'product_id': product.id, 'product_qty': 5})
        mo.name = 'MO-%s' % suffix
        workshop = self.env['sn.mrp.workshop'].create({
            'name': 'WS-%s' % suffix, 'code': 'WS%s' % suffix})
        line = self.env['sn.mrp.production.line'].create({
            'name': 'PL-%s' % suffix, 'code': 'PL%s' % suffix,
            'workshop_id': workshop.id})
        operation = self.env['sn.wsd.operation'].create({
            'name': 'OP-%s' % suffix, 'code': 'OP%s' % suffix,
            'x_max_test_count': 9})
        route = self.env['sn.wsd.process.route'].with_context(
            sn_wsd_skip_flow_versioning=True).create({
                'name': 'RT-%s' % suffix, 'code': 'RT%s' % suffix,
                'x_workshop_id': workshop.id,
                'state': 'confirmed',
                'x_production_side': 'single',
                'route_operation_ids': [
                    (0, 0, {'operation_id': operation.id, 'sequence': 10})],
                'x_daily_input_operation_id': operation.id,
                'x_daily_output_operation_id': operation.id,
                'x_workorder_input_operation_id': operation.id,
            })
        self.env['sn.wsd.process.route.drawing'].create({
            'route_id': route.id, 'x_drawing_no': product.default_code})
        order = self.env['sn.wsd.mes.order'].create({
            'production_id': mo.id,
            'production_line_id': line.id,
            'date_plan': datetime.date(2026, 12, 1),
            'planned_qty': 5,
        })
        order.name = 'MES-%s' % suffix
        return order

    def _order(self, **values):
        values.setdefault('po_item_id', '699708678428688384')
        values.setdefault('materials_code', 'MC-1')
        values.setdefault('materials_name', 'Meter X')
        values.setdefault('materials_unit', 'PCS')
        values.setdefault('materials_desc', 'Single-phase smart meter')
        values.setdefault('amount', '200')
        values.setdefault('unit', 'PCS')
        values.setdefault('plan_start_date', datetime.date(2026, 12, 1))
        values.setdefault('plan_finish_date', datetime.date(2026, 12, 31))
        values.setdefault(
            'category_id', self.env.ref('sn_wsd_eip.category_30').id)
        values.setdefault(
            'subclass_id', self.env.ref('sn_wsd_eip.subclass_30002').id)
        return self.env['sn.wsd.eip.production.order'].create(values)

    def _purchase_line(self, po_no='PO1', item_id='1001', **values):
        order = self.env['sn.wsd.eip.purchase.order'].create({
            'po_no': po_no,
            'buyer_code': 'BUY-1',
            'buyer_name': 'Grid Example Power Company',
        })
        values.setdefault('po_no', po_no)
        values.setdefault('po_item_id', item_id)
        values.setdefault('material_code', 'M-001')
        values.setdefault('material_desc', 'Single-phase meter')
        values.setdefault('amount', '200')
        return self.env['sn.wsd.eip.purchase.order.line'].create(
            dict(values, order_id=order.id))

    # ------------------------------------------------------------------
    # the four single-table models carry no child list
    # ------------------------------------------------------------------

    def test_10_single_tables_have_no_children(self):
        for model_name in SINGLE_TABLE_MODELS:
            model = self.env[model_name]
            self.assertFalse(
                [key for key, kind, _a, _ad, _u in model.EIP_FIELDS
                 if kind == KIND_CHILDREN],
                model_name)

    # ------------------------------------------------------------------
    # local EIP uniqueness rules
    # ------------------------------------------------------------------

    def test_20_uniqueness_rules(self):
        WorkOrder = self.env['sn.wsd.eip.work.order']
        Entity = self.env['sn.wsd.eip.entity.id']
        Production = self.env['sn.wsd.eip.production.order']
        category = self.env.ref('sn_wsd_eip.category_30')
        subclass = self.env.ref('sn_wsd_eip.subclass_30002')
        originals = {
            'production': Production.create(dict(
                po_item_id='X', materials_code='M', materials_name='M',
                materials_unit='U', materials_desc='M', amount='1',
                unit='U', ipo_no='IPO-DUP', category_id=category.id,
                subclass_id=subclass.id)),
            'work': WorkOrder.create({'wo_no': 'WO-DUP', 'ipo_no': 'IPO-1'}),
            'entity': Entity.create({
                'entity_code': 'ENT-1', 'po_item_id': '1001'}),
        }
        self.assertTrue(originals)
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                Production.create(dict(
                    po_item_id='Y', materials_code='M', materials_name='M',
                    materials_unit='U', materials_desc='M', amount='1',
                    unit='U', ipo_no='IPO-DUP', category_id=category.id,
                    subclass_id=subclass.id))
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                WorkOrder.create({'wo_no': 'WO-DUP', 'ipo_no': 'IPO-2'})
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                Entity.create({
                    'entity_code': originals['entity'].entity_code,
                    'po_item_id': '1002'})

    # ------------------------------------------------------------------
    # payload shapes of the single-table interfaces
    # ------------------------------------------------------------------

    def test_30_work_order_payload_shape(self):
        order = self._order()
        work = self.env['sn.wsd.eip.work.order'].create({
            'production_order_id': order.id,
            'ipo_no': order.ipo_no})
        values = work._eip_values(self.config)
        self.assertEqual(set(values), set(WORK_ORDER_KEYS))
        self.assertEqual(values['woStatus'], '1')
        self.assertEqual(values['dataSource'], '0')
        self.assertEqual(values['entityCode'], '')

    def test_31_process_work_payload_shape(self):
        Process = self.env['sn.wsd.eip.process.work']
        code = self.env['sn.wsd.eip.process.code'].create({
            'code': 'GX01', 'name': 'Assembly'})
        report = Process.create({
            'ipo_no': 'IPO-1', 'wo_no': 'WO-1',
            'process_code_id': code.id,
            'product_batch_no': 'B001',
            'buyer_province': '浙江',
        })
        # the derive from the dictionary is an onchange (UI); call it
        # like the form would
        report._onchange_process_code_id()
        self.assertEqual(report.process_code, 'GX01')
        self.assertEqual(report.process_name, 'Assembly')
        values = report._eip_values(self.config)
        self.assertEqual(set(values), set(PROCESS_WORK_KEYS))
        # the locate key of the parameter table, typed freely as well
        self.assertEqual(values['processCode'], 'GX01')
        self.assertEqual(values['buyerProvince'], '浙江')

    def test_32_entity_payload_shape(self):
        entity = self.env['sn.wsd.eip.entity.id'].create({
            'entity_code': '0001-0100', 'po_item_id': '1001',
            'entity_status': '1'})
        values = entity._eip_values(self.config)
        self.assertEqual(set(values), set(ENTITY_KEYS))
        self.assertEqual(values['entityStatus'], '1')
        self.assertEqual(values['dataSource'], '0')

    # ------------------------------------------------------------------
    # envelope fields on a fresh work order
    # ------------------------------------------------------------------

    def test_40_envelope_fields_and_beijing_time(self):
        work = self.env['sn.wsd.eip.work.order'].create({'ipo_no': 'IPO-9'})
        values = work._eip_values(self.config)
        self.assertEqual(values['purchaserHqCode'], 'SGCC')
        self.assertEqual(values['supplierCode'], 'SUP-1')
        self.assertEqual(values['supplierName'], 'Supplier One')
        self.assertEqual(values['dataSource'], '0')
        self.assertEqual(values['dataSourceCreateTime'],
                         self.transport._eip_format_datetime(work.create_date))
        # no sequence any more: the number is the MES order number,
        # brought out by the picker or typed, until then empty
        self.assertFalse(work.wo_no)

    def test_41_work_order_number_locked_after_push(self):
        work = self.env['sn.wsd.eip.work.order'].create({
            'ipo_no': 'IPO-9', 'wo_no': 'WO-9',
            'materials_code': 'MC', 'amount': '1', 'unit': 'PCS',
            'plan_start_date': datetime.date(2027, 1, 1),
            'plan_finish_date': datetime.date(2027, 1, 2),
            'category_id': self.env.ref('sn_wsd_eip.category_30').id,
            'subclass_id': self.env.ref('sn_wsd_eip.subclass_30002').id,
        })
        self.server.enqueue(eip_envelope())
        self.assertTrue(work._eip_push_one()['success'])
        with self.assertRaisesRegex(UserError, 'locate it there'):
            work.write({'wo_no': 'WO-CHANGED'})

    # ------------------------------------------------------------------
    # derive: purchase order line -> production order
    # ------------------------------------------------------------------

    def _config_defaults(self):
        """Category defaults on the config, as the production-order
        derivation reads them."""
        self.config.write({
            'default_category_id': self.env.ref('sn_wsd_eip.category_30').id,
            'default_subclass_id': self.env.ref(
                'sn_wsd_eip.subclass_30002').id,
        })

    def test_50_create_production_order_with_mapping(self):
        self._config_defaults()
        self.env['sn.wsd.eip.material.mapping'].create({
            'eip_material_code': 'M-001',
            'material_code': 'MC-9',
            'material_name': 'Smart Meter A',
            'material_desc': 'Our smart meter A',
            'material_unit': 'PCS',
        })
        line = self._purchase_line()
        action = line.action_create_production_orders()
        order = self.env['sn.wsd.eip.production.order'].browse(
            action['res_id'])
        self.assertEqual(order.po_item_id, '1001')
        self.assertEqual(order.data_type, '1')
        self.assertEqual(order.materials_code, 'MC-9')
        self.assertEqual(order.materials_name, 'Smart Meter A')
        self.assertEqual(order.materials_desc, 'Our smart meter A')
        self.assertEqual(order.materials_unit, 'PCS')
        self.assertEqual(order.unit, 'PCS')
        self.assertEqual(order.amount, '200')
        self.assertEqual(order.category_id.code, '30')
        self.assertEqual(order.subclass_id.code, '30002')
        self.assertEqual(order.push_state, 'draft')
        # nothing invented for the not-required fields
        self.assertFalse(order.ipo_status)
        self.assertFalse(order.owner_code)
        self.assertFalse(order.open_code)

    def test_51_create_production_order_without_mapping(self):
        self._config_defaults()
        line = self._purchase_line(item_id='1002')
        action = line.action_create_production_orders()
        order = self.env['sn.wsd.eip.production.order'].browse(
            action['res_id'])
        self.assertEqual(order.materials_code, 'M-001')
        self.assertEqual(order.materials_name, 'Single-phase meter')
        self.assertEqual(order.materials_desc, 'Single-phase meter')
        self.assertFalse(order.materials_unit)
        self.assertFalse(order.unit)

    def test_52_one_line_can_create_several_orders(self):
        self._config_defaults()
        line = self._purchase_line(item_id='1003')
        line.action_create_production_orders()
        line.action_create_production_orders()
        orders = self.env['sn.wsd.eip.production.order'].search(
            [('purchase_line_id', '=', line.id)])
        self.assertEqual(len(orders), 2)
        # no number until the manufacturing order is picked or the
        # number is typed
        self.assertEqual(orders.mapped('ipo_no'), [False, False])
        self.assertEqual(orders.mapped('po_item_id'), ['1003', '1003'])

    # ------------------------------------------------------------------
    # derive: production order -> work order
    # ------------------------------------------------------------------

    def _pick_mes_order(self, work, mes_order):
        """Pick the main MES order the way the form does: the field
        change brings out the numbers, and the main order joins the
        linked list (the save-time check demands it there)."""
        work.write({
            'mes_order_id': mes_order.id,
            'mes_order_ids': [(4, mes_order.id)],
        })
        work._onchange_mes_order_id()

    def test_60_create_work_order(self):
        order = self._order()
        action = order.action_create_work_order()
        work = self.env['sn.wsd.eip.work.order'].browse(action['res_id'])
        self.assertEqual(work.ipo_no, order.ipo_no)
        self.assertEqual(work.production_order_id, order)
        self.assertEqual(work.category_id, order.category_id)
        self.assertEqual(work.subclass_id, order.subclass_id)
        self.assertEqual(work.materials_code, 'MC-1')
        self.assertEqual(work.amount, '200')
        self.assertEqual(work.unit, 'PCS')
        self.assertEqual(work.wo_status, '1')
        self.assertEqual(work.push_state, 'draft')
        # the material description rides along (user decision 2026-11-25),
        # falling back to the purchase line when the order has none
        self.assertEqual(work.materials_description,
                         'Single-phase smart meter')
        self.assertFalse(work.entity_code)

    def test_65_report_fills_from_work_order(self):
        """Pick a work order on the report: numbers, category, route,
        entity and batch ride along (the picker column itself is not
        stored)."""
        work = self.env['sn.wsd.eip.work.order'].browse(
            self._order(ipo_no='IPO-R').action_create_work_order()['res_id'])
        work.write({'wo_no': 'WO-R', 'materials_batch': 'B2025',
                    'entity_code': 'ENT-X'})
        report = self.env['sn.wsd.eip.process.work'].create({
            'company_id': work.company_id.id,
            'ipo_no': 'TMP', 'wo_no': 'TMP',
        })
        # the picker is a form-only column: set it after create, exactly
        # like the user picking in the UI
        report.work_order_id = work
        report._onchange_work_order_id()
        self.assertEqual(report.wo_no, work.wo_no)
        self.assertEqual(report.ipo_no, work.ipo_no)
        self.assertEqual(report.category_id, work.category_id)
        self.assertEqual(report.subclass_id, work.subclass_id)
        self.assertEqual(report.process_no, work.process_route_no)
        self.assertEqual(report.entity_no, 'ENT-X')
        self.assertEqual(report.product_batch_no, 'B2025')
        report.invalidate_recordset()
        self.assertFalse(report.work_order_id)  # not stored: gone on reload

    def test_61_one_order_can_create_several_work_orders(self):
        order = self._order()
        order.action_create_work_order()
        order.action_create_work_order()
        works = self.env['sn.wsd.eip.work.order'].search(
            [('production_order_id', '=', order.id)])
        self.assertEqual(len(works), 2)
        self.assertEqual(works.mapped('wo_no'), [False, False])

    def test_62_mes_order_brings_out_both_numbers(self):
        """Pick the MES order on the work order: its number is the work
        order number, its manufacturing order the production order
        number."""
        mes_order = self._mes_order('A')
        order = self._order(ipo_no='OLD')
        work = self.env['sn.wsd.eip.work.order'].browse(
            order.action_create_work_order()['res_id'])
        self.assertEqual(work.ipo_no, 'OLD')
        self._pick_mes_order(work, mes_order)
        self.assertEqual(work.wo_no, mes_order.name)
        self.assertEqual(work.ipo_no, mes_order.production_id.name)
        self.assertEqual(work.wo_no, 'MES-A')
        self.assertEqual(work.ipo_no, 'MO-A')
        other = self._mes_order('B')
        self._pick_mes_order(work, other)
        self.assertEqual((work.wo_no, work.ipo_no), ('MES-B', 'MO-B'))

    def test_63_manufacturing_order_brings_out_production_order_no(self):
        mes_order = self._mes_order('C')
        order = self._order()
        self.assertFalse(order.ipo_no)
        order.production_id = mes_order.production_id
        order._onchange_production_id()
        self.assertEqual(order.ipo_no, 'MO-C')

    def test_64_number_is_free_to_type_and_unique(self):
        first = self.env['sn.wsd.eip.work.order'].create({
            'ipo_no': 'IPO-T', 'wo_no': 'TYPED-1'})
        self.assertEqual(first.wo_no, 'TYPED-1')
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.env['sn.wsd.eip.work.order'].create({
                    'ipo_no': 'IPO-T', 'wo_no': 'TYPED-1'})

    def test_65_several_drafts_without_a_number(self):
        """The numbers are not required at save time: drafts may pile
        up without one (the unique constraint ignores empty values)."""
        works = self.env['sn.wsd.eip.work.order'].create([
            {'ipo_no': 'IPO-D1'}, {'ipo_no': 'IPO-D2'},
            {'ipo_no': 'IPO-D3'},
        ])
        self.assertEqual(len(works), 3)
        orders = self.env['sn.wsd.eip.production.order'].create([
            {'po_item_id': '1'}, {'po_item_id': '2'},
        ])
        self.assertEqual(len(orders), 2)

    def test_66_push_refuses_an_empty_work_order_number(self):
        work = self.env['sn.wsd.eip.work.order'].create({
            'ipo_no': 'IPO-9',
            'materials_code': 'MC', 'amount': '1', 'unit': 'PCS',
            'plan_start_date': datetime.date(2027, 1, 1),
            'plan_finish_date': datetime.date(2027, 1, 2),
            'category_id': self.env.ref('sn_wsd_eip.category_30').id,
            'subclass_id': self.env.ref('sn_wsd_eip.subclass_30002').id,
        })
        self.assertFalse(work.wo_no)
        result = work._eip_push_one()
        self.assertFalse(result['success'])
        self.assertIn('Missing required fields', result['error'])
        self.assertEqual(self.server.calls, 0)

    def test_67_push_refuses_an_empty_production_order_number(self):
        order = self._order()
        self.assertFalse(order.ipo_no)
        result = order._eip_push_one()
        self.assertFalse(result['success'])
        self.assertIn('Missing required fields', result['error'])
        self.assertEqual(self.server.calls, 0)

    def test_68_raw_report_copies_the_ledger_numbers(self):
        """The raw-material report keyed by the work order carries the
        same two numbers as the ledger."""
        mes_order = self._mes_order('R')
        work = self.env['sn.wsd.eip.work.order'].browse(
            self._order(ipo_no='OLD').action_create_work_order()['res_id'])
        self._pick_mes_order(work, mes_order)
        Report = self.env['sn.wsd.eip.raw.report']
        report = Report.create({
            'production_order_no': 'TMP',
            'procedure_code': '1012',
            'material_check_batch': 'MB-1',
        })
        report.work_order_id = work
        report._onchange_work_order_id()
        self.assertEqual(report.production_work_no, work.wo_no)
        self.assertEqual(report.production_order_no, work.ipo_no)
        self.assertEqual(report.production_work_no, 'MES-R')
        self.assertEqual(report.production_order_no, 'MO-R')


@tagged('post_install', '-at_install')
class TestEipFormsMasterDetail(EipOrderCase):
    """Batches 7 (+ the deferred child-list scenarios of batches 4/5):
    the master-detail forms, their payloads, line numbering, the supply
    note write-back, the schedule first-push exemption and the daily
    inventory re-push."""

    def _last_request(self):
        return self.server.requests[-1]

    def _sale(self, **values):
        return self.env['sn.wsd.eip.sale.order'].create(dict(
            dict(buyer_name='Grid Example Power Company'), **values))

    def _supply(self, **values):
        values.setdefault('con_type', '3')
        values.setdefault('con_code', 'CON-9')
        values.setdefault('cargo_name', 'Meters')
        values.setdefault('purchase_name', 'Grid Example Power Company')
        return self.env['sn.wsd.eip.supply.note'].create(values)

    def _supply_line(self, note, **values):
        values.setdefault('received_name', 'Grid Warehouse 1')
        values.setdefault('material_code', 'M-1')
        values.setdefault('material_desc', 'Meter')
        values.setdefault('amount', '10')
        values.setdefault('meas_unit', 'PCS')
        values.setdefault(
            'category_id', self.env.ref('sn_wsd_eip.category_30').id)
        values.setdefault(
            'subclass_id', self.env.ref('sn_wsd_eip.subclass_30002').id)
        return self.env['sn.wsd.eip.supply.note.line'].create(
            dict(values, supply_note_id=note.id))

    def _schedule(self, **values):
        values.setdefault('po_item_id', '699708678428688384')
        values.setdefault('due_date', datetime.date(2027, 1, 1))
        values.setdefault(
            'category_id', self.env.ref('sn_wsd_eip.category_30').id)
        values.setdefault(
            'subclass_id', self.env.ref('sn_wsd_eip.subclass_30002').id)
        return self.env['sn.wsd.eip.schedule'].create(values)

    # ------------------------------------------------------------------
    # three-level schedule
    # ------------------------------------------------------------------

    def test_10_schedule_three_levels(self):
        schedule = self._schedule()
        wo_model = self.env['sn.wsd.eip.schedule.wo']
        process_model = self.env['sn.wsd.eip.schedule.process']
        wo_a = wo_model.create({'schedule_id': schedule.id})
        wo_b = wo_model.create({'schedule_id': schedule.id})
        for _index in range(3):
            process_model.create({'schedule_wo_id': wo_a.id})
        process_model.create({'schedule_wo_id': wo_b.id})
        self.assertEqual(len(schedule.wo_ids), 2)
        self.assertEqual(len(wo_a.process_ids), 3)
        self.assertEqual(len(wo_b.process_ids), 1)
        values = schedule._eip_values(self.config)
        self.assertEqual(len(values['woList']), 2)
        self.assertEqual(len(values['woList'][0]['processList']), 3)
        self.assertEqual(len(values['woList'][1]['processList']), 1)

    # ------------------------------------------------------------------
    # payload shapes of the master-detail interfaces
    # ------------------------------------------------------------------

    def test_20_sale_order_payload(self):
        order = self._sale()
        self.env['sn.wsd.eip.sale.order.line'].create(dict(
            sale_order_id=order.id, po_item_id='1001',
            product_code='MC-1', product_name='Meter',
            product_unit='PCS', product_amount='100'))
        self.env['sn.wsd.eip.sale.order.line'].create(dict(
            sale_order_id=order.id, po_item_id='1002',
            product_code='MC-2', product_name='Meter 2',
            product_unit='PCS', product_amount='200'))
        values = order._eip_values(self.config)
        self.assertEqual(values['soNo'], order.so_no)
        self.assertEqual(values['buyerName'], 'Grid Example Power Company')
        self.assertEqual(len(values['itemList']), 2)
        line_values = values['itemList'][0]
        self.assertEqual(line_values['soItemNo'], '0010')
        self.assertEqual(line_values['poItemId'], '1001')
        self.assertEqual(line_values['productAmount'], '100')

    def test_30_inventory_payloads(self):
        raw = self.env['sn.wsd.eip.raw.inventory'].create({
            'mat_name': 'Chip', 'mat_code': 'RAW-1', 'mat_num': '50',
            'mat_unit': 'PCS'})
        self.env['sn.wsd.eip.raw.inventory.line'].create(
            dict(inventory_id=raw.id, batch_code='B1', product_amount='30'))
        spare = self.env['sn.wsd.eip.spare.inventory'].create({
            'spare_product_code': 'SP-1', 'product_dec': 'Spare',
            'product_amount': '5', 'product_unit': 'PCS'})
        self.env['sn.wsd.eip.spare.inventory.line'].create(
            dict(inventory_id=spare.id, product_lot='L1',
                 product_amount='2', remark='x'))
        finished = self.env['sn.wsd.eip.finished.inventory'].create({
            'product_code': '30002', 'product_name': '电能表',
            'product_amount': '12', 'product_unit': 'PCS'})
        self.env['sn.wsd.eip.finished.inventory.line'].create(
            dict(inventory_id=finished.id, batch_code='F1',
                 product_amount='7', data_source='0'))
        raw_values = raw._eip_values(self.config)
        spare_values = spare._eip_values(self.config)
        finished_values = finished._eip_values(self.config)
        # the three detail arrays use the three different keys of the spec
        self.assertEqual(len(raw_values['data']), 1)
        self.assertEqual(raw_values['data'][0]['batchCode'], 'B1')
        self.assertEqual(len(spare_values['itemList']), 1)
        self.assertEqual(spare_values['itemList'][0]['productLot'], 'L1')
        self.assertEqual(len(finished_values['itemList']), 1)
        self.assertEqual(finished_values['itemList'][0]['dataSource'], '0')
        # the finished product carries the subclass as the code
        self.assertEqual(finished_values['productCode'], '30002')

    def test_31_finished_picks_the_subclass(self):
        finished = self.env['sn.wsd.eip.finished.inventory'].create({
            'subclass_id': self.env.ref('sn_wsd_eip.subclass_30002').id,
            'product_code': 'X'})
        finished._onchange_subclass_id()
        self.assertEqual(finished.product_code, '30002')
        self.assertEqual(finished.product_name, '电能表')

    # ------------------------------------------------------------------
    # sequential line numbers (0010 step)
    # ------------------------------------------------------------------

    def test_40_line_numbers(self):
        note = self._supply()
        self._supply_line(note)
        self._supply_line(note)
        self._supply_line(note)
        self.assertEqual(note.line_ids.mapped('po_item_no'),
                         ['0010', '0020', '0030'])
        # numbering also works when several lines arrive in one create
        sale2 = self._sale()
        self.env['sn.wsd.eip.sale.order.line'].create([
            dict(sale_order_id=sale2.id, po_item_id='1',
                 product_code='A', product_name='A', product_unit='U',
                 product_amount='1'),
            dict(sale_order_id=sale2.id, po_item_id='2',
                 product_code='B', product_name='B', product_unit='U',
                 product_amount='2'),
        ])
        self.assertEqual(sale2.line_ids.mapped('so_item_no'),
                         ['0010', '0020'])

    # ------------------------------------------------------------------
    # deferred scenarios of batches 4/5: child lists and re-queue
    # ------------------------------------------------------------------

    def test_50_child_edit_requeues(self):
        note = self._supply()
        self._supply_line(note)
        self.server.enqueue(eip_envelope())
        self.assertTrue(note._eip_push_one()['success'])
        self.server.reset()
        # adding a line re-queues the note
        self._supply_line(note)
        self.assertEqual(note.push_state, 'to_push')
        entries = self.env['sn.wsd.eip.push.queue'].search(
            [('model_name', '=', note._name), ('res_id', '=', note.id)])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.state, 'pending')
        # ...and the next push carries both lines
        self.server.enqueue(eip_envelope())
        self.assertTrue(note._eip_push_one()['success'])
        body = self._last_request()['json']
        self.assertEqual(len(body['itemList']), 2)

    def test_51_child_list_carries_every_row(self):
        order = self._sale()
        line_a = self.env['sn.wsd.eip.sale.order.line'].create(dict(
            sale_order_id=order.id, po_item_id='1001',
            category_id=self.env.ref('sn_wsd_eip.category_30').id,
            subclass_id=self.env.ref('sn_wsd_eip.subclass_30002').id,
            product_code='MC-1', product_name='Meter',
            product_unit='PCS', product_amount='100'))
        self.env['sn.wsd.eip.sale.order.line'].create(dict(
            sale_order_id=order.id, po_item_id='1002',
            category_id=self.env.ref('sn_wsd_eip.category_30').id,
            subclass_id=self.env.ref('sn_wsd_eip.subclass_30002').id,
            product_code='MC-2', product_name='Meter 2',
            product_unit='PCS', product_amount='200'))
        self.server.enqueue(eip_envelope())
        self.assertTrue(order._eip_push_one()['success'], order.eip_last_error)
        self.server.reset()
        line_a.product_amount = '150'  # writes the line, re-queues the order
        self.assertEqual(order.push_state, 'to_push')
        self.server.enqueue(eip_envelope())
        self.assertTrue(order._eip_push_one()['success'], order.eip_last_error)
        body = self._last_request()['json']
        self.assertEqual(self._last_request()['headers']['operatetype'],
                         'UPDATE')
        self.assertEqual(len(body['itemList']), 2)
        self.assertEqual(
            [row['soItemNo'] for row in body['itemList']],
            ['0010', '0020'])
        self.assertEqual(body['itemList'][0]['productAmount'], '150')
        self.assertEqual(body['itemList'][1]['productAmount'], '200')

    # ------------------------------------------------------------------
    # supply note write-back of the returned line IDs
    # ------------------------------------------------------------------

    def test_60_supply_writeback(self):
        note = self._supply()
        self._supply_line(note)  # numbered 0010
        self._supply_line(note)  # numbered 0020
        self.server.enqueue(eip_envelope(
            data='0010:699708678428688384&0020:699708678428688385'))
        self.assertTrue(note._eip_push_one()['success'])
        self.assertEqual(
            note.line_ids.sorted('po_item_no').mapped('eip_item_id'),
            ['699708678428688384', '699708678428688385'])
        self.assertEqual(
            note.eip_result_data,
            '0010:699708678428688384&0020:699708678428688385')
        # the write-back is not a business change: nothing re-queued
        self.assertEqual(note.push_state, 'pushed')
        self.assertFalse(self.env['sn.wsd.eip.push.queue'].search([
            ('model_name', '=', note._name), ('res_id', '=', note.id),
            ('state', 'in', ('pending', 'pushing'))]))

    def test_61_supply_writeback_with_malformed_segments(self):
        note = self._supply()
        self._supply_line(note)
        self._supply_line(note)
        self.server.enqueue(eip_envelope(
            data='0010:699708678428688384&broken&0020:'))
        self.assertTrue(note._eip_push_one()['success'])
        lines = note.line_ids.sorted('po_item_no')
        self.assertEqual(lines[0].eip_item_id, '699708678428688384')
        self.assertFalse(lines[1].eip_item_id)
        self.assertEqual(
            note.eip_result_data,
            '0010:699708678428688384&broken&0020:')

    def test_62_supply_number_locked_after_push(self):
        note = self._supply()
        self._supply_line(note)
        self.server.enqueue(eip_envelope(
            data='0010:699708678428688384'))
        self.assertTrue(note._eip_push_one()['success'])
        with self.assertRaisesRegex(UserError, 'locate it there'):
            note.write({'supply_no': 'SN-CHANGED'})

    # ------------------------------------------------------------------
    # schedule: the first push may leave plan dates and amounts empty
    # ------------------------------------------------------------------

    def test_70_schedule_first_push_exemption(self):
        schedule = self._schedule()
        self.env['sn.wsd.eip.schedule.wo'].create({
            'schedule_id': schedule.id,
            'batch_code': 'B1', 'schedule_wo': 'SWO-1',
            'mat_code': 'M-1', 'mat_desc': 'Meter',
            'schedule_unit': 'PCS'})
        self.assertFalse(schedule.eip_missing)
        self.server.enqueue(eip_envelope())
        result = schedule._eip_push_one()
        self.assertTrue(result['success'], result)
        self.assertEqual(
            self._last_request()['headers']['operatetype'], 'ADD')
        body = self._last_request()['json']
        self.assertEqual(body['planStartDate'], '')
        self.assertEqual(body['planPeriod'], '')
        self.assertEqual(body['woList'][0]['scheduleAmount'], '')

    def test_71_schedule_delivery_date_still_required(self):
        schedule = self.env['sn.wsd.eip.schedule'].create({
            'po_item_id': '699708678428688384',
            'category_id': self.env.ref('sn_wsd_eip.category_30').id,
            'subclass_id': self.env.ref('sn_wsd_eip.subclass_30002').id})
        self.assertIn('Delivery Date', schedule.eip_missing)

    # ------------------------------------------------------------------
    # daily inventory re-push
    # ------------------------------------------------------------------

    def test_80_daily_inventory_repushes_pushed_only(self):
        finished_pushed = self.env['sn.wsd.eip.finished.inventory'].create({
            'product_code': '30002', 'product_name': '电能表',
            'product_amount': '12', 'product_unit': 'PCS'})
        spare_pushed = self.env['sn.wsd.eip.spare.inventory'].create({
            'spare_product_code': 'SP-1', 'product_dec': 'Spare',
            'product_amount': '5', 'product_unit': 'PCS'})
        spare_draft = self.env['sn.wsd.eip.spare.inventory'].create({
            'spare_product_code': 'SP-2', 'product_dec': 'Spare 2',
            'product_amount': '3', 'product_unit': 'PCS'})
        for doc in (finished_pushed, spare_pushed):
            self.server.enqueue(eip_envelope())
            doc._eip_push_one()
        self.server.reset()
        self.env['sn.wsd.eip.push.worker'].run_daily_inventory()
        queued = self.env['sn.wsd.eip.push.queue'].search(
            [('state', '=', 'pending')])
        queued_docs = {entry.model_name: entry.res_id for entry in queued}
        self.assertEqual(queued_docs.get(finished_pushed._name),
                         finished_pushed.id)
        self.assertEqual(queued_docs.get(spare_pushed._name), spare_pushed.id)
        spare_ids = self.env['sn.wsd.eip.push.queue'].search(
            [('model_name', '=', spare_draft._name)]).mapped('res_id')
        self.assertNotIn(spare_draft.id, spare_ids)

    def test_81_daily_inventory_cron_ships_paused(self):
        cron = self.env.ref('sn_wsd_eip.ir_cron_eip_daily_inventory')
        self.assertFalse(cron.active)
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.interval_type, 'days')

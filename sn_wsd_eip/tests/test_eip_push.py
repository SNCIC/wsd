"""Batches 4 and 5 of the eip-order-push change: push engine.

The production order is the pilot document: it carries every trait of
the single-table interfaces. Covers the push state machine, the
ADD / UPDATE decision, the UPDATE diff rules, the required-field gate
and the duplicate (20006) fallback of the eip-business-push spec.
"""

import datetime

from odoo.exceptions import UserError
from odoo.tests import tagged

from .eip_order_common import EipOrderCase, eip_envelope

PRODUCTION_ORDER_KEYS = (
    'purchaserHqCode', 'ipoType', 'supplierCode', 'supplierName', 'ipoNo',
    'categoryCode', 'subclassCode', 'scheduleCode', 'poItemId', 'dataType',
    'soItemNo', 'materialsCode', 'materialsName', 'materialsUnit',
    'materialsDesc', 'amount', 'unit', 'productIdGrpNo', 'productIdType',
    'productModel', 'planStartDate', 'planFinishDate', 'actualStartDate',
    'actualFinishDate', 'plantName', 'workshopName', 'ipoStatus', 'center',
    'dataSource', 'dataSourceCreateTime', 'ownerId', 'openId',
)
# keys an UPDATE locates the production order by (UPDATE-required)
LOCATE_KEYS = ('supplierCode', 'supplierName', 'ipoNo', 'poItemId',
               'dataType', 'dataSourceCreateTime')


@tagged('post_install', '-at_install')
class TestEipPush(EipOrderCase):

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

    def _last_request(self):
        return self.server.requests[-1]

    def _logs(self):
        return self.env['sn.wsd.eip.push.log'].search([], order='id')

    # ------------------------------------------------------------------
    # state machine
    # ------------------------------------------------------------------

    def test_10_new_document_is_draft(self):
        order = self._order()
        self.assertEqual(order.push_state, 'draft')
        self.assertFalse(order.eip_synced)
        self.assertEqual(self.server.calls, 0)
        self.assertTrue(order.ipo_no)
        self.assertEqual(order.category_id.code, '30')
        self.assertEqual(order.subclass_id.code, '30002')

    def test_11_manual_push_succeeds(self):
        self.server.enqueue(eip_envelope(data='0500626736'))
        order = self._order()
        result = order._eip_push_one()
        self.assertTrue(result['success'], result)
        self.assertEqual(result['status'], '00000')
        self.assertEqual(order.push_state, 'pushed')
        self.assertTrue(order.eip_synced)
        self.assertTrue(order.eip_last_push_at)
        self.assertEqual(order.eip_push_count, 1)
        self.assertFalse(order.eip_last_error)
        # the log points back at the document
        log = self._logs()
        self.assertEqual(len(log), 1)
        self.assertEqual(log.model_name, order._name)
        self.assertEqual(log.res_id, order.id)
        self.assertEqual(log.document_ref, order.ipo_no)
        self.assertEqual(order.eip_last_log_id, log)
        self.assertEqual(order.eip_log_count, 1)

    # ------------------------------------------------------------------
    # ADD / UPDATE is decided by the engine
    # ------------------------------------------------------------------

    def test_20_first_push_is_add_with_every_value(self):
        order = self._order(plant_name='Plant A')
        result = order._eip_push_one()
        self.assertTrue(result['success'], result)
        request = self._last_request()
        self.assertEqual(request['path'], '/api/supplier-ipo')
        self.assertEqual(request['headers']['operatetype'], 'ADD')
        body = request['json']
        self.assertEqual(set(body), set(PRODUCTION_ORDER_KEYS))
        self.assertEqual(body['purchaserHqCode'], 'SGCC')
        self.assertEqual(body['supplierCode'], 'SUP-1')
        self.assertEqual(body['supplierName'], 'Supplier One')
        self.assertEqual(body['ipoType'], '0')
        self.assertEqual(body['ipoNo'], order.ipo_no)
        self.assertEqual(body['categoryCode'], '30')
        self.assertEqual(body['subclassCode'], '30002')
        self.assertEqual(body['poItemId'], '699708678428688384')
        self.assertEqual(body['dataType'], '1')
        self.assertEqual(body['materialsCode'], 'MC-1')
        self.assertEqual(body['amount'], '200')
        self.assertEqual(body['planStartDate'], '2026-12-01')
        self.assertEqual(body['planFinishDate'], '2026-12-31')
        self.assertEqual(body['dataSource'], '0')
        self.assertEqual(body['plantName'], 'Plant A')
        self.assertEqual(body['dataSourceCreateTime'],
                         self.transport._eip_format_datetime(order.create_date))
        # neither required nor filled: nothing is invented
        self.assertEqual(body['ipoStatus'], '')
        self.assertEqual(body['ownerId'], '')
        self.assertEqual(body['openId'], '')
        self.assertEqual(body['scheduleCode'], '')

    def test_21_push_after_a_change_is_update(self):
        order = self._order(center='Center A')
        order._eip_push_one()
        order.write({'plan_finish_date': datetime.date(2027, 1, 15)})
        result = order._eip_push_one()
        self.assertTrue(result['success'], result)
        request = self._last_request()
        self.assertEqual(request['headers']['operatetype'], 'UPDATE')
        body = request['json']
        # every key is present
        self.assertEqual(set(body), set(PRODUCTION_ORDER_KEYS))
        # changed: the new value
        self.assertEqual(body['planFinishDate'], '2027-01-15')
        # unchanged: the empty string
        for key in ('materialsCode', 'materialsName', 'planStartDate',
                    'purchaserHqCode', 'amount', 'unit'):
            self.assertEqual(body[key], '', key)
        # empty before and after: still the empty string
        self.assertEqual(body['plantName'], '')
        self.assertEqual(body['ipoStatus'], '')
        # locate keys always carry their real value
        for key in LOCATE_KEYS:
            self.assertTrue(body[key], key)
        self.assertEqual(body['supplierCode'], 'SUP-1')
        self.assertEqual(body['ipoNo'], order.ipo_no)
        self.assertEqual(order.eip_push_count, 2)

    # ------------------------------------------------------------------
    # UPDATE diff rules
    # ------------------------------------------------------------------

    def test_22_cleared_field_is_the_null_string(self):
        order = self._order(center='Center A')
        order._eip_push_one()
        order.write({'center': False})
        order._eip_push_one()
        body = self._last_request()['json']
        self.assertEqual(body['center'], 'null')
        self.assertIsInstance(body['center'], str)

    def test_23_full_mode_sends_every_value(self):
        self.config.write({'update_mode': 'full'})
        order = self._order(center='Center A')
        order._eip_push_one()
        order.write({'center': False})
        order._eip_push_one()
        body = self._last_request()['json']
        self.assertEqual(self._last_request()['headers']['operatetype'], 'UPDATE')
        self.assertEqual(body['materialsCode'], 'MC-1')
        self.assertEqual(body['amount'], '200')
        self.assertEqual(body['center'], '')

    # ------------------------------------------------------------------
    # required-field gate
    # ------------------------------------------------------------------

    def test_30_missing_field_blocks_the_push(self):
        order = self._order(materials_code=False)
        self.assertIn('Material Code', order.eip_missing)
        result = order._eip_push_one()
        self.assertFalse(result['success'])
        self.assertFalse(result['sent'])
        self.assertEqual(self.server.calls, 0)
        self.assertEqual(order.push_state, 'failed')
        self.assertIn('Missing required fields', order.eip_last_error)
        self.assertIn('Material Code', order.eip_last_error)
        self.assertEqual(self._logs(), self.env['sn.wsd.eip.push.log'])

    def test_31_filled_document_pushes(self):
        order = self._order(materials_code=False, amount=False)
        order._eip_push_one()
        order.write({'materials_code': 'MC-9', 'amount': '150'})
        self.assertFalse(order.eip_missing)
        self.assertTrue(order._eip_push_one()['success'])
        self.assertEqual(self.server.calls, 1)
        self.assertEqual(order.push_state, 'pushed')

    # ------------------------------------------------------------------
    # duplicate on ADD: update instead
    # ------------------------------------------------------------------

    def test_40_duplicate_on_add_switches_to_update(self):
        self.server.enqueue(eip_envelope(status='20006', message='duplicate'))
        self.server.enqueue(eip_envelope(data='0500626736'))
        order = self._order(center='Center A')
        result = order._eip_push_one()
        self.assertTrue(result['success'], result)
        self.assertEqual(self.server.calls, 2)
        self.assertEqual(
            [request['headers']['operatetype'] for request in self.server.requests],
            ['ADD', 'UPDATE'])
        # against an empty baseline every filled field carries its value
        body = self._last_request()['json']
        self.assertEqual(body['ipoNo'], order.ipo_no)
        self.assertEqual(body['materialsCode'], 'MC-1')
        self.assertEqual(body['center'], 'Center A')
        self.assertEqual(body['plantName'], '')
        self.assertEqual(order.push_state, 'pushed')
        self.assertTrue(order.eip_synced)
        logs = self._logs()
        self.assertEqual(logs.mapped('operatetype'), ['ADD', 'UPDATE'])
        self.assertEqual(logs.mapped('status_code'), ['20006', '00000'])
        self.assertEqual(logs.mapped('result'), ['failed', 'success'])

    def test_41_update_after_duplicate_still_failing(self):
        self.server.enqueue(eip_envelope(status='20006', message='duplicate'))
        self.server.enqueue(eip_envelope(status='10002', message='too long'))
        order = self._order()
        result = order._eip_push_one()
        self.assertFalse(result['success'])
        self.assertEqual(order.push_state, 'failed')
        self.assertIn('10002', order.eip_last_error)
        self.assertFalse(order.eip_synced)
        logs = self._logs()
        self.assertEqual(logs.mapped('operatetype'), ['ADD', 'UPDATE'])
        self.assertEqual(logs.mapped('result'), ['failed', 'failed'])
        self.assertEqual(order.eip_last_log_id, logs[-1])

    # ------------------------------------------------------------------
    # guards before any request
    # ------------------------------------------------------------------

    def test_50_disabled_interface_or_missing_config_blocks(self):
        order = self._order()
        interface = self.env['sn.wsd.eip.interface']._eip_interface(
            'production_order')
        interface.active = False
        with self.assertRaisesRegex(UserError, 'is disabled'):
            order._eip_push_one()
        interface.active = True
        self.config.active = False
        with self.assertRaisesRegex(UserError, 'No active EIP integration config'):
            order._eip_push_one()
        self.assertEqual(self.server.calls, 0)

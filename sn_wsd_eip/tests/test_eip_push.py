"""Batches 4 and 5 of the eip-order-push change: push engine.

The production order is the pilot document: it carries every trait of
the single-table interfaces. Covers the push state machine, the
ADD / UPDATE decision, the UPDATE diff rules, the required-field gate
and the duplicate (20006) fallback of the eip-business-push spec.
"""

import datetime
import json
from unittest.mock import patch

from odoo import fields
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

    def test_51_locate_keys_locked_after_push(self):
        order = self._order()
        order._eip_push_one()
        with self.assertRaisesRegex(UserError, 'locate it there'):
            order.write({'ipo_no': 'IPO-CHANGED'})
        with self.assertRaisesRegex(UserError, 'locate it there'):
            order.write({'po_item_id': '999'})
        # engine fields stay writable, and non-locate business fields too
        order.write({'center': 'C'})
        self.assertEqual(order.center, 'C')


@tagged('post_install', '-at_install')
class TestEipPushQueue(EipOrderCase):

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

    def _pushed(self, **values):
        self.server.enqueue(eip_envelope())
        order = self._order(**values)
        order._eip_push_one()
        self.assertTrue(order.eip_synced)
        self.server.reset()
        return order

    def _queue(self):
        return self.env['sn.wsd.eip.push.queue'].search([], order='id')

    def _last_request(self):
        return self.server.requests[-1]

    def _run(self):
        self.env['sn.wsd.eip.push.worker'].run_push()

    # ------------------------------------------------------------------
    # edited after a push: automatically queued again
    # ------------------------------------------------------------------

    def test_10_main_field_edit_requeues(self):
        order = self._pushed()
        order.write({'actual_start_date': datetime.date(2026, 12, 5)})
        self.assertEqual(order.push_state, 'to_push')
        entries = self._queue()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries.state, 'pending')
        self.assertEqual(entries.retry_count, 0)
        self.assertFalse(entries.next_attempt_at)
        self.assertEqual(order.eip_queue_id, entries)

    def test_11_draft_edits_stay_draft(self):
        order = self._order()
        order.write({'center': 'C'})
        self.assertEqual(order.push_state, 'draft')
        self.assertFalse(self._queue())

    def test_12_engine_writes_do_not_requeue(self):
        order = self._pushed()
        entries = self._queue()
        self.assertFalse(entries)
        # replay an engine write: no queue row appears
        order.write({'eip_last_push_at': fields.Datetime.now()})
        self.assertFalse(self._queue())
        self.assertEqual(order.push_state, 'pushed')

    def test_13_child_line_edit_requeues(self):
        # the production order has no child table; the line hook is
        # exercised with a scratch model inheriting the line mixin
        self.skipTest('covered by the supply-note tests of batch 7')

    # ------------------------------------------------------------------
    # the worker: claim, push, retry
    # ------------------------------------------------------------------

    def test_20_worker_pushes_queued_draft(self):
        order = self._order()
        order.action_eip_queue_push()
        self.assertEqual(order.push_state, 'to_push')
        self._run()
        self.assertEqual(self.server.calls, 1)
        self.assertEqual(order.push_state, 'pushed')
        self.assertTrue(order.eip_synced)
        entry = self._queue()
        self.assertEqual(entry.state, 'done')
        self.assertEqual(self._last_request()['headers']['operatetype'], 'ADD')

    def test_21_worker_updates_edited_document(self):
        order = self._pushed()
        order.write({'center': 'Center B'})
        self._run()
        self.assertEqual(self.server.calls, 1)
        self.assertEqual(
            self._last_request()['headers']['operatetype'], 'UPDATE')
        self.assertEqual(self._last_request()['json']['center'], 'Center B')
        self.assertEqual(order.push_state, 'pushed')
        self.assertEqual(self._queue().state, 'done')

    def test_22_retryable_failure_schedules_retry_then_fails(self):
        order = self._pushed()
        order.write({'center': 'C'})
        self.config.write({'retry_times': 1, 'retry_interval_min': 10})
        # 1st run: platform error 90003 (retryable)
        self.server.enqueue(eip_envelope(status='90003', message='system error',
                                         successful=False))
        self._run()
        entry = self._queue()
        self.assertEqual(entry.state, 'pending')
        self.assertEqual(entry.retry_count, 1)
        self.assertTrue(entry.next_attempt_at)
        self.assertEqual(order.push_state, 'to_push')
        # 2nd run: the row waits for its next attempt, nothing is sent
        self.server.reset()
        self._run()
        self.assertEqual(self.server.calls, 0)
        self.assertEqual(entry.state, 'pending')
        # 3rd run after the wait: it fails again, the retry is used up
        entry.write({'next_attempt_at': False})
        self.server.enqueue(eip_envelope(status='90003', message='system error',
                                         successful=False))
        self._run()
        entry.invalidate_recordset()
        self.assertEqual(entry.state, 'failed')
        self.assertEqual(entry.retry_count, 1)
        self.assertEqual(order.push_state, 'failed')

    def test_23_data_error_never_autoretries(self):
        order = self._pushed()
        order.write({'center': 'C'})
        self.config.write({'retry_times': 3})
        self.server.enqueue(eip_envelope(status='10002', message='too long'))
        self._run()
        entry = self._queue()
        self.assertEqual(entry.state, 'failed')
        self.assertEqual(entry.retry_count, 0)
        self.assertFalse(entry.next_attempt_at)
        self.assertEqual(order.push_state, 'failed')
        self.assertEqual(self.server.calls, 1)

    def test_24_edit_after_failure_resets_the_retries(self):
        order = self._pushed()
        order.write({'center': 'C'})
        self.server.enqueue(eip_envelope(status='10002', message='too long'))
        self._run()
        entry = self._queue()
        self.assertEqual(entry.state, 'failed')
        entry.write({'retry_count': 3})
        # a business edit re-queues with a clean retry counter: the
        # failed row stays as history, a fresh pending row appears
        order.write({'center': 'C2'})
        entries = self._queue()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].state, 'failed')
        self.assertEqual(entries[0].retry_count, 3)
        self.assertEqual(entries[1].state, 'pending')
        self.assertEqual(entries[1].retry_count, 0)
        self.assertEqual(order.push_state, 'to_push')

    def test_25_edited_while_pushing_is_requeued_after_success(self):
        order = self._pushed()
        order.write({'center': 'C'})
        # the edit races the request: it lands after the body was built
        # but before the answer arrives (same thread, via the transport)
        original_send = type(self.env['sn.wsd.eip.transport'])._eip_send

        def send(transport, log, body):
            order.write({'center': 'C2'})
            return original_send(transport, log, body)
        with patch.object(type(self.env['sn.wsd.eip.transport']),
                          '_eip_send', send):
            self._run()
        # the platform learned "C" (the body was built before the edit)
        self.assertEqual(self._last_request()['json']['center'], 'C')
        self.assertEqual(order.push_state, 'to_push')
        entries = self._queue()
        # the run's row is done, a fresh row carries the newer edit
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].state, 'done')
        self.assertEqual(entries[1].state, 'pending')
        self.assertEqual(entries[1].retry_count, 0)
        # and the next run pushes the newer value
        self.server.enqueue(eip_envelope())
        self._run()
        self.assertEqual(
            self._last_request()['json']['center'], 'C2')
        self.assertEqual(order.push_state, 'pushed')

    def test_26_already_pushed_and_clean_row_is_closed_without_request(self):
        order = self._pushed()
        order.write({'center': 'C'})
        # pushed manually before the worker runs
        self.server.enqueue(eip_envelope())
        order._eip_push_one()
        self.server.reset()
        self._run()
        self.assertEqual(self.server.calls, 0)
        self.assertEqual(self._queue().state, 'done')
        self.assertEqual(order.push_state, 'pushed')

    # ------------------------------------------------------------------
    # claim and batch behaviour
    # ------------------------------------------------------------------

    def test_30_claim_is_atomic_and_batched(self):
        self.config.write({'push_batch_size': 2})
        orders = self._pushed() + self._pushed() + self._pushed()
        for order in orders:
            order.write({'center': 'C'})
        self.assertEqual(len(self._queue().filtered(
            lambda entry: entry.state == 'pending')), 3)
        worker = self.env['sn.wsd.eip.push.worker']
        # the batch size caps the claim
        claimed = worker._eip_claim(self.config, 2)
        self.assertEqual(len(claimed), 2)
        self.assertEqual(claimed.mapped('state'), ['pushing', 'pushing'])
        # claimed rows are never handed out again; the third pending
        # row is
        again = worker._eip_claim(self.config, 2)
        self.assertEqual(len(again), 1)
        self.assertFalse(claimed & again)
        self.assertFalse(worker._eip_claim(self.config, 2))

    def test_31_one_failure_does_not_stop_the_batch(self):
        self.config.write({'push_batch_size': 10})
        order_a = self._pushed(po_item_id='111')
        order_b = self._pushed(po_item_id='222')
        order_a.write({'center': 'A'})
        order_b.write({'center': 'B'})
        self.server.set_responder(lambda request: eip_envelope(
            status='10002', message='too long', successful=False)
            if request['json']['ipoNo'] == order_a.ipo_no
            else eip_envelope())
        self._run()
        entry_a, entry_b = self._queue()
        self.assertEqual(entry_a.state, 'failed')
        self.assertEqual(entry_a._eip_document(), order_a)
        self.assertEqual(entry_b.state, 'done')
        self.assertEqual(entry_b._eip_document(), order_b)
        self.assertEqual(order_b.push_state, 'pushed')

    def test_32_cron_ships_paused(self):
        cron = self.env.ref('sn_wsd_eip.ir_cron_eip_push_queue')
        self.assertFalse(cron.active)
        self.assertEqual(cron.interval_number, 5)
        self.assertEqual(cron.interval_type, 'minutes')

    # ------------------------------------------------------------------
    # preview: headers and body, nothing sent
    # ------------------------------------------------------------------

    def test_40_preview_of_draft_is_add(self):
        order = self._order(center='Center A')
        preview = self.env['sn.wsd.eip.push.preview'].with_context(
            active_model=order._name, active_id=order.id).create({})
        self.assertEqual(preview.operatetype, 'ADD')
        body = json.loads(preview.body_text)
        self.assertEqual(body['center'], 'Center A')
        self.assertEqual(body['ipoNo'], order.ipo_no)
        headers = json.loads(preview.headers_text)
        self.assertEqual(headers['operatetype'], 'ADD')
        self.assertEqual(headers['orisys'], '0')
        self.assertEqual(self.server.calls, 0)
        self.assertEqual(order.push_state, 'draft')

    def test_41_preview_after_push_is_diff_update(self):
        order = self._pushed(center='Center A')
        order.write({'center': 'Center B'})
        preview = self.env['sn.wsd.eip.push.preview'].with_context(
            active_model=order._name, active_id=order.id).create({})
        self.assertEqual(preview.operatetype, 'UPDATE')
        body = json.loads(preview.body_text)
        self.assertEqual(body['center'], 'Center B')
        self.assertEqual(body['materialsCode'], '')
        self.assertEqual(body['ipoNo'], order.ipo_no)
        self.assertEqual(self.server.calls, 0)

    def test_42_preview_needs_a_document(self):
        with self.assertRaisesRegex(UserError, 'not pushed to EIP'):
            self.env['sn.wsd.eip.push.preview'].with_context(
                active_model='res.partner', active_id=1).create({})


"""Batch 3 of the eip-order-push change: purchase-order pull.

Covers every requirement of the eip-purchase-order-sync spec: the
master-detail mirror, the frozen incremental window, pageNum paging,
the hard daily limit (counted before each request), breakpoint resume,
manual and scheduled pulls.
"""

import datetime
import json
from unittest.mock import patch

from odoo.addons.sn_wsd_eip.models.eip_pull import PULL_LOCK_NAMESPACE
from odoo import fields
from odoo.exceptions import UserError
from odoo.sql_db import db_connect
from odoo.tests import tagged

from .eip_order_common import EipOrderCase, eip_envelope, eip_page


def po_row(item_id, po_no='PO1', item_no='0010', **overrides):
    """One purchase-order line as the platform returns it (every key of
    the response table)."""
    row = {
        'poNo': po_no,
        'poItemNo': item_no,
        'poItemId': item_id,
        'conCode': 'CON-1',
        'conName': 'Meter Supply Contract',
        'buyerName': 'Grid Example Power Company',
        'buyerCode': 'BUY-1',
        'materialCode': 'M-001',
        'materialDesc': 'Single-phase meter',
        'amount': '100',
        'sellerConCode': 'SC-1',
        'serialNumber': 'TS-1',
        'sellerSignTime': '2026-11-01',
        'conType': '1',
        'prjCode': 'PRJ-1',
        'prjName': 'Project A',
        'matCode': '5001001',
        'fixedTechId': 'FT-1',
        'pkgNo': 'PKG-1',
        'bidBatCode': 'BID-1',
        'extDes': 'Fixed technical ID description',
        'matMaxCode': '30',
        'matMedCode': '30002',
        'matMinCode': '3000201',
        'matMaxName': 'Meters',
        'matMedName': 'Electricity meter',
        'matMinName': 'Smart meter',
        'modifyTime': '2026-11-20 10:00:00',
    }
    row.update(overrides)
    return row


def system_error():
    return eip_envelope(status='90003', message='system error',
                        successful=False)


@tagged('post_install', '-at_install')
class TestEipPull(EipOrderCase):

    # fixed clock of the window tests: 09:00 and 10:00 Beijing time
    NOW = datetime.datetime(2026, 11, 24, 1, 0, 0)
    WATERMARK = datetime.datetime(2026, 11, 23, 2, 0, 0)
    BEIJING_NOW = datetime.datetime(2026, 11, 24, 9, 0, 0)

    def _state(self):
        return self.env['sn.wsd.eip.pull.state'].search(
            [('config_id', '=', self.config.id)], limit=1)

    def _lines(self):
        return self.env['sn.wsd.eip.purchase.order.line'].search([])

    def _pages_sent(self):
        return [request['json']['pageNum'] for request in self.server.requests]

    def _today(self):
        return self.transport._eip_now().date()

    def _wizard(self, **values):
        values.setdefault('config_id', self.config.id)
        return self.env['sn.wsd.eip.pull.wizard'].create(values)

    # ------------------------------------------------------------------
    # master-detail mirror, idempotent upsert
    # ------------------------------------------------------------------

    def test_10_pull_creates_order_and_lines(self):
        self.server.enqueue(eip_page(
            [po_row('1001'), po_row('1002', item_no='0020')],
            1, 1000, 1, 2))
        result = self.config._eip_pull_incremental()
        self.assertEqual(
            (result['reason'], result['pages'], result['rows']),
            ('done', 1, 2))
        order = self.env['sn.wsd.eip.purchase.order'].search([])
        self.assertEqual(len(order), 1)
        self.assertEqual(order.po_no, 'PO1')
        self.assertEqual(order.con_code, 'CON-1')
        self.assertEqual(order.con_name, 'Meter Supply Contract')
        self.assertEqual(order.buyer_name, 'Grid Example Power Company')
        self.assertEqual(order.con_type, '1')
        self.assertEqual(order.line_count, 2)
        lines = self._lines()
        self.assertEqual(sorted(lines.mapped('po_item_id')),
                         ['1001', '1002'])
        self.assertEqual(set(lines.mapped('order_id')), set(order))
        line = lines.filtered(lambda rec: rec.po_item_id == '1001')
        self.assertEqual(line.material_code, 'M-001')
        self.assertEqual(line.material_desc, 'Single-phase meter')
        self.assertEqual(line.amount, '100')
        self.assertEqual(line.seller_sign_time, datetime.date(2026, 11, 1))
        # platform times are Beijing wall-clock values, stored in UTC
        self.assertEqual(line.modify_time,
                         datetime.datetime(2026, 11, 20, 2, 0, 0))

    def test_11_repull_updates_without_duplicates(self):
        self.server.enqueue(eip_page([po_row('1001', amount='100')],
                                     1, 1000, 1, 1))
        self.config._eip_pull_incremental()
        # the overlap brings the same line back with a new quantity
        self.server.enqueue(eip_page([po_row('1001', amount='150')],
                                     1, 1000, 1, 1))
        self.config._eip_pull_incremental()
        lines = self._lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.amount, '150')
        self.assertEqual(
            self.env['sn.wsd.eip.purchase.order'].search_count([]), 1)
        self.assertEqual(self.server.calls, 2)

    def test_12_long_line_id_and_decimal_text_are_kept(self):
        long_id = 699708678428688384
        body = json.dumps(eip_page(
            [dict(po_row('X', amount='1'), poItemId=long_id),
             po_row('1002')],
            1, 1000, 1, 2))
        # the platform may send quantities as JSON numbers: keep the text
        body = body.replace('"amount": "100"', '"amount": 200.50')
        self.server.enqueue(body.encode('utf-8'))
        self.config._eip_pull_incremental()
        lines = self._lines()
        self.assertEqual(sorted(lines.mapped('po_item_id')),
                         ['1002', '699708678428688384'])
        self.assertEqual(
            lines.filtered(lambda rec: rec.po_item_id == '1002').amount,
            '200.50')

    # ------------------------------------------------------------------
    # incremental window
    # ------------------------------------------------------------------

    def test_20_first_sync_is_full(self):
        before = fields.Datetime.now()
        self.server.enqueue(eip_page([po_row('1001')], 1, 1000, 1, 1))
        self.config._eip_pull_incremental()
        request = self.server.requests[0]
        body = request['json']
        self.assertEqual(request['path'], '/api/supplier-send')
        self.assertEqual(request['headers']['operatetype'], 'QUERY')
        # no update-time condition at all, and not the retired dataSource
        self.assertNotIn('modifyStartTime', body)
        self.assertNotIn('modifyEndTime', body)
        self.assertNotIn('dataSource', body)
        self.assertEqual(body['purchaserHqCode'], 'SGCC')
        self.assertEqual(body['supplierCode'], 'SUP-1')
        self.assertEqual(body['supplierName'], 'Supplier One')
        self.assertEqual(body['pageNum'], 1)
        self.assertEqual(body['pageSize'], 1000)
        state = self._state()
        self.assertLessEqual(before, state.watermark)
        self.assertLessEqual(state.watermark, fields.Datetime.now())
        self.assertFalse(state.pending_end)
        self.assertEqual(state.calls_count, 1)

    def test_21_incremental_window_with_overlap(self):
        self._state().write({'watermark': self.WATERMARK})
        self.server.enqueue(eip_page([], 1, 1000, 0, 0))
        with patch.object(fields.Datetime, 'now', return_value=self.NOW):
            result = self.config._eip_pull_incremental()
        # watermark 11-23 10:00 Beijing, overlap 24h, run at 11-24 09:00
        body = self.server.requests[0]['json']
        self.assertEqual(body['modifyStartTime'], '2026-11-22 10:00:00')
        self.assertEqual(body['modifyEndTime'], '2026-11-24 09:00:00')
        self.assertEqual(result['reason'], 'done')
        self.assertEqual(self._state().watermark, self.NOW)

    def test_22_failed_page_keeps_watermark(self):
        self._state().write({'watermark': self.WATERMARK})
        self.server.enqueue(eip_page([po_row('1001')], 1, 1000, 3, 3))
        self.server.enqueue(system_error())
        result = self.config._eip_pull_incremental()
        self.assertEqual(result['reason'], 'error')
        self.assertIn('90003', result['detail'])
        # page 1 was stored, the watermark did not move, the breakpoint
        # sits on the failed page
        self.assertEqual(len(self._lines()), 1)
        state = self._state()
        self.assertEqual(state.watermark, self.WATERMARK)
        self.assertEqual(state.calls_count, 2)
        self.assertTrue(state.pending_end)
        self.assertEqual(state.pending_page, 2)
        self.assertEqual(state.last_run_reason, 'error')

    # ------------------------------------------------------------------
    # paging
    # ------------------------------------------------------------------

    def test_30_pages_fetched_to_the_end(self):
        def responder(request):
            page = request['json']['pageNum']
            start = (page - 1) * 1000
            rows = [
                po_row(str(1001 + start + index), item_no=str(index))
                for index in range(min(1000, 2500 - start))]
            return eip_page(rows, page, 1000, 3, 2500)
        self.server.set_responder(responder)
        result = self.config._eip_pull_incremental()
        self.assertEqual(self._pages_sent(), [1, 2, 3])
        self.assertEqual(result['rows'], 2500)
        self.assertEqual(len(self._lines()), 2500)

    def test_31_full_pages_do_not_trigger_an_extra_request(self):
        self.config.write({'pull_page_size': 10})
        self.server.set_responder(lambda request: eip_page(
            [po_row('L%d-%d' % (request['json']['pageNum'], index))
             for index in range(10)],
            request['json']['pageNum'], 10, 2, 20))
        result = self.config._eip_pull_incremental()
        self.assertEqual(self._pages_sent(), [1, 2])
        self.assertEqual(result['rows'], 20)

    def test_32_no_data(self):
        self.server.enqueue(eip_page([], 1, 1000, 0, 0))
        result = self.config._eip_pull_incremental()
        self.assertEqual(self.server.calls, 1)
        self.assertEqual((result['reason'], result['rows']), ('done', 0))
        self.assertTrue(self._state().watermark)

    def test_33_without_page_count_an_empty_page_ends_the_run(self):
        self.server.set_responder(lambda request: eip_envelope(
            data=[po_row('1001'), po_row('1002')]
            if request['json']['pageNum'] == 1 else []))
        result = self.config._eip_pull_incremental()
        self.assertEqual(self._pages_sent(), [1, 2])
        self.assertEqual(result['reason'], 'done')
        self.assertEqual(len(self._lines()), 2)

    # ------------------------------------------------------------------
    # daily limit: counted before the request, shared by every trigger
    # ------------------------------------------------------------------

    def _run_until_quota(self):
        """3 pages needed, 1 call left today."""
        self.config.write({'pull_page_size': 1})
        self._state().write(
            {'calls_date': self._today(), 'calls_count': 99})
        self.server.set_responder(lambda request: eip_page(
            [po_row('L%d' % request['json']['pageNum'])],
            request['json']['pageNum'], 1, 3, 3))
        return self.config._eip_pull_incremental()

    def test_40_quota_stops_the_run(self):
        result = self._run_until_quota()
        self.assertEqual(self.server.calls, 1)
        self.assertEqual(
            (result['reason'], result['pages'], result['next_page']),
            ('quota', 1, 2))
        state = self._state()
        self.assertEqual(state.calls_count, 100)
        self.assertFalse(state.watermark)
        self.assertTrue(state.pending_end)
        self.assertEqual(state.pending_page, 2)

    def test_41_manual_pull_reports_exhausted_quota(self):
        self._state().write({'calls_date': self._today(), 'calls_count': 100})
        wizard = self._wizard()
        wizard.action_pull()
        self.assertEqual(self.server.calls, 0)
        self.assertIn('100/100', wizard.result_summary)
        self.assertIn("Today's pull quota is used up", wizard.result_summary)

    def test_42_failed_run_keeps_sent_calls_counted(self):
        self.server.enqueue(eip_page([po_row('1001')], 1, 1000, 3, 3))
        self.server.enqueue(eip_page([po_row('1002')], 2, 1000, 3, 3))
        self.server.enqueue(system_error())
        result = self.config._eip_pull_incremental()
        self.assertEqual(result['reason'], 'error')
        # the 3 requests that really left are still counted
        self.assertEqual(self._state().calls_count, 3)

    def test_43_pulls_of_one_config_are_serialised(self):
        # while a request is in flight the per-config session lock is
        # held: from another database connection it cannot be taken;
        # once the run is over it is free again
        probe = {}
        db_name = self.env.cr.dbname
        config_id = self.config.id

        def try_lock(cursor):
            cursor.execute(
                'SELECT pg_try_advisory_lock(%s, %s)',
                (PULL_LOCK_NAMESPACE, config_id))
            return cursor.fetchone()[0]

        def responder(request):
            with db_connect(db_name).cursor() as cursor:
                locked = try_lock(cursor)
                probe['during'] = locked
                if locked:
                    cursor.execute(
                        'SELECT pg_advisory_unlock(%s, %s)',
                        (PULL_LOCK_NAMESPACE, config_id))
            return eip_page([po_row('1001')], 1, 1000, 1, 1)

        self.server.set_responder(responder)
        self.config._eip_pull_incremental()
        self.assertIs(probe['during'], False)
        with db_connect(db_name).cursor() as cursor:
            self.assertIs(try_lock(cursor), True)
            cursor.execute('SELECT pg_advisory_unlock(%s, %s)',
                           (PULL_LOCK_NAMESPACE, config_id))

    def test_44_counter_resets_on_a_new_day(self):
        self._state().write({
            'calls_date': self._today() - datetime.timedelta(days=1),
            'calls_count': 100,
        })
        self.server.enqueue(eip_page([], 1, 1000, 0, 0))
        self.config._eip_pull_incremental()
        state = self._state()
        self.assertEqual(state.calls_date, self._today())
        self.assertEqual(state.calls_count, 1)

    # ------------------------------------------------------------------
    # breakpoint resume
    # ------------------------------------------------------------------

    def test_50_breakpoint_resumes_with_the_same_window(self):
        self.config.write({'pull_daily_limit': 3})
        self._state().write({'watermark': self.WATERMARK})
        self.server.set_responder(lambda request: eip_page(
            [po_row('L%d' % request['json']['pageNum'])],
            request['json']['pageNum'], 1000, 5, 5))
        with patch.object(fields.Datetime, 'now', return_value=self.NOW):
            first = self.config._eip_pull_incremental()
        # day 1: the quota cuts the run after page 3
        self.assertEqual(self._pages_sent(), [1, 2, 3])
        self.assertEqual(first['reason'], 'quota')
        state = self._state()
        self.assertEqual(state.pending_page, 4)
        self.assertEqual(state.watermark, self.WATERMARK)
        frozen = tuple(self.server.requests[0]['json'][key]
                       for key in ('modifyStartTime', 'modifyEndTime'))

        # day 2: the counter starts again, the window and page go on
        self._state().write({
            'calls_date': self.BEIJING_NOW.date() - datetime.timedelta(days=1),
            'calls_count': 3,
        })
        next_day = self.NOW + datetime.timedelta(days=1)
        with patch.object(fields.Datetime, 'now', return_value=next_day):
            second = self.config._eip_pull_incremental()
        self.assertEqual(self._pages_sent(), [1, 2, 3, 4, 5])
        self.assertEqual(second['reason'], 'done')
        for request in self.server.requests:
            self.assertEqual(
                tuple(request['json'][key]
                      for key in ('modifyStartTime', 'modifyEndTime')),
                frozen)

    def test_51_completed_breakpoint_advances_watermark(self):
        # a window left unfinished by an earlier run: 5 pages, page 4 next
        self.server.set_responder(lambda request: eip_page(
            [po_row('L%d' % request['json']['pageNum'])],
            request['json']['pageNum'], 1000, 5, 5))
        self._state().write({
            'pending_start': self.WATERMARK,
            'pending_end': self.NOW,
            'pending_page': 4,
        })
        with patch.object(fields.Datetime, 'now', return_value=self.NOW):
            result = self.config._eip_pull_incremental()
        self.assertEqual(self._pages_sent(), [4, 5])
        self.assertEqual(result['reason'], 'done')
        state = self._state()
        # the watermark moves to the frozen window end, not to "now"
        self.assertEqual(state.watermark, self.NOW)
        self.assertFalse(state.pending_end)
        self.assertEqual(state.pending_page, 0)

    # ------------------------------------------------------------------
    # targeted pull
    # ------------------------------------------------------------------

    def test_60_targeted_pull_keeps_watermark(self):
        self._state().write({'watermark': self.WATERMARK})
        self.server.enqueue(eip_page([po_row('9001', po_no='PO9')],
                                     1, 1000, 1, 1))
        self._wizard(mode='targeted', po_no='PO9').action_pull()
        body = self.server.requests[0]['json']
        self.assertEqual(body['poNo'], 'PO9')
        self.assertNotIn('modifyStartTime', body)
        self.assertNotIn('modifyEndTime', body)
        self.assertEqual(self._lines().mapped('po_no'), ['PO9'])
        state = self._state()
        self.assertEqual(state.watermark, self.WATERMARK)
        self.assertFalse(state.pending_end)
        # a targeted pull needs at least one condition
        with self.assertRaisesRegex(UserError, 'at least one condition'):
            self._wizard(mode='targeted').action_pull()

    def test_61_targeted_pull_shares_the_quota(self):
        self._state().write({'calls_date': self._today(), 'calls_count': 100})
        wizard = self._wizard(mode='targeted', po_no='PO9')
        wizard.action_pull()
        self.assertEqual(self.server.calls, 0)
        self.assertIn('100/100', wizard.result_summary)

    # ------------------------------------------------------------------
    # scheduled pull
    # ------------------------------------------------------------------

    def test_70_cron_runs_incremental_pull(self):
        self.server.enqueue(eip_page([po_row('1001')], 1, 1000, 1, 1))
        self.env['sn.wsd.eip.pull.worker'].run_pull()
        self.assertEqual(self.server.calls, 1)
        self.assertEqual(len(self._lines()), 1)
        self.assertTrue(self._state().last_run_at)

    def test_71_cron_skips_unconfigured_company_and_ships_paused(self):
        self.config.active = False
        self.env['sn.wsd.eip.pull.worker'].run_pull()
        self.assertEqual(self.server.calls, 0)
        cron = self.env.ref('sn_wsd_eip.ir_cron_eip_pull_purchase_order')
        self.assertFalse(cron.active)
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.interval_type, 'hours')

    # ------------------------------------------------------------------
    # after a run the state and the logs tell the whole story
    # ------------------------------------------------------------------

    def test_80_quota_stop_is_visible_in_state_and_logs(self):
        self._run_until_quota()
        state = self._state()
        self.assertEqual(state.calls_count, self.config.pull_daily_limit)
        self.assertEqual(state.pending_page, 2)
        self.assertEqual(state.last_run_reason, 'quota')
        self.assertIn('next page is 2', state.last_run_detail)
        self.assertEqual(state.pull_log_count, 1)
        log = self.env['sn.wsd.eip.pull.log'].search([])
        self.assertEqual(log.result, 'success')
        self.assertEqual(log.page_num, 1)
        self.assertEqual(log.row_count, 1)
        self.assertEqual(json.loads(log.page_info)['pageCount'], 3)
        self.assertEqual(
            json.loads(log.request_body)['pageNum'], 1)

    # ------------------------------------------------------------------
    # who may trigger it
    # ------------------------------------------------------------------

    def test_90_plain_user_can_trigger_pull(self):
        # the engine maintains the state and the logs itself: users only
        # read those, whatever user starts the pull
        user = self.env['res.users'].create({
            'name': 'EIP Pull MRP User',
            'login': 'eip_pull_mrp_user',
            'email': 'eip_pull_mrp_user@example.com',
            'group_ids': [(4, self.env.ref('sn_wsd_eip.group_eip_user').id)],
        })
        self.server.enqueue(eip_page([po_row('1001')], 1, 1000, 1, 1))
        wizard = self.env['sn.wsd.eip.pull.wizard'].with_user(user).create(
            {'config_id': self.config.id})
        wizard.action_pull()
        self.assertEqual(self.server.calls, 1)
        self.assertEqual(len(self._lines()), 1)

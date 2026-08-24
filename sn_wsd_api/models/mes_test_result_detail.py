"""Structured test detail support for the scan-pass API."""

import json

from odoo import api, fields, models


class MesTestResultDetail(models.Model):
    _name = 'sn.wsd.mes.test.result.detail'
    _description = 'MES Test Result Detail Item'
    _order = 'sequence, id'
    _check_company_auto = True

    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result',
        string='Test Result',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='test_result_id.company_id',
        store=True,
        readonly=True,
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity',
        string='SN',
        related='test_result_id.serial_identity_id',
        store=True,
        readonly=True,
        index=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='test_result_id.production_id',
        store=True,
        readonly=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='test_result_id.mes_order_id',
        store=True,
        readonly=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='MES Route Operation',
        related='test_result_id.route_operation_id',
        store=True,
        readonly=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        related='test_result_id.workcenter_id',
        store=True,
        readonly=True,
    )
    test_time = fields.Datetime(
        string='Test Time',
        related='test_result_id.test_time',
        store=True,
        readonly=True,
    )
    parent_result = fields.Selection(
        [('ok', 'OK'), ('ng', 'NG'), ('hold', 'Hold')],
        string='Overall Result',
        related='test_result_id.result',
        store=True,
        readonly=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='test_result_id.product_id',
        store=True,
        readonly=True,
    )
    operator_code = fields.Char(
        string='Operator Code',
        related='test_result_id.operator_code',
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(string='Sequence', default=1, required=True)
    project_name = fields.Char(string='Project Name', required=True)
    lower_limit = fields.Char(string='Lower Limit')
    upper_limit = fields.Char(string='Upper Limit')
    actual_value = fields.Char(string='Actual Value')
    result = fields.Selection([
        ('ok', 'OK'),
        ('ng', 'NG'),
    ], string='Result', required=True)
    raw_line = fields.Char(string='Raw Line', help='Original raw data before parsing')

    @api.model
    def _normalize_detail_result(self, raw_result):
        result_value = str(raw_result or '').strip().upper()
        if result_value in ('NG', 'FAIL', 'F'):
            return 'ng'
        if result_value in ('OK', 'PASS', 'P'):
            return 'ok'
        return 'ok'

    @api.model
    def _detail_text(self, value):
        return '' if value is None else str(value).strip()

    @api.model
    def _parse_structured_test_detail(self, test_detail):
        items = []
        for sequence, detail in enumerate(test_detail, start=1):
            if not isinstance(detail, dict):
                continue
            raw_line = json.dumps(detail, ensure_ascii=False, separators=(',', ':'))
            items.append({
                'sequence': sequence,
                'project_name': self._detail_text(detail.get('item_name')),
                'lower_limit': self._detail_text(detail.get('low_limit')),
                'upper_limit': self._detail_text(detail.get('up_limit')),
                'actual_value': self._detail_text(detail.get('item_value')),
                'result': self._normalize_detail_result(detail.get('item_result')),
                'raw_line': raw_line,
            })
        return items

    @api.model
    def _parse_test_detail(self, test_detail: str | list) -> list:
        """
        Parse M_TEST_DETAIL into structured items.

        The preferred format is a JSON array of objects with item_name,
        low_limit, up_limit, item_value, and item_result fields. A JSON array
        encoded as text and the legacy dollar/pipe-delimited text remain
        readable for historical payloads.

        :param test_detail: Structured array, JSON array text, or legacy text
        :return: List of parsed item dicts
        """
        if not test_detail:
            return []

        if isinstance(test_detail, list):
            return self._parse_structured_test_detail(test_detail)

        if not isinstance(test_detail, str):
            return []

        stripped_detail = test_detail.strip()
        if stripped_detail.startswith('['):
            try:
                structured_detail = json.loads(stripped_detail)
            except ValueError:
                structured_detail = None
            if isinstance(structured_detail, list):
                return self._parse_structured_test_detail(structured_detail)

        items = []
        lines = stripped_detail.split('$')

        for seq, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue

            parts = line.split('|')
            if len(parts) < 5:
                continue

            project_name = parts[0].strip()
            lower_limit = parts[1].strip()
            upper_limit = parts[2].strip()
            actual_value = parts[3].strip()
            result = self._normalize_detail_result(parts[4])

            items.append({
                'sequence': seq,
                'project_name': project_name,
                'lower_limit': lower_limit,
                'upper_limit': upper_limit,
                'actual_value': actual_value,
                'result': result,
                'raw_line': line,
            })

        return items

    @api.model
    def create_from_test_result(self, test_result, test_detail: str | list):
        """
        Create detail records from M_TEST_DETAIL.

        :param test_result: sn.wsd.mes.test.result record
        :param test_detail: Structured array, JSON array text, or legacy text
        :return: Created detail records
        """
        if not test_detail:
            return self

        existing = self.search([('test_result_id', '=', test_result.id)])
        if existing:
            return existing

        parsed_items = self._parse_test_detail(test_detail)
        if not parsed_items:
            return self

        vals_list = [
            {
                'test_result_id': test_result.id,
                'sequence': item['sequence'],
                'project_name': item['project_name'],
                'lower_limit': item['lower_limit'],
                'upper_limit': item['upper_limit'],
                'actual_value': item['actual_value'],
                'result': item['result'],
                'raw_line': item['raw_line'],
            }
            for item in parsed_items
        ]

        return self.create(vals_list)

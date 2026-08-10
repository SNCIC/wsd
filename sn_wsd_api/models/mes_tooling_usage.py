"""
Extension for sn.wsd.mes.test.result to support tooling usage counting.

This module implements the F-027 requirement from the scan-pass API:
Tooling usage count should be incremented for each tooling SN passed in M_TOOLING field.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MesToolingUsageLog(models.Model):
    _name = 'sn.wsd.mes.tooling.usage.log'
    _description = 'MES Tooling Usage Log'
    _order = 'usage_time desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    manufacturing_batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch',
        string='Manufacturing Batch',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    tooling_id = fields.Many2one(
        'sn.tooling',
        string='Tooling',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
    )
    tooling_code = fields.Char(
        string='Tooling Code',
        related='tooling_id.name',
        store=True,
        readonly=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Product SN',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    serial_number = fields.Char(
        string='Serial Number',
        related='internal_serial_id.serial_no',
        store=True,
        readonly=True,
    )
    usage_count = fields.Integer(string='Usage Count', default=1, required=True)
    usage_time = fields.Datetime(
        string='Usage Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    operator_code = fields.Char(string='Operator Code', index=True)
    event_type = fields.Selection([
        ('scan_pass', 'Scan Pass'),
        ('feeder_use', 'Feeder Use'),
        ('consumable_use', 'Consumable Use'),
    ], string='Event Type', required=True, default='scan_pass')
    payload = fields.Json(string='Raw Payload')
    note = fields.Char(string='Note')

    @api.model
    def _parse_tooling_string(self, tooling_input: str) -> list:
        """
        Parse M_TOOLING string into tooling SN list.

        Format: Multiple tooling SNs separated by pipe (|)
        Example: TOOL001|TOOL002|TOOL003

        :param tooling_input: Raw tooling string
        :return: List of tooling SN strings
        """
        if not tooling_input:
            return []

        tooling_list = []
        parts = tooling_input.replace(',', '|').split('|')

        for part in parts:
            sn = part.strip()
            if sn:
                tooling_list.append(sn)

        return tooling_list

    @api.model
    def increment_tooling_usage(
        self,
        tooling_sns: list,
        company_id=None,
        production_id=None,
        manufacturing_batch_id=None,
        workorder_id=None,
        workcenter_id=None,
        serial_number=None,
        operator_code=None,
        event_type='scan_pass',
        payload=None,
    ):
        """
        Increment usage count for tooling SNs.

        F-027: Each tooling SN passed in M_TOOLING should have its
        cumulative usage count incremented by 1.

        :param tooling_sns: List of tooling SN strings
        :param company_id: Company ID
        :param production_id: Manufacturing order ID
        :param manufacturing_batch_id: Manufacturing batch ID
        :param workorder_id: Work order ID
        :param workcenter_id: Work center ID
        :param serial_number: Product SN
        :param operator_code: Operator code
        :param event_type: Event type
        :param payload: Raw payload for traceability
        :return: Created usage log records
        """
        if not tooling_sns:
            return self

        company = self.env.company
        if company_id:
            company = self.env['res.company'].browse(company_id)
            if not company.exists():
                return self

        internal_serial_id = False
        if serial_number:
            production = self.env['mrp.production'].browse(production_id).exists() if production_id else self.env['mrp.production']
            manufacturing_batch = self.env['sn.wsd.manufacturing.batch'].browse(manufacturing_batch_id).exists() if manufacturing_batch_id else production.x_manufacturing_batch_id
            serial = self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(
                serial_number,
                company=company,
                production=production,
                manufacturing_batch=manufacturing_batch,
                product=production.product_id,
            )
            if serial:
                internal_serial_id = serial.id

        records = self.env['sn.wsd.mes.tooling.usage.log']
        usage_time = fields.Datetime.now()

        for tooling_sn in tooling_sns:
            tooling = self.env['sn.tooling'].search([
                ('name', '=', tooling_sn),
                ('company_id', '=', company.id),
            ], limit=1)

            if not tooling:
                tooling = self.env['sn.tooling'].search([
                    ('name', '=', tooling_sn),
                ], limit=1)

            if not tooling:
                continue

            tooling.write({
                'total_usage_count': tooling.total_usage_count + 1,
                'current_usage_count': tooling.current_usage_count + 1,
            })

            log_vals = {
                'company_id': company.id,
                'tooling_id': tooling.id,
                'production_id': production_id,
                'manufacturing_batch_id': manufacturing_batch_id,
                'workorder_id': workorder_id,
                'workcenter_id': workcenter_id,
                'internal_serial_id': internal_serial_id,
                'usage_count': 1,
                'usage_time': usage_time,
                'operator_code': operator_code,
                'event_type': event_type,
                'payload': payload,
            }
            records |= self.create(log_vals)

        return records

    @api.model
    def process_tooling_from_payload(self, payload: dict, **kwargs):
        """
        Process M_TOOLING field from scan-pass payload.

        :param payload: Scan-pass payload dict
        :return: Created usage log records
        """
        tooling_input = payload.get('M_TOOLING') or payload.get('tooling')
        if not tooling_input:
            return self

        tooling_sns = self._parse_tooling_string(tooling_input)
        if not tooling_sns:
            return self

        return self.increment_tooling_usage(
            tooling_sns=tooling_sns,
            company_id=kwargs.get('company_id'),
            production_id=kwargs.get('production_id'),
            manufacturing_batch_id=kwargs.get('manufacturing_batch_id'),
            workorder_id=kwargs.get('workorder_id'),
            workcenter_id=kwargs.get('workcenter_id'),
            serial_number=kwargs.get('serial_number'),
            operator_code=kwargs.get('operator_code'),
            event_type='scan_pass',
            payload=payload,
        )

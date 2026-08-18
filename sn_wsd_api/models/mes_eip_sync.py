"""
EIP (Enterprise Integration Platform) detection data synchronization.

This module implements the E-2 requirement from the scan-pass API:
Detection data should be synchronized to EIP intermediate tables
based on product category and operation rules.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MesEipProductCategoryMapping(models.Model):
    _name = 'sn.wsd.mes.eip.category.mapping'
    _description = 'MES EIP Product Category Mapping'
    _order = 'category_code, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    product_category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        required=True,
        index=True,
    )
    category_code = fields.Char(
        string='Category Code',
        related='product_category_id.complete_name',
        store=True,
        readonly=True,
    )
    eip_category = fields.Char(
        string='EIP Category',
        required=True,
        index=True,
        help='Category code used in EIP system (first 7 characters of product code)',
    )
    active = fields.Boolean(default=True, index=True)
    note = fields.Text(string='Notes')

    _category_uniq = models.Constraint(
        'unique(company_id, product_category_id)',
        'Category mapping must be unique per company.',
    )
    _eip_category_uniq = models.Constraint(
        'unique(company_id, eip_category)',
        'EIP category must be unique per company.',
    )


class MesEipOperationMapping(models.Model):
    _name = 'sn.wsd.mes.eip.operation.mapping'
    _description = 'MES EIP Operation Mapping'
    _order = 'operation_name, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    operation_name = fields.Char(
        string='Operation Name',
        required=True,
        index=True,
        help='Work center name or operation name',
    )
    eip_operation_code = fields.Char(
        string='EIP Operation Code',
        required=True,
        index=True,
    )
    operation_type = fields.Selection([
        ('single_board_debug', 'Single Board Debug'),
        ('pressure_test', 'Pressure Test'),
        ('auto_function', 'Auto Function Test'),
    ], string='Operation Type', required=True, index=True)
    active = fields.Boolean(default=True, index=True)
    note = fields.Text(string='Notes')

    _operation_uniq = models.Constraint(
        'unique(company_id, operation_name, operation_type)',
        'Operation mapping must be unique per company, name, and type.',
    )


class MesEipSyncConfig(models.Model):
    _name = 'sn.wsd.mes.eip.sync.config'
    _description = 'MES EIP Sync Configuration'
    _order = 'key, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    key = fields.Char(string='Config Key', required=True, index=True)
    value = fields.Char(string='Config Value', required=True)
    description = fields.Char(string='Description')

    _config_uniq = models.Constraint(
        'unique(company_id, key)',
        'Config key must be unique per company.',
    )

    @api.model
    def is_eip_enabled(self, company_id=None):
        """Check if EIP synchronization is enabled for the company."""
        company = company_id or self.env.company.id
        config = self.search([
            ('company_id', '=', company),
            ('key', '=', 'EIP_ENABLED'),
        ], limit=1)
        if not config:
            return False
        return str(config.value).strip().upper() in ('1', 'TRUE', 'YES', 'ON')

    @api.model
    def get_eip_config(self, key, company_id=None, default=None):
        """Get EIP configuration value."""
        company = company_id or self.env.company.id
        config = self.search([
            ('company_id', '=', company),
            ('key', '=', key),
        ], limit=1)
        return config.value if config else default


class MesEipSyncRecord(models.Model):
    _name = 'sn.wsd.mes.eip.sync.record'
    _description = 'MES EIP Synchronization Record'
    _order = 'sync_time desc, id desc'
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
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='MES Route Operation',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Product SN',
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
    workcenter_code = fields.Char(string='Work Center Code', index=True)
    eip_category = fields.Char(string='EIP Category', index=True)
    operation_type = fields.Selection([
        ('single_board_debug', 'Single Board Debug'),
        ('pressure_test', 'Pressure Test'),
        ('auto_function', 'Auto Function Test'),
    ], string='EIP Operation Type', index=True)
    test_result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('hold', 'Hold'),
    ], string='Test Result', index=True)
    test_data = fields.Json(string='Test Data')
    sync_status = fields.Selection([
        ('pending', 'Pending'),
        ('synced', 'Synced'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ], string='Sync Status', required=True, default='pending', index=True)
    sync_time = fields.Datetime(
        string='Sync Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    external_id = fields.Char(string='External EIP ID', index=True)
    error_message = fields.Text(string='Error Message')
    retry_count = fields.Integer(string='Retry Count', default=0)
    payload = fields.Json(string='Original Payload')
    note = fields.Char(string='Note')

    @api.model
    def _get_product_category_code(self, product_id):
        """Get product category code (first 7 characters of default_code)."""
        if not product_id:
            return None
        product = self.env['product.product'].browse(product_id)
        if not product or not product.default_code:
            return None
        return product.default_code[:7]

    @api.model
    def _match_eip_category(self, category_code, company_id):
        """Match product category code to EIP category."""
        if not category_code or not company_id:
            return None

        mapping = self.env['sn.wsd.mes.eip.category.mapping'].search([
            ('company_id', '=', company_id),
            ('eip_category', '=', category_code),
            ('active', '=', True),
        ], limit=1)

        return mapping.eip_category if mapping else None

    @api.model
    def _match_eip_operation(self, workcenter_name, operation_type, company_id):
        """Match work center name to EIP operation."""
        if not workcenter_name or not operation_type or not company_id:
            return None

        mapping = self.env['sn.wsd.mes.eip.operation.mapping'].search([
            ('company_id', '=', company_id),
            ('operation_name', 'ilike', workcenter_name),
            ('operation_type', '=', operation_type),
            ('active', '=', True),
        ], limit=1)

        return mapping.eip_operation_code if mapping else None

    @api.model
    def _prepare_eip_sync_data(self, test_result_record, payload=None):
        """Prepare EIP synchronization data from test result."""
        result = {
            'serial_number': test_result_record.internal_serial_id.serial_no if test_result_record.internal_serial_id else None,
            'production_order': test_result_record.production_id.name if test_result_record.production_id else None,
            'product_code': test_result_record.product_id.default_code if test_result_record.product_id else None,
            'workcenter_code': test_result_record.workcenter_code or None,
            'test_type': test_result_record.test_type or None,
            'test_result': test_result_record.result or 'pass',
            'test_time': test_result_record.test_time.isoformat() if test_result_record.test_time else None,
            'operator': test_result_record.operator_code or None,
            'basic_error': test_result_record.basic_error,
            'phase_error': test_result_record.phase_error,
            'aging_temp': test_result_record.aging_temp_c,
            'tester_channel': test_result_record.tester_channel,
            'cycle_time': test_result_record.cycle_time_sec,
            'payload': payload or {},
        }
        return result

    @api.model
    def sync_to_eip(self, test_result_id, payload=None):
        """
        Synchronize test result to EIP intermediate table.

        E-2 F-005: Sync rules:
        - Work order must have EIP control enabled
        - Product category (first 7 chars) must be in EIP category mapping
        - Work center name must match EIP operation mapping

        :param test_result_id: sn.wsd.mes.test.result ID
        :param payload: Original payload dict
        :return: EIP sync record
        """
        test_result = self.env['sn.wsd.mes.test.result'].browse(test_result_id).exists()
        if not test_result:
            return self

        company_id = test_result.company_id.id
        if not self.env['sn.wsd.mes.eip.sync.config'].is_eip_enabled(company_id):
            return self

        production = test_result.production_id
        if production and not production.x_enable_eip_control:
            return self

        product = test_result.product_id
        if not product or not product.default_code:
            return self

        category_code = self._get_product_category_code(product.id)
        eip_category = self._match_eip_category(category_code, company_id)

        if not eip_category:
            return self.create({
                'company_id': company_id,
                'production_id': production.id if production else False,
                'mes_order_id': test_result.mes_order_id.id if test_result.mes_order_id else False,
                'route_operation_id': test_result.route_operation_id.id if test_result.route_operation_id else False,
                'internal_serial_id': test_result.internal_serial_id.id if test_result.internal_serial_id else False,
                'workcenter_id': test_result.workcenter_id.id if test_result.workcenter_id else False,
                'workcenter_code': test_result.workcenter_code,
                'test_result': test_result.result,
                'sync_status': 'skipped',
                'sync_time': fields.Datetime.now(),
                'payload': payload or {},
                'note': 'No EIP category mapping found',
            })

        workcenter = test_result.workcenter_id
        workcenter_name = workcenter.name if workcenter else ''
        test_type = test_result.test_type or ''

        operation_type = 'auto_function'
        if 'debug' in test_type.lower() or 'programming' in test_type.lower():
            operation_type = 'single_board_debug'
        elif 'pressure' in test_type.lower() or 'hi_pot' in test_type.lower():
            operation_type = 'pressure_test'

        eip_operation = self._match_eip_operation(workcenter_name, operation_type, company_id)

        if not eip_operation:
            return self.create({
                'company_id': company_id,
                'production_id': production.id if production else False,
                'mes_order_id': test_result.mes_order_id.id if test_result.mes_order_id else False,
                'route_operation_id': test_result.route_operation_id.id if test_result.route_operation_id else False,
                'internal_serial_id': test_result.internal_serial_id.id if test_result.internal_serial_id else False,
                'workcenter_id': test_result.workcenter_id.id if test_result.workcenter_id else False,
                'workcenter_code': test_result.workcenter_code,
                'eip_category': eip_category,
                'operation_type': operation_type,
                'test_result': test_result.result,
                'sync_status': 'skipped',
                'sync_time': fields.Datetime.now(),
                'payload': payload or {},
                'note': 'No EIP operation mapping found',
            })

        test_data = self._prepare_eip_sync_data(test_result, payload)

        sync_record = self.create({
            'company_id': company_id,
            'production_id': production.id if production else False,
            'mes_order_id': test_result.mes_order_id.id if test_result.mes_order_id else False,
            'route_operation_id': test_result.route_operation_id.id if test_result.route_operation_id else False,
            'internal_serial_id': test_result.internal_serial_id.id if test_result.internal_serial_id else False,
            'workcenter_id': test_result.workcenter_id.id if test_result.workcenter_id else False,
            'workcenter_code': test_result.workcenter_code,
            'eip_category': eip_category,
            'operation_type': operation_type,
            'test_result': test_result.result,
            'test_data': test_data,
            'sync_status': 'synced',
            'sync_time': fields.Datetime.now(),
            'payload': payload or {},
        })

        return sync_record

    @api.model
    def batch_sync_to_eip(self, test_result_ids, payload=None):
        """Batch synchronize test results to EIP."""
        records = self
        for test_result_id in test_result_ids:
            record = self.sync_to_eip(test_result_id, payload=payload)
            if record:
                records |= record
        return records

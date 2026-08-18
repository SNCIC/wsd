"""
Extension for scan-pass API to validate process parameter consistency.

This module implements F-013 to F-016 requirements from the scan-pass API:
When G0010=1, the following parameter codes must match the manufacturing order:
- F-013: Parameter plan (M_PARAMETER_PLAN)
- F-014: Program version (M_PROGRAM_NUM)
- F-015: Test plan (M_TEST_PLAN)
- F-016: Software number (M_SOFTWARE_NUM)
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MesProcessParameterConfig(models.Model):
    _name = 'sn.wsd.mes.process.parameter'
    _description = 'MES Process Parameter Configuration'
    _order = 'parameter_type, code, id'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    parameter_type = fields.Selection([
        ('parameter_plan', 'Parameter Plan'),
        ('program_version', 'Program Version'),
        ('test_plan', 'Test Plan'),
        ('software_number', 'Software Number'),
    ], string='Parameter Type', required=True, index=True)
    code = fields.Char(string='Code', required=True, index=True)
    name = fields.Char(string='Name')
    active = fields.Boolean(default=True, index=True)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        check_company=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        check_company=True,
        index=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        check_company=True,
        index=True,
    )
    operation_id = fields.Many2one(
        'mrp.routing.workcenter',
        string='Operation',
        check_company=True,
        index=True,
    )
    note = fields.Text(string='Notes')

    _code_type_company_uniq = models.Constraint(
        'unique(parameter_type, code, company_id)',
        'Parameter type and code must be unique per company.',
    )


class MesProcessParameterValidation(models.Model):
    _name = 'sn.wsd.mes.process.parameter.validation'
    _description = 'MES Process Parameter Validation Record'
    _order = 'validation_time desc, id desc'
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
        required=True,
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
    parameter_type = fields.Selection([
        ('parameter_plan', 'Parameter Plan'),
        ('program_version', 'Program Version'),
        ('test_plan', 'Test Plan'),
        ('software_number', 'Software Number'),
    ], string='Parameter Type', required=True, index=True)
    passed_code = fields.Char(string='Passed Code')
    expected_code = fields.Char(string='Expected Code')
    result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('skipped', 'Skipped'),
    ], string='Result', required=True, index=True)
    validation_time = fields.Datetime(
        string='Validation Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    operator_code = fields.Char(string='Operator Code')
    payload = fields.Json(string='Payload')
    note = fields.Char(string='Note')

    _validation_uniq = models.Constraint(
        'unique(production_id, internal_serial_id, parameter_type)',
        'Validation record must be unique per production, serial, and parameter type.',
    )

    @api.model
    def _normalize_company_record(self, company=False):
        if not company:
            return self.env.company
        if isinstance(company, int):
            company = self.env['res.company'].browse(company)
        return company if company.exists() else self.env.company

    @api.model
    def _is_validation_enabled(self, company=False):
        """Check if G0010 parameter validation is enabled."""
        company = self._normalize_company_record(company)
        config = self.env['sn.smt.config'].get_value(
            'G0010', default='0', company=company
        )
        return str(config).strip() == '1'

    @api.model
    def _validate_parameter_code(
        self,
        parameter_type: str,
        passed_code: str,
        production_id,
        company_id=None,
        product_id=None,
        workcenter_id=None,
        operation_id=None,
    ):
        """
        Validate a parameter code against configured values.

        :param parameter_type: Type of parameter (parameter_plan, program_version, etc.)
        :param passed_code: Code passed in the API call
        :param production_id: Manufacturing order ID
        :param company_id: Company ID
        :param product_id: Product ID
        :param workcenter_id: Work center ID
        :param operation_id: Operation ID
        :return: True if validation passes, ValidationError if fails
        """
        if not self._is_validation_enabled(company_id):
            return True

        if not passed_code:
            return True

        company = self.env.company
        if company_id:
            company = self.env['res.company'].browse(company_id)
            if not company.exists():
                company = self.env.company

        production = self.env['mrp.production'].browse(production_id).exists() if production_id else False

        domain = [
            ('company_id', '=', company.id),
            ('parameter_type', '=', parameter_type),
            ('active', '=', True),
        ]

        if production:
            if not product_id:
                product_id = production.product_id.id
            if not workcenter_id:
                workcenter_id = production.mapped('workorder_ids.workcenter_id.id')[:1] if production.workorder_ids else False

        candidates = self.env['sn.wsd.mes.process.parameter'].search(domain)

        expected_code = None
        for candidate in candidates:
            if product_id and candidate.product_id and candidate.product_id.id != product_id:
                continue
            if workcenter_id and candidate.workcenter_id and candidate.workcenter_id.id != workcenter_id:
                continue
            expected_code = candidate.code
            break

        if expected_code and expected_code != passed_code:
            type_label = dict(self._fields['parameter_type'].selection).get(parameter_type, parameter_type)
            raise ValidationError(_(
                '%s mismatch. Expected: %s, Passed: %s'
            ) % (type_label, expected_code, passed_code))

        return True

    @api.model
    def validate_all_parameters(self, payload: dict, production_id, **kwargs):
        """
        Validate all parameter codes from scan-pass payload.

        :param payload: Scan-pass payload dict
        :param production_id: Manufacturing order ID
        :param kwargs: Additional context (company_id, workorder_id, internal_serial_id, etc.)
        :return: List of validation results
        """
        if not self._is_validation_enabled(kwargs.get('company_id')):
            return []

        results = []
        parameter_types = [
            ('M_PARAMETER_PLAN', 'parameter_plan'),
            ('M_PROGRAM_NUM', 'program_version'),
            ('M_TEST_PLAN', 'test_plan'),
            ('M_SOFTWARE_NUM', 'software_number'),
        ]

        for payload_key, param_type in parameter_types:
            passed_code = payload.get(payload_key)
            if not passed_code:
                continue

            try:
                self._validate_parameter_code(
                    parameter_type=param_type,
                    passed_code=passed_code,
                    production_id=production_id,
                    **kwargs
                )
                results.append({
                    'parameter_type': param_type,
                    'passed_code': passed_code,
                    'result': 'pass',
                })
            except ValidationError as e:
                results.append({
                    'parameter_type': param_type,
                    'passed_code': passed_code,
                    'result': 'fail',
                    'error': str(e),
                })

        return results

    @api.model
    def create_validation_records(self, production_id, validation_results, **kwargs):
        """
        Create validation records from validation results.

        :param production_id: Manufacturing order ID
        :param validation_results: List of validation results
        :param kwargs: Additional context fields
        :return: Created validation records
        """
        if not validation_results:
            return self

        records = self
        validation_time = fields.Datetime.now()

        for result in validation_results:
            if result.get('result') == 'skipped':
                continue

            expected_code = False
            domain = [
                ('company_id', '=', kwargs.get('company_id') or self.env.company.id),
                ('parameter_type', '=', result.get('parameter_type')),
                ('active', '=', True),
            ]
            param = self.env['sn.wsd.mes.process.parameter'].search(domain, limit=1)
            if param:
                expected_code = param.code

            records |= self.create({
                'company_id': kwargs.get('company_id') or self.env.company.id,
                'production_id': production_id,
                'mes_order_id': kwargs.get('mes_order_id'),
                'workorder_id': kwargs.get('workorder_id'),
                'workcenter_id': kwargs.get('workcenter_id'),
                'internal_serial_id': kwargs.get('internal_serial_id'),
                'parameter_type': result.get('parameter_type'),
                'passed_code': result.get('passed_code'),
                'expected_code': expected_code,
                'result': result.get('result'),
                'validation_time': validation_time,
                'operator_code': kwargs.get('operator_code'),
                'payload': kwargs.get('payload'),
                'note': result.get('error'),
            })

        return records

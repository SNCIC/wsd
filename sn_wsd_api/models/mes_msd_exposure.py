"""
MSD (Moisture Sensitive Device) exposure time validation.

This module implements F-012 from the scan-pass API:
Validate PCB exposure time from unpacking to printing,
and maximum interval from solder paste printing to reflow.
"""

from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MesPcbExposureRecord(models.Model):
    _name = 'sn.wsd.mes.pcb.exposure.record'
    _description = 'PCB Exposure Time Record'
    _order = 'record_time desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='PCB Serial',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='internal_serial_id.product_id',
        store=True,
        readonly=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    record_type = fields.Selection([
        ('unpack', 'Unpack'),
        ('print', 'Print'),
        ('reflow', 'Reflow'),
    ], string='Record Type', required=True, index=True)
    exposure_minutes = fields.Integer(
        string='Exposure Minutes',
        help='Cumulative exposure time in minutes',
    )
    standard_minutes = fields.Integer(
        string='Standard Minutes',
        help='MSD level standard exposure time in minutes',
    )
    warning_minutes = fields.Integer(
        string='Warning Minutes',
        help='Warning threshold before standard',
    )
    record_time = fields.Datetime(
        string='Record Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    operator_code = fields.Char(string='Operator Code')
    state = fields.Selection([
        ('normal', 'Normal'),
        ('warning', 'Warning'),
        ('expired', 'Expired'),
    ], string='State', required=True, default='normal', index=True)
    note = fields.Char(string='Note')

    @api.model
    def _get_msd_level(self, product_id):
        """Get MSD level configuration for a product."""
        if not product_id:
            return None
        product = self.env['product.product'].browse(product_id)
        if not product:
            return None

        if hasattr(product, 'is_msd_material') and product.is_msd_material:
            return {
                'level': product.msl_level_id.name if product.msl_level_id else None,
                'standard_minutes': product.msl_level_id.standard_exposure_minutes if product.msl_level_id else None,
                'warning_minutes': int((product.msl_level_id.standard_exposure_minutes or 0) * 0.8) if product.msl_level_id else None,
            }
        return None

    @api.model
    def record_unpack(self, internal_serial_id, company_id=None, operator_code=None):
        """Record PCB unpacking time for exposure tracking."""
        company = company_id or self.env.company.id

        serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists()
        if not serial:
            raise ValidationError(_('PCB serial not found.'))

        product_id = serial.product_id.id if serial.product_id else None
        msd_config = self._get_msd_level(product_id)

        vals = {
            'company_id': company,
            'internal_serial_id': serial.id,
            'product_id': product_id,
            'record_type': 'unpack',
            'record_time': fields.Datetime.now(),
            'operator_code': operator_code,
            'state': 'normal',
        }

        if msd_config:
            vals['standard_minutes'] = msd_config.get('standard_minutes')
            vals['warning_minutes'] = msd_config.get('warning_minutes')

        return self.create(vals)

    @api.model
    def record_print(self, internal_serial_id, production_id=None, company_id=None, operator_code=None):
        """Record solder paste printing time and validate exposure."""
        company = company_id or self.env.company.id

        serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists()
        if not serial:
            raise ValidationError(_('PCB serial not found.'))

        unpack_record = self.search([
            ('internal_serial_id', '=', serial.id),
            ('record_type', '=', 'unpack'),
            ('company_id', '=', company),
        ], order='record_time desc', limit=1)

        if not unpack_record:
            raise ValidationError(_('PCB has no unpack record. Please unpack first.'))

        exposure_minutes = self._calculate_exposure_minutes(unpack_record.record_time)
        product_id = serial.product_id.id if serial.product_id else None
        msd_config = self._get_msd_level(product_id)

        state = 'normal'
        note = None
        if msd_config:
            standard = msd_config.get('standard_minutes', 0)
            warning = msd_config.get('warning_minutes', 0)
            if exposure_minutes > standard:
                state = 'expired'
                note = 'PCB exposure time exceeded standard'
            elif exposure_minutes > warning:
                state = 'warning'
                note = 'PCB exposure time approaching standard'

        vals = {
            'company_id': company,
            'internal_serial_id': serial.id,
            'product_id': product_id,
            'production_id': production_id,
            'record_type': 'print',
            'exposure_minutes': exposure_minutes,
            'standard_minutes': msd_config.get('standard_minutes') if msd_config else None,
            'warning_minutes': msd_config.get('warning_minutes') if msd_config else None,
            'record_time': fields.Datetime.now(),
            'operator_code': operator_code,
            'state': state,
            'note': note,
        }

        record = self.create(vals)

        if state == 'expired':
            self.create_warning_record(serial, company, 'PCB exposure time exceeded')

        return record

    @api.model
    def record_reflow(self, internal_serial_id, company_id=None, operator_code=None):
        """Record reflow completion."""
        company = company_id or self.env.company.id

        serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists()
        if not serial:
            raise ValidationError(_('PCB serial not found.'))

        print_record = self.search([
            ('internal_serial_id', '=', serial.id),
            ('record_type', '=', 'print'),
            ('company_id', '=', company),
        ], order='record_time desc', limit=1)

        if not print_record:
            raise ValidationError(_('PCB has no print record. Please print first.'))

        exposure_minutes = self._calculate_exposure_minutes(print_record.record_time)
        product_id = serial.product_id.id if serial.product_id else None

        vals = {
            'company_id': company,
            'internal_serial_id': serial.id,
            'product_id': product_id,
            'record_type': 'reflow',
            'exposure_minutes': exposure_minutes,
            'record_time': fields.Datetime.now(),
            'operator_code': operator_code,
            'state': 'normal',
        }

        return self.create(vals)

    @api.model
    def _calculate_exposure_minutes(self, start_time):
        """Calculate exposure minutes from start time to now."""
        if not start_time:
            return 0
        delta = fields.Datetime.now() - start_time
        return int(delta.total_seconds() / 60)

    @api.model
    def _create_warning_record(self, serial, company_id, message):
        """Create product warning record."""
        self.env['sn.wsd.mes.product.warning'].create({
            'company_id': company_id,
            'internal_serial_id': serial.id,
            'product_id': serial.product_id.id if serial.product_id else None,
            'warning_type': 'msd_exposure',
            'warning_level': 'warning',
            'message': message,
            'warning_time': fields.Datetime.now(),
        })

    @api.model
    def validate_print_interval(self, internal_serial_id, max_interval_minutes=480):
        """
        Validate print-to-reflow interval.

        Default max interval is 480 minutes (8 hours) as per IPC standard.

        :param internal_serial_id: PCB serial ID
        :param max_interval_minutes: Maximum allowed interval
        :return: True if valid, raises ValidationError if expired
        """
        serial = self.env['sn.wsd.internal.serial'].browse(internal_serial_id).exists()
        if not serial:
            return True

        print_record = self.search([
            ('internal_serial_id', '=', serial.id),
            ('record_type', '=', 'print'),
        ], order='record_time desc', limit=1)

        if not print_record:
            return True

        interval_minutes = self._calculate_exposure_minutes(print_record.record_time)

        if interval_minutes > max_interval_minutes:
            raise ValidationError(_(
                'Print to reflow interval (%d minutes) exceeded maximum allowed (%d minutes).'
            ) % (interval_minutes, max_interval_minutes))

        return True


class MesProductWarning(models.Model):
    _name = 'sn.wsd.mes.product.warning'
    _description = 'Product Warning Record'
    _order = 'warning_time desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Serial/Lot',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    warning_type = fields.Selection([
        ('msd_exposure', 'MSD Exposure'),
        ('defect_count', 'Defect Count'),
        ('quality', 'Quality Issue'),
    ], string='Warning Type', required=True, index=True)
    warning_level = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ], string='Warning Level', required=True, default='warning', index=True)
    message = fields.Char(string='Warning Message', required=True)
    warning_time = fields.Datetime(
        string='Warning Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    acknowledged = fields.Boolean(string='Acknowledged', default=False)
    acknowledged_by = fields.Many2one('res.users', string='Acknowledged By')
    acknowledged_time = fields.Datetime(string='Acknowledged Time')
    note = fields.Char(string='Note')

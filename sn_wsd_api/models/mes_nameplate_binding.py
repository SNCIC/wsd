"""
Extension for sn.wsd.mes.test.result to support nameplate binding.

This module implements the F-024, F-025, F-026 requirements from the scan-pass API:
- F-024: Nameplate binding (multiple nameplates per product SN, one product SN per nameplate)
- F-025: Nameplate binding audit trail
- F-026: Clear old nameplate packaging data when a nameplate is transferred
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MesNameplateBinding(models.Model):
    _name = 'sn.wsd.mes.nameplate.binding'
    _description = 'MES Nameplate Binding Record'
    _order = 'binding_time desc, id desc'
    _check_company_auto = True

    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Product SN',
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
    nameplate_code = fields.Char(string='Nameplate Code', required=True, index=True)
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        ondelete='set null',
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
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    workcenter_code = fields.Char(string='Work Center Code', index=True)
    operator_code = fields.Char(string='Operator Code', index=True)
    binding_time = fields.Datetime(
        string='Binding Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    binding_mode = fields.Selection([
        ('strict', 'Strict'),
        ('override', 'Override'),
    ], string='Binding Mode', required=True)
    previous_nameplate_id = fields.Many2one(
        'sn.wsd.mes.nameplate.binding',
        string='Previous Binding',
        ondelete='set null',
        index=True,
    )
    note = fields.Char(string='Note')

    def init(self):
        self.env.cr.execute("""
            ALTER TABLE sn_wsd_mes_nameplate_binding
            DROP CONSTRAINT IF EXISTS sn_wsd_mes_nameplate_binding_binding_uniq
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS sn_wsd_mes_nameplate_binding_active_nameplate_uniq
            ON sn_wsd_mes_nameplate_binding (company_id, nameplate_code)
            WHERE active
        """)

    @api.model
    def _get_binding_mode(self, company=False):
        """Get binding mode from configuration. Default is strict mode (1)."""
        company = company or self.env.company
        config = self.env['sn.smt.config'].get_value(
            'MESSC010', default='1', company=company
        )
        return 'strict' if str(config).strip() == '1' else 'override'

    @api.model
    def bind_nameplate(
        self,
        serial_number: str,
        nameplate_code: str,
        company_id=None,
        production_id=None,
        workcenter_id=None,
        operator_code=None,
        note=None,
    ):
        """
        Bind a product SN to a nameplate code.

        Implements F-024 nameplate binding with strict/override modes.
        A product SN may have multiple active nameplates; each nameplate may
        belong to only one active product SN in a company.

        :param serial_number: Product SN
        :param nameplate_code: Nameplate code to bind
        :param company_id: Company ID
        :param production_id: Manufacturing order ID
        :param workcenter_id: Work center ID
        :param operator_code: Operator code
        :param note: Optional note
        :return: Binding record
        :raises ValidationError: If strict mode conflict detected
        """
        company = self.env['res.company'].browse(company_id).exists() if company_id else self.env.company
        production = self.env['mrp.production'].browse(production_id).exists() if production_id else self.env['mrp.production']
        serial = self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(
            serial_number,
            company=company,
            production=production,
            mes_order=production.x_mes_order_ids[:1],
            product=production.product_id,
        )
        if not serial:
            raise ValidationError(_('Product SN %s not found.') % serial_number)

        binding_mode = self._get_binding_mode(company)

        current_same_binding = self.search([
            ('internal_serial_id', '=', serial.id),
            ('nameplate_code', '=', nameplate_code),
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], order='binding_time desc', limit=1)
        if current_same_binding:
            if serial.x_nameplate_code != nameplate_code:
                serial.x_nameplate_code = nameplate_code
            return current_same_binding

        existing_for_nameplate = self.search([
            ('internal_serial_id', '!=', serial.id),
            ('nameplate_code', '=', nameplate_code),
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], order='binding_time desc', limit=1)

        if binding_mode == 'strict':
            if existing_for_nameplate:
                existing_serial = existing_for_nameplate.internal_serial_id.serial_no
                raise ValidationError(_(
                    'Nameplate code %s is already bound to product SN %s. '
                    'Please unbind the existing binding first.'
                ) % (nameplate_code, existing_serial))

        if binding_mode == 'override' and existing_for_nameplate:
            if existing_for_nameplate:
                existing_for_nameplate.write({'active': False})

        binding_vals = {
            'company_id': company.id,
            'internal_serial_id': serial.id,
            'nameplate_code': nameplate_code,
            'production_id': production_id,
            'operator_code': operator_code,
            'binding_mode': binding_mode,
            'binding_time': fields.Datetime.now(),
            'note': note,
        }
        if workcenter_id:
            binding_vals['workcenter_id'] = workcenter_id
            workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
            if workcenter:
                binding_vals['workcenter_code'] = workcenter.code

        if binding_mode == 'override' and existing_for_nameplate:
            binding_vals['previous_nameplate_id'] = existing_for_nameplate.id

        binding = self.create(binding_vals)

        if binding_mode == 'override' and existing_for_nameplate:
            self._clear_nameplate_packaging_data(nameplate_code, company.id)
            old_serials = existing_for_nameplate.mapped('internal_serial_id')
            old_serials.filtered(lambda item: item.x_nameplate_code == nameplate_code).write({
                'x_nameplate_code': False,
            })

        serial.x_nameplate_code = nameplate_code

        return binding

    @api.constrains('internal_serial_id', 'nameplate_code', 'company_id', 'active')
    def _check_single_active_nameplate_binding(self):
        for record in self.filtered('active'):
            same_nameplate = self.search([
                ('id', '!=', record.id),
                ('nameplate_code', '=', record.nameplate_code),
                ('company_id', '=', record.company_id.id),
                ('active', '=', True),
            ], limit=1)
            if same_nameplate:
                raise ValidationError(_(
                    'Nameplate code %s already has an active product binding.'
                ) % record.nameplate_code)

    @api.model
    def _clear_nameplate_packaging_data(self, nameplate_code, company_id):
        """F-026: Clear old packaging data when rebinding nameplate in override mode."""
        packaging_records = self.env['sn.wsd.mes.packaging.record'].search([
            ('nameplate_code', '=', nameplate_code),
            ('company_id', '=', company_id),
        ])
        if packaging_records:
            packaging_records.write({'active': False})

    @api.model
    def _clear_serial_packaging_data(self, serial_lots):
        """Clear business packaging data for serials affected by a nameplate override."""
        archives = serial_lots
        if not archives:
            return
        archives.write({
            'carton_no': False,
            'pallet_no': False,
            'pack_date': False,
            'state': 'sealed',
        })
        pack_records = self.env['sn.wsd.meter.pack.record'].with_context(active_test=False).search([
            ('serial_id', 'in', archives.ids),
        ])
        if pack_records:
            pack_records.write({'active': False})

    @api.model
    def get_nameplate_for_serial(self, serial_number):
        """Get the current nameplate binding for a product SN."""
        serial = self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(serial_number)
        if not serial:
            return False

        binding = self.search([
            ('internal_serial_id', '=', serial.id),
            ('active', '=', True),
        ], order='binding_time desc', limit=1)
        return binding

    @api.model
    def get_serial_for_nameplate(self, nameplate_code, company_id=None):
        """Get the product SN currently bound to a nameplate code."""
        company = company_id or self.env.company.id
        binding = self.search([
            ('nameplate_code', '=', nameplate_code),
            ('company_id', '=', company),
            ('active', '=', True),
        ], order='binding_time desc', limit=1)
        return binding.internal_serial_id.serial_no if binding else False


class MesPackagingRecord(models.Model):
    _name = 'sn.wsd.mes.packaging.record'
    _description = 'MES Packaging Record'
    _order = 'packaging_time desc, id desc'
    _check_company_auto = True

    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Product SN',
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
        ondelete='set null',
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
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    workcenter_code = fields.Char(string='Work Center Code', index=True)
    nameplate_code = fields.Char(string='Nameplate Code', index=True)
    box_sn = fields.Char(string='Box SN', index=True)
    pallet_sn = fields.Char(string='Pallet SN', index=True)
    quantity = fields.Integer(string='Quantity', default=1)
    project_code = fields.Char(string='Project Code', index=True)
    packaging_time = fields.Datetime(
        string='Packaging Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    operator_code = fields.Char(string='Operator Code', index=True)
    operator_id = fields.Many2one('res.users', string='Operator', index=True)
    crc_value = fields.Char(string='CRC Value')
    payload = fields.Json(string='Raw Payload')

    def init(self):
        self.env.cr.execute("""
            ALTER TABLE sn_wsd_mes_packaging_record
            DROP CONSTRAINT IF EXISTS sn_wsd_mes_packaging_record_serial_uniq
        """)

    @api.model
    def _check_can_package(self, serial_number, company_id=None, production_id=None):
        """
        Check if a product SN can be packaged.

        F-030: NG test results should block packaging.
        F-031: SN already in packaging record should be blocked.
        """
        company = company_id or self.env.company.id
        production = self.env['mrp.production'].browse(production_id).exists() if production_id else self.env['mrp.production']
        serial = self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(
            serial_number,
            company=self.env['res.company'].browse(company),
            production=production,
            mes_order=production.x_mes_order_ids[:1],
            product=production.product_id,
        )
        if not serial:
            raise ValidationError(_('Product SN %s not found.') % serial_number)

        serial.check_packaging_readiness()

        existing = self.search([
            ('internal_serial_id', '=', serial.id),
            ('active', '=', True),
        ], limit=1)
        if existing:
            raise ValidationError(_(
                'Product SN %s already has an active packaging record.'
            ) % serial_number)

        return True

    @api.constrains('internal_serial_id', 'active', 'company_id')
    def _check_single_active_packaging(self):
        for record in self.filtered('active'):
            duplicate = self.search([
                ('id', '!=', record.id),
                ('internal_serial_id', '=', record.internal_serial_id.id),
                ('company_id', '=', record.company_id.id),
                ('active', '=', True),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Product SN %s already has an active packaging record.'
                ) % record.internal_serial_id.serial_no)

    @api.model
    def create_packaging(
        self,
        serial_number,
        company_id=None,
        production_id=None,
        workorder_id=None,
        workcenter_id=None,
        nameplate_code=None,
        box_sn=None,
        pallet_sn=None,
        operator_code=None,
        project_code=None,
        quantity=1,
        crc_value=None,
        payload=None,
    ):
        """
        Create a packaging record for a product SN.

        F-032: Generate packaging record.
        """
        company = self.env['res.company'].browse(company_id).exists() if company_id else self.env.company
        self._check_can_package(serial_number, company.id, production_id=production_id)

        production = self.env['mrp.production'].browse(production_id).exists() if production_id else self.env['mrp.production']
        serial = self.env['sn.wsd.internal.serial'].find_for_manufacturing_context(
            serial_number,
            company=company,
            production=production,
            mes_order=production.x_mes_order_ids[:1],
            product=production.product_id,
        )

        operator = self.env['res.users']
        if operator_code:
            operator = self.env['res.users'].search([
                ('login', '=', operator_code),
            ], limit=1)

        vals = {
            'company_id': company.id,
            'internal_serial_id': serial.id,
            'production_id': production_id,
            'workorder_id': workorder_id,
            'workcenter_id': workcenter_id,
            'nameplate_code': nameplate_code,
            'box_sn': box_sn,
            'pallet_sn': pallet_sn,
            'operator_code': operator_code,
            'operator_id': operator.id if operator else self.env.user.id,
            'project_code': project_code,
            'quantity': quantity,
            'crc_value': crc_value,
            'packaging_time': fields.Datetime.now(),
            'payload': payload,
        }
        if workcenter_id:
            workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
            if workcenter:
                vals['workcenter_code'] = workcenter.code

        record = self.create(vals)
        record._sync_meter_pack_record()
        return record

    def _sync_meter_pack_record(self):
        """Mirror MES packaging into the meter business packaging record when applicable."""
        pack_model = self.env['sn.wsd.meter.pack.record']
        workorder_model = self.env['mrp.workorder']
        for record in self:
            serial = record.internal_serial_id
            production = record.production_id
            workorder = record.workorder_id
            if not workorder and production and record.workcenter_id:
                workorder = workorder_model.search([
                    ('production_id', '=', production.id),
                    ('workcenter_id', '=', record.workcenter_id.id),
                ], limit=1)
            archive = serial
            if not archive:
                continue
            existing = pack_model.with_context(active_test=False).search([
                ('serial_id', '=', archive.id),
                ('production_id', '=', production.id),
            ], order='active desc, pack_time desc, id desc', limit=1)
            carton_package = self.env['stock.package']
            if record.box_sn:
                carton_package = self.env['stock.package'].get_or_create_wsd_package(
                    record.box_sn,
                    'carton',
                    record.company_id,
                    x_wsd_production_id=production,
                    x_wsd_operator_code=record.operator_code,
                )
            values = {
                'active': True,
                'serial_id': archive.id,
                'production_id': production.id if production else False,
                'pack_workorder_id': workorder.id if workorder else False,
                'carton_no': record.box_sn,
                'pallet_no': record.pallet_sn,
                'carton_package_id': carton_package.id,
                'pallet_package_id': carton_package.parent_package_id.id if carton_package else False,
                'pack_time': record.packaging_time,
                'operator_code': record.operator_code,
                'scan_check_result': 'pass',
                'note': record.nameplate_code,
            }
            if existing:
                existing.write(values)
                pack_record = existing
            else:
                pack_record = pack_model.create(values)
            pack_record.action_apply_to_serial()
            if carton_package:
                archive.write({
                    'carton_no': carton_package.name,
                    'pallet_no': carton_package.parent_package_id.name or record.pallet_sn,
                })
                self._assign_serial_to_carton(archive, production, carton_package)

    @api.model
    def _assign_serial_to_carton(self, serial, production, carton_package):
        lot = serial.lot_id
        if not lot and production:
            lot = production._get_or_create_stage_lot(serial.serial_no, identity=serial.serial_identity_id)
            serial.lot_id = lot
        if not lot:
            return
        move_lines = production.move_finished_ids.move_line_ids.filtered(
            lambda line: line.lot_id == lot and line.state not in ('done', 'cancel')
        ) if production else self.env['stock.move.line']
        if move_lines:
            move_lines.write({'result_package_id': carton_package.id})
        quants = self.env['stock.quant'].search([
            ('lot_id', '=', lot.id),
            ('product_id', '=', serial.product_id.id),
            ('quantity', '>', 0),
            ('location_id.usage', 'in', ['internal', 'transit']),
        ])
        conflicting = quants.filtered(lambda quant: quant.package_id and quant.package_id != carton_package)
        if conflicting:
            raise ValidationError(_(
                'Serial number %(serial)s is already stored in package %(package)s.'
            ) % {'serial': serial.serial_no, 'package': conflicting.package_id[:1].display_name})
        quants.filtered(lambda quant: not quant.package_id).write({'package_id': carton_package.id})

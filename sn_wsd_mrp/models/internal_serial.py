from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class InternalSerial(models.Model):
    _name = 'sn.wsd.internal.serial'
    _description = 'Internal Serial'
    _order = 'production_date desc, id desc'

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        # Scan-friendly: match by the physical SN as well as the record name.
        if name:
            domain = list(domain or []) + [
                '|', ('serial_no', operator, name), ('name', operator, name)]
            return super().name_search('', domain=domain, operator='ilike', limit=limit)
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    name = fields.Char(
        string='Serial Record',
        required=True,
        copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('sn.wsd.internal.serial') or 'New',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    serial_no = fields.Char(required=True, index=True)
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity',
        string='Physical Serial Identity',
        index=True,
        ondelete='restrict',
        check_company=True,
        copy=False,
    )
    serial_type = fields.Selection(
        [
            ('component', 'Component'),
            ('semifinished', 'Semi-finished'),
            ('finished', 'Finished Product'),
            ('package', 'Package'),
        ],
        string='Serial Type',
        default='finished',
        required=True,
        index=True,
    )
    x_panel_no = fields.Char(string='Panel No', index=True)
    barcode = fields.Char(index=True)
    qr_code = fields.Char()
    product_id = fields.Many2one('product.product', required=True, index=True, check_company=True)
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id', store=True)
    production_id = fields.Many2one('mrp.production', index=True, check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', index=True, check_company=True,
        ondelete='set null',
    )
    current_production_id = fields.Many2one(
        'mrp.production', string='Current Manufacturing Order', index=True, check_company=True,
    )
    current_route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Current MES Route Operation',
        index=True,
        check_company=True,
    )
    current_operation_id = fields.Many2one('mrp.routing.workcenter', index=True, check_company=True)
    current_workcenter_id = fields.Many2one('mrp.workcenter', index=True, check_company=True)
    parent_id = fields.Many2one('sn.wsd.internal.serial', string='Parent Serial', index=True, check_company=True)
    child_ids = fields.One2many('sn.wsd.internal.serial', 'parent_id', string='Child Serials')
    source_lot_id = fields.Many2one(
        'stock.lot', string='Source Lot/Serial', index=True, check_company=True, copy=False,
    )
    lot_id = fields.Many2one(
        'stock.lot', string='Product Lot/Serial', index=True, check_company=True, copy=False,
    )
    entry_route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Entry MES Route Operation',
        index=True,
        check_company=True,
        copy=False,
    )
    entry_time = fields.Datetime(copy=False, index=True)
    replaces_serial_id = fields.Many2one(
        'sn.wsd.internal.serial', string='Replaces Scrapped Serial', index=True, check_company=True, copy=False,
    )
    replacement_serial_ids = fields.One2many(
        'sn.wsd.internal.serial', 'replaces_serial_id', string='Replacement Serials', readonly=True,
    )
    current_aging_batch_id = fields.Many2one('sn.wsd.meter.aging.batch', index=True, check_company=True)
    main_pcb_sn = fields.Char(index=True)
    comm_module_sn = fields.Char(index=True)
    display_module_sn = fields.Char(index=True)
    firmware_version = fields.Char()
    parameter_version = fields.Char()
    protocol_version = fields.Char()
    hardware_version = fields.Char()
    customer_batch_no = fields.Char(index=True)
    seal_no = fields.Char(index=True)
    carton_no = fields.Char(index=True)
    pallet_no = fields.Char(index=True)
    production_date = fields.Datetime(default=fields.Datetime.now, index=True)
    verification_date = fields.Datetime(index=True)
    pack_date = fields.Datetime(index=True)
    final_result = fields.Selection(
        [('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold'), ('scrap', 'Scrap')],
        index=True,
    )
    final_verification_result = fields.Selection(
        [('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')],
    )
    communication_result = fields.Selection(
        [('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')],
    )
    hipot_result = fields.Selection(
        [('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')],
    )
    aging_result = fields.Selection(
        [('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')],
    )
    note = fields.Text()

    _serial_no_production_uniq = models.Constraint(
        'unique(company_id, serial_no, production_id)',
        'A serial number can only have one production stage per manufacturing order.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        production_model = self.env['mrp.production']
        identity_model = self.env['sn.wsd.serial.identity']
        for values in vals_list:
            identity_origin_type = values.pop('identity_origin_type', False) or 'external'
            values['serial_no'] = (values.get('serial_no') or '').strip()
            if not values['serial_no']:
                raise ValidationError(_('Serial number is required.'))
            production = production_model.browse(values.get('current_production_id') or values.get('production_id')).exists()
            company = production.company_id or self.env['res.company'].browse(values.get('company_id')).exists() or self.env.company
            if not values.get('serial_identity_id'):
                identity = identity_model.get_or_create(
                    values['serial_no'],
                    company,
                    origin_type=identity_origin_type,
                    origin_production_id=production,
                    origin_lot_id=self.env['stock.lot'].browse(values.get('source_lot_id')).exists(),
                )
                values['serial_identity_id'] = identity.id
            if production:
                if not values.get('production_id'):
                    values['production_id'] = production.id
                if not values.get('current_production_id'):
                    values['current_production_id'] = production.id
                if not values.get('mes_order_id'):
                    mes_orders = production.x_mes_order_ids.filtered(
                        lambda order: order.state != 'cancelled'
                    )
                    if len(mes_orders) == 1:
                        values['mes_order_id'] = mes_orders.id
        return super().create(vals_list)

    @api.constrains('serial_identity_id', 'serial_no', 'company_id')
    def _check_identity_scope(self):
        for serial in self:
            if not serial.serial_identity_id:
                continue
            if serial.serial_identity_id.company_id != serial.company_id:
                raise ValidationError(_('The physical serial identity must belong to the same company.'))
            if serial.serial_identity_id.name != serial.serial_no:
                raise ValidationError(_('The production stage SN must match the physical serial identity.'))

    def action_scrap(self, reason=False):
        """Mark this serial as scrapped (final state)."""
        for serial in self:
            serial.final_result = 'scrap'
        return True

    @api.constrains('mes_order_id', 'production_id', 'current_production_id', 'company_id', 'product_id')
    def _check_manufacturing_scope(self):
        for serial in self:
            mes_order = serial.mes_order_id
            if mes_order and mes_order.company_id != serial.company_id:
                raise ValidationError(_('The MES order must belong to the same company as the internal serial.'))
            if mes_order and mes_order.product_id != serial.product_id:
                raise ValidationError(_('The MES order product must match the internal serial product.'))
            for production in serial.production_id | serial.current_production_id:
                if production and production.company_id != serial.company_id:
                    raise ValidationError(_('The manufacturing order must belong to the same company as the internal serial.'))
                if mes_order and production != mes_order.production_id:
                    raise ValidationError(_('The manufacturing order must match the internal serial MES order.'))

    @api.model
    def _resolve_context_record(self, model_name, value=False):
        if not value:
            return self.env[model_name]
        if hasattr(value, 'ids'):
            return value.exists()
        return self.env[model_name].browse(int(value)).exists()

    @api.model
    def find_for_manufacturing_context(
        self,
        serial_no,
        company=False,
        production=False,
        mes_order=False,
        product=False,
        active=None,
    ):
        serial_no = (serial_no or '').strip()
        if not serial_no:
            return self.env['sn.wsd.internal.serial']

        production = self._resolve_context_record('mrp.production', production)
        mes_order = self._resolve_context_record('sn.wsd.mes.order', mes_order)
        product = self._resolve_context_record('product.product', product)
        company = self._resolve_context_record('res.company', company)

        if production and not mes_order:
            mes_orders = production.x_mes_order_ids.filtered(
                lambda order: order.state != 'cancelled'
            )
            if len(mes_orders) == 1:
                mes_order = mes_orders
        if production and not product:
            product = production.product_id
        if production and not company:
            company = production.company_id
        if mes_order and not product:
            product = mes_order.product_id
        if mes_order and not company:
            company = mes_order.company_id

        base_domain = [('serial_no', '=', serial_no)]
        if company:
            base_domain.append(('company_id', '=', company.id))
        else:
            base_domain.append(('company_id', 'in', self.env.companies.ids))
        if product:
            base_domain.append(('product_id', '=', product.id))
        if active is not None:
            base_domain.append(('active', '=', bool(active)))

        if production:
            serial = self.with_context(active_test=False).search(
                base_domain + [('production_id', '=', production.id)],
                order='active desc, production_date desc, id desc',
                limit=1,
            )
            if serial:
                return serial

        if mes_order:
            serials = self.with_context(active_test=False).search(
                base_domain + [('mes_order_id', '=', mes_order.id)],
                order='active desc, production_date desc, id desc',
            )
            if production:
                current = serials.filtered(lambda serial: serial.current_production_id == production)
                if current:
                    return current[:1]
            if serials:
                return serials[:1]

        if not production:
            return self.with_context(active_test=False).search(
                base_domain,
                order='active desc, production_date desc, id desc',
                limit=1,
            )
        return self.env['sn.wsd.internal.serial']

    def is_confirmed_scrapped(self):
        self.ensure_one()
        if self.final_result == 'scrap':
            return True
        if 'scrap_record_ids' not in self._fields:
            return False
        return bool(self.scrap_record_ids.filtered(lambda record: record.state == 'scrapped'))

    def check_packaging_readiness(self):
        self.ensure_one()
        if self.is_confirmed_scrapped():
            raise ValidationError(_('Serial number %s has been scrapped.') % self.serial_no)
        if self.pack_date:
            raise ValidationError(_('Serial number %s has already been packaged.') % self.serial_no)
        if 'x_freeze_state' in self._fields and self.x_freeze_state == 'frozen':
            raise ValidationError(_('Serial number %s is frozen.') % self.serial_no)
        if 'x_quality_hold_state' in self._fields and self.x_quality_hold_state in ('hold', 'blocked', 'scrapped'):
            raise ValidationError(_('Serial number %s is blocked by quality control.') % self.serial_no)
        if 'open_quality_issue_count' in self._fields and self.open_quality_issue_count:
            raise ValidationError(_('Serial number %s has an open quality issue.') % self.serial_no)
        if 'x_fqc_status' in self._fields and self.x_fqc_status == 'failed':
            raise ValidationError(_('Serial number %s has failed FQC.') % self.serial_no)
        if self.production_id.x_need_final_verification and self.final_verification_result != 'pass':
            raise ValidationError(_('Serial number %s has not passed final verification.') % self.serial_no)
        if self.final_result in ('fail', 'hold', 'scrap'):
            raise ValidationError(_('Serial number %s does not have a current passing result.') % self.serial_no)
        return True

    # Serial lifecycle state transitions were intentionally removed.  MES and
    # quality records keep their own statuses and update traceability fields only.

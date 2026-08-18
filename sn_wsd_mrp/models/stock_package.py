from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class StockPackage(models.Model):
    _inherit = 'stock.package'

    x_wsd_company_id = fields.Many2one(
        'res.company', string='WSD Company', default=lambda self: self.env.company, index=True,
    )
    x_wsd_package_role = fields.Selection(
        [('carton', 'Meter Carton'), ('pallet', 'Meter Pallet')],
        string='WSD Package Role',
        index=True,
        copy=False,
    )
    x_wsd_pack_state = fields.Selection(
        [('open', 'Open'), ('closed', 'Closed'), ('shipped', 'Shipped'), ('cancelled', 'Cancelled')],
        string='WSD Pack State',
        default='open',
        index=True,
        copy=False,
    )
    x_wsd_production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', index=True, check_company=True, copy=False,
    )
    x_wsd_pack_time = fields.Datetime(copy=False, index=True)
    x_wsd_close_time = fields.Datetime(copy=False, index=True)
    x_wsd_operator_code = fields.Char(copy=False, index=True)
    x_meter_pack_record_ids = fields.One2many(
        'sn.wsd.meter.pack.record', 'carton_package_id', string='Meter Pack Records', readonly=True,
    )

    @api.constrains('name', 'x_wsd_company_id', 'x_wsd_package_role', 'x_wsd_pack_state')
    def _check_wsd_package_reference(self):
        for package in self.filtered(lambda item: item.x_wsd_package_role and item.x_wsd_pack_state != 'cancelled'):
            duplicate = self.search([
                ('id', '!=', package.id),
                ('name', '=', package.name),
                ('x_wsd_company_id', '=', package.x_wsd_company_id.id),
                ('x_wsd_package_role', '!=', False),
                ('x_wsd_pack_state', '!=', 'cancelled'),
            ], limit=1)
            if duplicate:
                raise ValidationError(_('Package reference %s is already in use.') % package.name)

    @api.constrains('parent_package_id', 'x_wsd_package_role')
    def _check_wsd_package_hierarchy(self):
        for package in self.filtered('parent_package_id'):
            if package.x_wsd_package_role == 'pallet':
                raise ValidationError(_('A meter pallet cannot be placed inside another package.'))
            if package.x_wsd_package_role == 'carton' and package.parent_package_id.x_wsd_package_role != 'pallet':
                raise ValidationError(_('A meter carton can only be bound to a meter pallet.'))

    @api.model
    def get_or_create_wsd_package(self, reference, role, company, **values):
        reference = (reference or '').strip()
        if not reference:
            raise ValidationError(_('Package reference is required.'))
        package = self.search([
            ('name', '=', reference),
            ('x_wsd_company_id', '=', company.id),
            ('x_wsd_pack_state', '!=', 'cancelled'),
        ], limit=1)
        if package:
            if package.x_wsd_package_role and package.x_wsd_package_role != role:
                raise ValidationError(_(
                    'Package reference %(reference)s is already used as %(role)s.'
                ) % {'reference': reference, 'role': package.x_wsd_package_role})
            updates = {}
            if not package.x_wsd_package_role:
                updates['x_wsd_package_role'] = role
            for field_name, value in values.items():
                if field_name in self._fields and value and not package[field_name]:
                    updates[field_name] = value.id if hasattr(value, 'id') else value
            if updates:
                package.write(updates)
            return package
        package_type = self.env.ref(
            'sn_wsd_mrp.package_type_meter_carton' if role == 'carton' else 'sn_wsd_mrp.package_type_meter_pallet',
            raise_if_not_found=False,
        )
        create_values = {
            'name': reference,
            'package_type_id': package_type.id if package_type else False,
            'x_wsd_company_id': company.id,
            'x_wsd_package_role': role,
            'x_wsd_pack_state': 'open',
            'x_wsd_pack_time': fields.Datetime.now(),
        }
        create_values.update({
            key: value.id if hasattr(value, 'id') else value
            for key, value in values.items()
            if key in self._fields and value
        })
        return self.create(create_values)


class CartonPalletBindingLog(models.Model):
    _name = 'sn.wsd.carton.pallet.binding.log'
    _description = 'Carton Pallet Binding Log'
    _order = 'event_time desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    carton_package_id = fields.Many2one('stock.package', required=True, ondelete='restrict', index=True)
    pallet_package_id = fields.Many2one('stock.package', required=True, ondelete='restrict', index=True)
    previous_pallet_package_id = fields.Many2one('stock.package', ondelete='restrict', index=True)
    event_type = fields.Selection(
        [('bind', 'Bind'), ('unbind', 'Unbind'), ('move', 'Move'), ('close', 'Close')],
        required=True,
        default='bind',
        index=True,
    )
    operator_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, index=True)
    operator_code = fields.Char(index=True)
    event_time = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    reason = fields.Char()
    device_code = fields.Char(index=True)

    @api.model
    def bind_carton_to_pallet(self, pallet_no, carton_no, operator_code=None, device_code=None):
        company = self.env.company
        package_model = self.env['stock.package']
        pallet = package_model.get_or_create_wsd_package(
            pallet_no, 'pallet', company, x_wsd_operator_code=operator_code,
        )
        carton = package_model.search([
            ('name', '=', (carton_no or '').strip()),
            ('x_wsd_company_id', '=', company.id),
            ('x_wsd_package_role', '=', 'carton'),
            ('x_wsd_pack_state', '!=', 'cancelled'),
        ], limit=1)
        if not carton:
            raise ValidationError(_('Meter carton %s was not found.') % (carton_no or ''))
        if carton.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('Meter carton %s has already been shipped.') % carton.name)
        if pallet.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('Meter pallet %s has already been shipped.') % pallet.name)
        if pallet.x_wsd_pack_state == 'closed':
            raise ValidationError(_('Meter pallet %s is closed.') % pallet.name)
        if not carton.x_meter_pack_record_ids:
            raise ValidationError(_('Meter carton %s does not contain any meter pack record.') % carton.name)
        if carton.parent_package_id == pallet:
            return {
                'ok': True,
                'duplicated': True,
                'carton_id': carton.id,
                'carton_no': carton.name,
                'pallet_id': pallet.id,
                'pallet_no': pallet.name,
                'carton_count': len(pallet.child_package_ids),
                'meter_count': sum(len(item.x_meter_pack_record_ids) for item in pallet.child_package_ids),
            }
        if carton.parent_package_id:
            raise ValidationError(_(
                'Meter carton %(carton)s is already bound to pallet %(pallet)s.'
            ) % {'carton': carton.name, 'pallet': carton.parent_package_id.name})
        carton.parent_package_id = pallet
        carton.x_meter_pack_record_ids.write({'pallet_package_id': pallet.id, 'pallet_no': pallet.name})
        carton.x_meter_pack_record_ids.mapped('serial_id').write({'pallet_no': pallet.name})
        self.create({
            'company_id': company.id,
            'carton_package_id': carton.id,
            'pallet_package_id': pallet.id,
            'event_type': 'bind',
            'operator_code': operator_code,
            'device_code': device_code,
        })
        return {
            'ok': True,
            'duplicated': False,
            'carton_id': carton.id,
            'carton_no': carton.name,
            'pallet_id': pallet.id,
            'pallet_no': pallet.name,
            'carton_count': len(pallet.child_package_ids),
            'meter_count': sum(len(item.x_meter_pack_record_ids) for item in pallet.child_package_ids),
        }

    @api.model
    def close_pallet(self, pallet_no, operator_code=None, device_code=None):
        pallet = self.env['stock.package'].search([
            ('name', '=', (pallet_no or '').strip()),
            ('x_wsd_company_id', '=', self.env.company.id),
            ('x_wsd_package_role', '=', 'pallet'),
        ], limit=1)
        if not pallet:
            raise ValidationError(_('Meter pallet %s was not found.') % (pallet_no or ''))
        if not pallet.child_package_ids:
            raise ValidationError(_('An empty meter pallet cannot be closed.'))
        if pallet.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('Meter pallet %s has already been shipped.') % pallet.name)
        if pallet.x_wsd_pack_state != 'closed':
            pallet.write({'x_wsd_pack_state': 'closed', 'x_wsd_close_time': fields.Datetime.now()})
            self.create({
                'company_id': self.env.company.id,
                'carton_package_id': pallet.child_package_ids[:1].id,
                'pallet_package_id': pallet.id,
                'event_type': 'close',
                'operator_code': operator_code,
                'device_code': device_code,
            })
        return {
            'ok': True,
            'pallet_id': pallet.id,
            'pallet_no': pallet.name,
            'carton_count': len(pallet.child_package_ids),
            'meter_count': sum(len(item.x_meter_pack_record_ids) for item in pallet.child_package_ids),
        }

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SerialIdentity(models.Model):
    _name = 'sn.wsd.serial.identity'
    _description = 'Physical Serial Identity'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Physical SN', required=True, index=True, copy=False)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    origin_type = fields.Selection(
        [
            ('laser', 'Laser'),
            ('external', 'External'),
            ('manual', 'Manual'),
            ('migration', 'Migration'),
        ],
        default='external',
        required=True,
        index=True,
    )
    origin_production_id = fields.Many2one(
        'mrp.production', string='Origin Manufacturing Order', check_company=True, index=True,
    )
    origin_lot_id = fields.Many2one(
        'stock.lot', string='Origin Lot/Serial', check_company=True, index=True,
    )
    binding_ids = fields.One2many(
        'sn.wsd.serial.binding', 'serial_identity_id', string='Bindings',
    )
    bound_machine_binding_ids = fields.One2many(
        'sn.wsd.serial.binding', 'bound_serial_identity_id',
        string='Bound SNs',
    )
    note = fields.Text()

    _name_company_uniq = models.Constraint(
        'unique(company_id, name)',
        'The physical serial number must be unique per company.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values['name'] = (values.get('name') or '').strip()
            if not values['name']:
                raise ValidationError(_('Physical SN is required.'))
        return super().create(vals_list)

    @api.model
    def get_or_create(self, serial_no, company, **values):
        serial_no = (serial_no or '').strip()
        if not serial_no:
            raise ValidationError(_('Physical SN is required.'))
        identity = self.with_context(active_test=False).search([
            ('name', '=', serial_no),
            ('company_id', '=', company.id),
        ], limit=1)
        if identity:
            updates = {}
            if not identity.active:
                updates['active'] = True
            for field_name in ('origin_type', 'origin_production_id', 'origin_lot_id'):
                value = values.get(field_name)
                if value and not identity[field_name]:
                    updates[field_name] = value.id if hasattr(value, 'id') else value
            if updates:
                identity.write(updates)
            return identity
        create_values = {
            'name': serial_no,
            'company_id': company.id,
            **{
                key: value.id if hasattr(value, 'id') else value
                for key, value in values.items()
                if key in ('origin_type', 'origin_production_id', 'origin_lot_id', 'note') and value
            },
        }
        return self.create(create_values)

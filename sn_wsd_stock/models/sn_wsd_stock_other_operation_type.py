from odoo import api, fields, models

# Preset types of the other receipts and other deliveries. Each type carries
# the virtual location the goods move through, which is what selects the stock
# valuation account of the accounting entries. The locations are matched on
# their name: a database already carrying them keeps the existing ones.
DEFAULT_OPERATION_TYPES = (
    ('MEA', '计量误差调整', 'both'),
    ('CSW', '代码互换', 'both'),
    ('ASS', '售后服务', 'both'),
    ('RPS', '返修表', 'both'),
    ('SPS', '备表', 'both'),
    ('OSI', '办公用品领用', 'other_out'),
    ('RDI', '研发领用', 'other_out'),
    ('RDP', '研发产品', 'other_in'),
    ('RDS', '研发废料', 'other_out'),
    ('SCS', '废料销售', 'other_out'),
    ('SCP', '报废产品', 'other_out'),
    ('SRR', '报废残值回收', 'other_in'),
    ('CSP', '客户样品', 'other_out'),
)


class SnWsdStockOtherOperationType(models.Model):
    _name = 'sn.wsd.stock.other.operation.type'
    _description = 'Other Receipt and Delivery Type'
    _order = 'sequence, code, id'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True, index=True)
    operation = fields.Selection(
        selection=[
            ('other_out', 'Other Delivery'),
            ('other_in', 'Other Receipt'),
            ('both', 'Both'),
        ],
        string='Applies To',
        required=True,
        default='both',
        help='Direction of the other operations this type may be selected on.',
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Virtual Location',
        required=True,
        check_company=True,
        ondelete='restrict',
        domain=[('usage', '!=', 'view')],
        default=lambda self: self._default_location_id(),
        help='Virtual location the goods leave to (other delivery) or come '
             'from (other receipt). Its stock valuation account is the one '
             'used by the accounting entries of the operation.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        index=True,
        default=lambda self: self.env.company,
        help='Company the type and its virtual location belong to.',
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    note = fields.Text(string='Notes')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The type code must be unique.',
    )

    @api.model
    def _default_location_id(self):
        return self.env['stock.location']._sn_get_inventory_adjustment_location()

    @api.model
    def _ensure_default_types(self):
        """Create the preset types and the virtual locations they need.

        The production database already carries the virtual locations: they
        are looked up on their name and reused, never duplicated. A type
        already present is left untouched, so an administrator may rename it,
        change its location or archive it without the upgrade undoing it.
        """
        company = self.env.company
        Location = self.env['stock.location'].with_context(active_test=False)
        OperationType = self.with_context(active_test=False)
        names = [name for _code, name, _operation in DEFAULT_OPERATION_TYPES]
        locations = Location.search([
            ('usage', '=', 'inventory'),
            ('name', 'in', names),
            ('company_id', 'in', [company.id, False]),
        ])
        locations_by_name = {location.name: location for location in locations}
        for code, name, operation in DEFAULT_OPERATION_TYPES:
            location = locations_by_name.get(name)
            if not location:
                location = Location.create({
                    'name': name,
                    'usage': 'inventory',
                    'company_id': company.id,
                })
                locations_by_name[name] = location
            if not OperationType.search([('code', '=', code)], limit=1):
                OperationType.create({
                    'code': code,
                    'name': name,
                    'operation': operation,
                    'location_id': location.id,
                    'company_id': company.id,
                })
        return True

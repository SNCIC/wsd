from odoo import api, fields, models, _


class SnMrpWorkshop(models.Model):
    _name = 'sn.mrp.workshop'
    _description = 'Manufacturing Workshop'
    _order = 'sequence, code, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    component_location_id = fields.Many2one(
        'stock.location',
        string='Component Location',
        check_company=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
        help='Internal location where components are delivered before manufacturing.',
    )
    finished_product_location_id = fields.Many2one(
        'stock.location',
        string='Finished Product Location',
        check_company=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
        help='Internal location where finished products are stored before being transferred to stock.',
    )
    production_line_ids = fields.One2many(
        'sn.mrp.production.line',
        'workshop_id',
        string='Production Lines',
        copy=False,
    )
    note = fields.Text()

    _sn_mrp_workshop_company_code_unique = models.Constraint(
        'unique(company_id, code)',
        'The workshop code must be unique per company.',
    )

    def _get_copy_code(self):
        self.ensure_one()
        base_code = f'{self.code}_COPY'
        code = base_code
        index = 1
        while self.search_count([
            ('company_id', '=', self.company_id.id),
            ('code', '=', code),
        ]):
            index += 1
            code = f'{base_code}{index}'
        return code

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('name', _('%s (Copy)') % self.name)
        default.setdefault('code', self._get_copy_code())
        default.setdefault('active', True)
        return super().copy(default=default)


class SnMrpProductionLine(models.Model):
    _name = 'sn.mrp.production.line'
    _description = 'Manufacturing Production Line'
    _order = 'workshop_id, sequence, code, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        required=True,
        check_company=True,
        ondelete='restrict',
    )
    station_ids = fields.One2many(
        'mrp.workcenter',
        'x_production_line_id',
        string='Work Centers',
        copy=False,
    )
    team_ids = fields.One2many(
        'sn.mrp.team',
        'production_line_id',
        string='Teams',
        copy=False,
    )
    note = fields.Text()

    _sn_mrp_production_line_company_code_unique = models.Constraint(
        'unique(company_id, code)',
        'The production line code must be unique per company.',
    )

    @api.onchange('workshop_id')
    def _onchange_workshop_id_sync_company(self):
        for line in self:
            if line.workshop_id:
                line.company_id = line.workshop_id.company_id

    def _get_copy_code(self):
        self.ensure_one()
        base_code = f'{self.code}_COPY'
        code = base_code
        index = 1
        while self.search_count([
            ('company_id', '=', self.company_id.id),
            ('code', '=', code),
        ]):
            index += 1
            code = f'{base_code}{index}'
        return code

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('name', _('%s (Copy)') % self.name)
        default.setdefault('code', self._get_copy_code())
        default.setdefault('active', True)
        return super().copy(default=default)


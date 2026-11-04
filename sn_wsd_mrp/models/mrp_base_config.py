from odoo import api, fields, models, _
from odoo.exceptions import UserError


MTO_ROUTE_XMLID = 'stock.route_warehouse0_mto'
PRODUCTION_LOCATION_XMLID = 'stock.stock_location_production'


class SnMrpWorkshop(models.Model):
    _name = 'sn.mrp.workshop'
    _description = 'Manufacturing Workshop'
    _order = 'sequence, code, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(index=True, copy=False)
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                code = self.env['ir.sequence'].next_by_code('sn.mrp.workshop')
                if not code:
                    raise UserError(_(
                        'The coding rule is not configured. Please create an ir.sequence '
                        'with code %s in Settings > Technical > Sequences.'
                    ) % 'sn.mrp.workshop')
                vals['code'] = code
        workshops = super().create(vals_list)
        workshops._ensure_line_side_replenishment()
        return workshops

    def write(self, vals):
        res = super().write(vals)
        if {'component_location_id', 'company_id'} & set(vals):
            self._ensure_line_side_replenishment()
        return res

    # ------------------------------------------------------------------
    # Line-side replenishment rules
    # ------------------------------------------------------------------
    # A workshop line-side location is a workshop store, not a storage
    # sub-location: it hangs directly under the warehouse and therefore owns
    # nothing of the warehouse stock chain. Manufacturing still consumes the
    # components *from* that location, so the pull chain has to start there.
    # The native MTO rules only start at the warehouse stock location
    # (Stock -> Production), which the line-side location no longer walks up
    # to; without the two rules below the component move silently falls back
    # to "take from stock", the procurement never runs and no child
    # manufacturing order is created.
    def _line_side_production_location(self, company):
        """Virtual production location the workshop consumes into."""
        Location = self.env['stock.location'].sudo()
        location = Location.search([
            ('usage', '=', 'production'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not location:
            location = Location.search([
                ('usage', '=', 'production'),
                ('company_id', '=', False),
            ], limit=1)
        if not location:
            location = self.env.ref(PRODUCTION_LOCATION_XMLID, raise_if_not_found=False)
        return location

    def _sync_line_side_rule(self, route, source, destination, picking_type,
                             warehouse, company, name):
        """Create or refresh one MTO pull rule of the workshop store."""
        StockRule = self.env['stock.rule'].sudo()
        rule = StockRule.search([
            ('route_id', '=', route.id),
            ('location_src_id', '=', source.id),
            ('location_dest_id', '=', destination.id),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        values = {
            'name': name,
            'action': 'pull',
            'route_id': route.id,
            'location_src_id': source.id,
            'location_dest_id': destination.id,
            'picking_type_id': picking_type.id,
            'warehouse_id': warehouse.id,
            'company_id': company.id,
            'procure_method': 'make_to_order',
            'auto': 'manual',
            # The generated move must land on the rule destination: without
            # this flag the move takes the operation type destination instead
            # (stock -> stock for an internal transfer, stock -> stock for a
            # manufacture), so the material would never reach the workshop
            # store and the demand would stay unmet.
            'location_dest_from_rule': True,
        }
        # sn_wsd_stock extends stock.rule with a required weekend policy whose
        # column carries no SQL default; a rule created outside its views has
        # to state the value explicitly. The field is only present when that
        # module is installed, hence the guard.
        if 'weekend_policy' in StockRule._fields:
            values['weekend_policy'] = 'none'
        if rule:
            rule.write(values)
        else:
            rule = StockRule.create(values)
        return rule

    def _ensure_line_side_replenishment(self):
        """Make every workshop store a self-contained replenishment point.

        Two pull rules on the MTO route close the chain:
          * line-side -> production: the component demand of the workshop MO
            is flagged "trigger another rule" instead of "take from stock";
          * warehouse stock -> line-side: that demand is then supplied from
            stock, which in turn keeps triggering the existing manufacture /
            buy rules of the warehouse stock location (child MO, purchase).
        """
        mto_route = self.env.ref(MTO_ROUTE_XMLID, raise_if_not_found=False)
        if not mto_route:
            return
        for workshop in self:
            location = workshop.component_location_id
            if not location:
                continue
            warehouse = location.warehouse_id
            company = workshop.company_id or location.company_id
            if not warehouse or not company:
                continue
            stock_location = warehouse.lot_stock_id
            if not stock_location or stock_location == location:
                continue
            production_location = workshop._line_side_production_location(company)
            if not production_location:
                continue
            manu_type = warehouse.manu_type_id
            int_type = warehouse.int_type_id or manu_type
            if not manu_type or not int_type:
                continue
            workshop._sync_line_side_rule(
                mto_route, location, production_location, manu_type,
                warehouse, company,
                _('%(warehouse)s: %(location)s → %(production)s (MTO)',
                  warehouse=warehouse.code or warehouse.name,
                  location=location.name,
                  production=production_location.name),
            )
            workshop._sync_line_side_rule(
                mto_route, stock_location, location, int_type,
                warehouse, company,
                _('%(warehouse)s: %(stock)s → %(location)s (MTO)',
                  warehouse=warehouse.code or warehouse.name,
                  stock=stock_location.name,
                  location=location.name),
            )


class SnMrpProductionLine(models.Model):
    _name = 'sn.mrp.production.line'
    _description = 'Manufacturing Production Line'
    _order = 'workshop_id, sequence, code, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(index=True, copy=False)
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
    x_smt_is_feeder_control = fields.Boolean(string='Feeder Control')
    x_line_type = fields.Selection(
        [('auto', 'Automated Line'), ('manual', 'Manual Line')],
        string='Line Type',
        default='manual',
    )

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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                code = self.env['ir.sequence'].next_by_code('sn.mrp.production.line')
                if not code:
                    raise UserError(_(
                        'The coding rule is not configured. Please create an ir.sequence '
                        'with code %s in Settings > Technical > Sequences.'
                    ) % 'sn.mrp.production.line')
                vals['code'] = code
        return super().create(vals_list)


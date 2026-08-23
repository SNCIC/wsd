from odoo import _, api, fields, models
from odoo.exceptions import UserError

CART_STATUS_SELECTION = [
    ('idle', 'Idle'),
    ('loaded', 'Loaded'),
    ('mounted', 'Mounted'),
    ('disabled', 'Disabled'),
    ('scrapped', 'Scrapped'),
]


class SnSmtCart(models.Model):
    _name = 'sn.smt.cart'
    _description = 'SMT Material Cart'
    _inherit = ['mail.thread']
    _order = 'cart_sn, id'
    _check_company_auto = True

    cart_sn = fields.Char(string='CART_SN', required=True, index=True, tracking=True)
    name = fields.Char(string='Cart', compute='_compute_name', store=True)
    status = fields.Selection(
        CART_STATUS_SELECTION,
        string='Status',
        default='idle',
        required=True,
        index=True,
        tracking=True,
    )
    mounted_workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Mounted Workcenter',
        copy=False,
        index=True,
        check_company=True,
        tracking=True,
    )
    mounted_at = fields.Datetime(string='Mounted At', copy=False, readonly=True)
    unmounted_at = fields.Datetime(string='Unmounted At', copy=False, readonly=True)
    active_line_ids = fields.One2many(
        'sn.smt.cart.line',
        'cart_id',
        string='Active Feeder Lines',
        domain=[('removed_at', '=', False)],
    )
    line_ids = fields.One2many('sn.smt.cart.line', 'cart_id', string='Feeder Lines')
    feeder_ids = fields.Many2many('sn.smt.feeder', compute='_compute_feeder_ids', string='Feeders')
    feeder_count = fields.Integer(compute='_compute_feeder_ids')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_smt_cart_sn_unique = models.Constraint(
        'unique(company_id, cart_sn)',
        'The cart SN must be unique per company.',
    )

    @api.depends('cart_sn')
    def _compute_name(self):
        for cart in self:
            cart.name = cart.cart_sn

    @api.depends('active_line_ids.feeder_id')
    def _compute_feeder_ids(self):
        for cart in self:
            cart.feeder_ids = cart.active_line_ids.mapped('feeder_id')
            cart.feeder_count = len(cart.feeder_ids)

    def _get_active_lines(self):
        self.ensure_one()
        return self.env['sn.smt.cart.line'].search([
            ('cart_id', '=', self.id),
            ('removed_at', '=', False),
        ])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def action_disable(self):
        for cart in self:
            if cart.status == 'scrapped':
                raise UserError(_('The cart is scrapped and cannot be disabled.'))
            if cart.mounted_workcenter_id:
                raise UserError(_('The cart must be unmounted before it can be disabled.'))
        self.write({'status': 'disabled'})
        return True

    def action_enable(self):
        for cart in self:
            if cart.status != 'disabled':
                raise UserError(_('Only a disabled cart can be enabled.'))
        for cart in self:
            cart.status = 'loaded' if cart._get_active_lines() else 'idle'
        return True

    def action_scrap(self):
        for cart in self:
            if cart.status == 'scrapped':
                raise UserError(_('The cart is already scrapped.'))
            if cart.mounted_workcenter_id:
                raise UserError(_('The cart must be unmounted before it can be scrapped.'))
            if cart._get_active_lines():
                raise UserError(_('The cart must be empty before it can be scrapped.'))
        self.write({'status': 'scrapped'})
        for cart in self:
            cart.message_post(body=_('Cart %s scrapped.', cart.cart_sn))
        return True

    # ------------------------------------------------------------------
    # Mount / unmount
    # ------------------------------------------------------------------

    def action_open_mount(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.smt.cart.mount.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': self.env.ref('sn_wsd_smt.action_sn_smt_cart_mount_wizard').name,
            'context': {'default_cart_id': self.id},
        }

    def action_mount(self, workcenter):
        for cart in self:
            if cart.status in ('disabled', 'scrapped'):
                raise UserError(_('The cart status is invalid.'))
            if cart.mounted_workcenter_id:
                raise UserError(
                    _('The cart is already mounted on %s.', cart.mounted_workcenter_id.display_name))
            invalid_feeders = cart._get_active_lines().mapped('feeder_id').filtered(
                lambda feeder: feeder.status in ('disabled', 'scrapped', 'in_repair'))
            if invalid_feeders:
                raise UserError(
                    _('The cart holds feeders with an invalid status: %s.',
                      ', '.join(invalid_feeders.mapped('feeder_sn'))))
            missing, extra = cart._check_mount_material()
            cart.write({
                'mounted_workcenter_id': workcenter.id,
                'mounted_at': fields.Datetime.now(),
                'status': 'mounted',
            })
            notes = [_('Cart %s mounted on %s.', cart.cart_sn, workcenter.display_name)]
            if missing:
                notes.append(_('Stations required by the MES order but not on the cart: %s.',
                               ', '.join(missing)))
            if extra:
                notes.append(_('Stations on the cart but not required by the MES order: %s.',
                               ', '.join(extra)))
            cart.message_post(body='<br/>'.join(notes))
        return True

    def _check_mount_material(self):
        """ Compare the cart's active lines with the MES order requirements.

        Wrong material at a required station blocks the mount. Missing and
        extra stations are returned as warnings (shared-material changeovers
        legitimately prep only the differing stations).
        """
        self.ensure_one()
        lines = self._get_active_lines()
        mismatch = []
        extra = []
        for line in lines:
            requirements = self.env['sn.smt.online.material'].search([
                ('mes_order_id', '=', line.mes_order_id.id),
                ('loadpoint', '=', line.slot_no),
                ('company_id', '=', self.company_id.id),
            ])
            if not requirements:
                extra.append(line.slot_no)
                continue
            if line.material_lot_id and not any(
                self._cart_material_matches(line.mes_order_id, req.item_code, line.material_lot_id.product_id)
                for req in requirements):
                mismatch.append((line.slot_no, line.material_lot_id.product_id.default_code,
                                 ', '.join(sorted(set(requirements.mapped('item_code'))))))
        if mismatch:
            details = '; '.join(
                _('station %s: %s loaded, %s required.', station, loaded, required)
                for station, loaded, required in sorted(mismatch))
            raise UserError(_('The cart cannot be mounted because materials conflict with the MES order requirements: %s', details))
        missing = []
        for mes_order in lines.mapped('mes_order_id'):
            requirements = self.env['sn.smt.online.material'].search([
                ('mes_order_id', '=', mes_order.id),
                ('company_id', '=', self.company_id.id),
            ]).filtered(lambda req: req.is_tray != 'Y' and req.is_skip != 'Y')
            covered = set(lines.mapped('slot_no'))
            missing += [loadpoint for loadpoint in sorted(set(requirements.mapped('loadpoint')))
                        if loadpoint not in covered]
        return missing, extra

    @api.model
    def _cart_material_matches(self, mes_order, item_code, product):
        if not product:
            return False
        required = self.env['product.product'].search([
            ('default_code', '=', item_code),
        ], limit=1)
        if required:
            return self.env['sn.smt.operation.mixin']._is_allowed_material_product(
                mes_order, required, product)
        return product.default_code == item_code

    def action_unmount(self):
        for cart in self:
            if not cart.mounted_workcenter_id:
                raise UserError(_('The cart is not mounted on any workcenter.'))
            workcenter = cart.mounted_workcenter_id
            cart.write({
                'mounted_workcenter_id': False,
                'unmounted_at': fields.Datetime.now(),
                'status': 'loaded' if cart._get_active_lines() else 'idle',
            })
            cart.message_post(body=_('Cart %s unmounted from %s.', cart.cart_sn, workcenter.display_name))
        return True

    def action_clear_lines(self):
        for cart in self:
            if cart.mounted_workcenter_id:
                raise UserError(_('The cart must be unmounted before it can be cleared.'))
            active_lines = cart._get_active_lines()
            if not active_lines:
                continue
            active_lines.write({'removed_at': fields.Datetime.now()})
            cart.message_post(body=_('Cart %s cleared: %s feeder(s) unbound.',
                                     cart.cart_sn, len(active_lines)))
        return True


class SnSmtCartLine(models.Model):
    _name = 'sn.smt.cart.line'
    _description = 'SMT Cart Feeder Line'
    _order = 'cart_id, slot_no, id'
    _check_company_auto = True

    cart_id = fields.Many2one(
        'sn.smt.cart',
        string='CART_SN',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='FEEDER_SN',
        required=True,
        ondelete='restrict',
        index=True,
        check_company=True,
    )
    slot_no = fields.Char(string='Station No', required=True, index=True)
    material_lot_id = fields.Many2one(
        'stock.lot',
        string='Material Lot',
        check_company=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        required=True,
        index=True,
        check_company=True,
    )
    installed_at = fields.Datetime(string='Installed At', default=fields.Datetime.now, required=True)
    removed_at = fields.Datetime(string='Removed At', readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='cart_id.company_id',
        store=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            line._validate_active()
            line.feeder_id.cart_id = line.cart_id
            line._sync_cart_status()
        return lines

    def write(self, vals):
        result = super().write(vals)
        reactivation_fields = {'feeder_id', 'cart_id', 'slot_no', 'material_lot_id', 'mes_order_id'}
        for line in self:
            if 'removed_at' in vals:
                if line.removed_at and line.feeder_id.cart_id == line.cart_id:
                    line.feeder_id.cart_id = False
                elif not line.removed_at:
                    line.feeder_id.cart_id = line.cart_id
            if not line.removed_at and reactivation_fields & set(vals):
                line._validate_active()
                line.feeder_id.cart_id = line.cart_id
            line._sync_cart_status()
        return result

    def unlink(self):
        for line in self:
            if not line.removed_at and line.feeder_id.cart_id == line.cart_id:
                line.feeder_id.cart_id = False
        result = super().unlink()
        for cart in self.mapped('cart_id'):
            cart_line = self.env['sn.smt.cart.line']
            if cart.status not in ('disabled', 'scrapped', 'mounted') and not cart_line.search_count([
                    ('cart_id', '=', cart.id), ('removed_at', '=', False)], limit=1):
                cart.status = 'idle'
        return result

    def action_unbind(self):
        self.write({'removed_at': fields.Datetime.now()})
        return True

    def _sync_cart_status(self):
        cart_line = self.env['sn.smt.cart.line']
        for cart in self.mapped('cart_id'):
            if cart.status in ('disabled', 'scrapped', 'mounted'):
                continue
            has_active = cart_line.search_count([
                ('cart_id', '=', cart.id),
                ('removed_at', '=', False),
            ], limit=1)
            cart.status = 'loaded' if has_active else 'idle'

    def _validate_active(self):
        self.ensure_one()
        cart_line = self.env['sn.smt.cart.line']
        if self.cart_id.status in ('disabled', 'scrapped'):
            raise UserError(_('The cart status is invalid.'))
        feeder = self.feeder_id
        if feeder.status != 'normal':
            raise UserError(
                _('The feeder %s is not available for cart loading.', feeder.feeder_sn))
        if feeder.cart_id and feeder.cart_id != self.cart_id:
            raise UserError(
                _('The feeder %s is already on cart %s.', feeder.feeder_sn, feeder.cart_id.cart_sn))
        if cart_line.search_count([
                ('removed_at', '=', False),
                ('feeder_id', '=', feeder.id),
                ('id', '!=', self.id),
        ], limit=1):
            other = cart_line.search([
                ('removed_at', '=', False), ('feeder_id', '=', feeder.id)], limit=1)
            raise UserError(
                _('The feeder %s is already on cart %s.', feeder.feeder_sn, other.cart_id.cart_sn))
        if cart_line.search_count([
                ('cart_id', '=', self.cart_id.id),
                ('slot_no', '=', self.slot_no),
                ('removed_at', '=', False),
                ('id', '!=', self.id),
        ], limit=1):
            raise UserError(
                _('The station %s on cart %s is already occupied.', self.slot_no, self.cart_id.cart_sn))
        if self.material_lot_id and cart_line.search_count([
                ('removed_at', '=', False),
                ('material_lot_id', '=', self.material_lot_id.id),
                ('id', '!=', self.id),
        ], limit=1):
            raise UserError(
                _('The material %s is already mounted on a cart.', self.material_lot_id.name))
        other_order_lines = cart_line.search([
            ('cart_id', '=', self.cart_id.id),
            ('removed_at', '=', False),
            ('id', '!=', self.id),
            ('mes_order_id', '!=', self.mes_order_id.id),
        ], limit=1)
        if other_order_lines:
            raise UserError(
                _('The cart %s is prepared for MES order %s. All feeder lines must target the same MES order.',
                  self.cart_id.cart_sn, other_order_lines.mes_order_id.display_name))
        requirements = self.env['sn.smt.online.material'].search([
            ('mes_order_id', '=', self.mes_order_id.id),
            ('loadpoint', '=', self.slot_no),
            ('company_id', '=', self.cart_id.company_id.id),
        ])
        if not requirements:
            raise UserError(
                _('The station %s is not required by MES order %s.',
                  self.slot_no, self.mes_order_id.display_name))
        if self.material_lot_id and not any(
                self.cart_id._cart_material_matches(req.item_code, self.material_lot_id.product_id)
                for req in requirements):
            raise UserError(
                _('The material %s does not match station %s. Required item code: %s.',
                  self.material_lot_id.name, self.slot_no,
                  ', '.join(sorted(set(requirements.mapped('item_code'))))))

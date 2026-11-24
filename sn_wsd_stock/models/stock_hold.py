from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# Hold types and the state they put on the held record. A batch or serial
# number is sealed (kept in stock but not usable) or blocked (waiting for a
# quality decision); a whole material is disabled (no new purchase or use).
HOLD_STATES = {
    'blocked': 'blocked',
    'sealed': 'sealed',
    'disabled': 'disabled',
}


class SnWsdStockHold(models.Model):
    """Quality hold of a batch, a serial number or a whole material.

    A quality risk found on incoming material or on finished goods is recorded
    here: the held batch (or the whole material) leaves the usable pool and
    every outgoing flow refuses it until the hold is released. The quantity
    already ordered or received is untouched, so the document trail stays
    complete.
    """

    _name = 'sn.wsd.stock.hold'
    _description = 'Stock Quality Hold'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'hold_date desc, id desc'

    name = fields.Char(
        string='Hold Reference',
        default='/',
        copy=False,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    target_type = fields.Selection(
        selection=[('lot', 'Batch/Serial'), ('product', 'Material')],
        string='Scope',
        required=True,
        default='lot',
        tracking=True,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Material',
        required=True,
        tracking=True,
    )
    lot_id = fields.Many2one(
        comodel_name='stock.lot',
        string='Batch/Serial',
        domain="[('product_id', '=', product_id)]",
        tracking=True,
    )
    hold_type = fields.Selection(
        selection=[
            ('blocked', 'Blocked'),
            ('sealed', 'Sealed'),
            ('disabled', 'Disabled'),
        ],
        string='Hold Type',
        required=True,
        default='blocked',
        tracking=True,
        help="Blocked and sealed apply to a batch or serial number; disabled "
             "applies to the whole material.",
    )
    state = fields.Selection(
        selection=[('active', 'Held'), ('released', 'Released')],
        string='Status',
        required=True,
        default='active',
        tracking=True,
        index=True,
    )
    reason = fields.Text(string='Quality Risk', required=True)
    origin = fields.Char(string='Source Document')
    hold_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Held by',
        readonly=True,
        default=lambda self: self.env.user,
    )
    hold_date = fields.Datetime(
        string='Hold Date', readonly=True, default=fields.Datetime.now,
    )
    release_user_id = fields.Many2one(
        comodel_name='res.users', string='Released by', readonly=True,
    )
    release_date = fields.Datetime(string='Release Date', readonly=True)
    release_reason = fields.Text(string='Release Reason')

    @api.constrains('target_type', 'lot_id', 'hold_type')
    def _check_target(self):
        for hold in self:
            if hold.target_type == 'lot' and not hold.lot_id:
                raise ValidationError(
                    _('A batch or serial number is required to hold a lot.')
                )
            if hold.target_type == 'product' and hold.lot_id:
                raise ValidationError(
                    _('A material hold must not target a batch or serial number.')
                )
            if hold.target_type == 'product' and hold.hold_type != 'disabled':
                raise ValidationError(
                    _('Only a disabled hold applies to a whole material.')
                )

    @api.constrains('state', 'target_type', 'lot_id', 'product_id')
    def _check_single_active_hold(self):
        for hold in self.filtered(lambda record: record.state == 'active'):
            domain = [
                ('id', '!=', hold.id),
                ('state', '=', 'active'),
                ('company_id', '=', hold.company_id.id),
                ('target_type', '=', hold.target_type),
            ]
            if hold.target_type == 'lot':
                domain.append(('lot_id', '=', hold.lot_id.id))
            else:
                domain.append(('product_id', '=', hold.product_id.id))
            if self.search_count(domain):
                raise ValidationError(_(
                    'An active hold already exists for %s.',
                    hold.lot_id.display_name or hold.product_id.display_name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.stock.hold'
                ) or '/'
        holds = super().create(vals_list)
        holds._apply_hold()
        return holds

    def write(self, vals):
        result = super().write(vals)
        if {'state', 'hold_type', 'lot_id', 'product_id', 'target_type'} & set(vals):
            self._apply_hold()
        return result

    def _apply_hold(self):
        """Put the current state of the hold on the held record."""
        self._clear_hold()
        for hold in self.filtered(lambda record: record.state == 'active'):
            values = {
                'sn_hold_state': HOLD_STATES.get(hold.hold_type, 'blocked'),
                'sn_hold_reason': hold.reason,
                'sn_hold_id': hold.id,
                'sn_hold_date': hold.hold_date,
            }
            if hold.target_type == 'lot':
                hold.lot_id.write(values)
            else:
                hold.product_id.product_tmpl_id.write(values)

    def _clear_hold(self):
        """Remove the state this hold left on its record.

        The state is only removed when the record still points at this hold:
        a record released twice, or a record now held by a newer document,
        keeps its current state.
        """
        for hold in self:
            target = hold.lot_id if hold.target_type == 'lot' else (
                hold.product_id.product_tmpl_id
            )
            if not target or hold.id not in target.sn_hold_id.ids:
                continue
            target.write({
                'sn_hold_state': 'none',
                'sn_hold_reason': False,
                'sn_hold_id': False,
                'sn_hold_date': False,
            })

    def action_release(self):
        """Release the selected holds, putting the records back in use."""
        holds = self.filtered(lambda record: record.state == 'active')
        if not holds:
            raise UserError(_('The selected holds are already released.'))
        holds._clear_hold()
        return holds.write({
            'state': 'released',
            'release_user_id': self.env.user.id,
            'release_date': fields.Datetime.now(),
        })

    @api.model
    def _create_hold(self, product, lot, hold_type, reason, origin=False):
        """Hold a record for quality, without duplicating an active hold.

        Used by the quality flows: an inspection that fails holds the batch it
        found the defect on, and a second failure on the same batch keeps the
        first document instead of piling up holds.
        """
        domain = [
            ('state', '=', 'active'),
            ('company_id', '=', self.env.company.id),
            ('target_type', '=', 'lot' if lot else 'product'),
        ]
        if lot:
            domain.append(('lot_id', '=', lot.id))
        else:
            domain.append(('product_id', '=', product.id))
        existing = self.search(domain, limit=1)
        if existing:
            return existing
        return self.create({
            'target_type': 'lot' if lot else 'product',
            'product_id': product.id,
            'lot_id': lot.id if lot else False,
            'hold_type': hold_type,
            'reason': reason,
            'origin': origin,
        })

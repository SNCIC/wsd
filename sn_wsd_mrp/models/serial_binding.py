from odoo import api, fields, models


class SerialBinding(models.Model):
    """Mapping between two serial identities: a product SN bound to the
    machine SN it was built into, or a nameplate SN mapped to its machine
    SN (scan the nameplate, resolve the machine). The future API uploads
    these relations in bulk."""
    _name = 'sn.wsd.serial.binding'
    _description = 'Serial Identity Binding'
    _order = 'binding_date desc, id desc'
    _check_company_auto = True

    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', required=True, index=True,
        ondelete='cascade', check_company=True,
        help='The bound SN: the product SN for a machine binding, the '
             'nameplate SN for a nameplate mapping.')
    bound_serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='Bound Machine SN', required=True,
        index=True, ondelete='cascade', check_company=True,
        help='The machine SN the other SN is bound to.')
    binding_type = fields.Selection(
        [
            ('machine', 'Machine Binding'),
            ('nameplate', 'Nameplate Mapping'),
        ],
        required=True, default='machine', index=True,
        help='Machine binding: a product SN was assembled into this machine '
             'SN. Nameplate mapping: scanning the nameplate SN resolves to '
             'this machine SN.')
    binding_date = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    source = fields.Selection(
        [('manual', 'Manual'), ('api', 'API')],
        default='manual', required=True,
        help='Manual entries come from the UI; API entries are uploaded by '
             'the future device API.')
    note = fields.Text()
    is_current = fields.Boolean(
        string='Current', default=False, index=True, copy=False,
        help='True on the latest binding of each (SN, type); demoted '
             'automatically when a newer binding of the same SN and type '
             'is created, so current mappings resolve in one search.')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True,
    )

    _binding_uniq = models.Constraint(
        'unique(company_id, serial_identity_id, bound_serial_identity_id, '
        'binding_type)',
        'The same SN pair can only be bound once per binding type.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._promote_as_current()
        return records

    def _promote_as_current(self):
        """Mark these bindings current and demote every older binding of
        the same (SN, type), including a pair bound earlier and re-bound
        now (its historical row is promoted back in place)."""
        for binding in self:
            siblings = self.search([
                ('serial_identity_id', '=', binding.serial_identity_id.id),
                ('binding_type', '=', binding.binding_type),
                ('company_id', '=', binding.company_id.id),
                ('is_current', '=', True),
                ('id', '!=', binding.id),
            ])
            siblings.write({'is_current': False})
            if not binding.is_current:
                binding.is_current = True

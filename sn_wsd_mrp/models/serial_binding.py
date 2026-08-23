from odoo import fields, models


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
    binding_date = fields.Datetime(default=fields.Datetime.now, required=True)
    source = fields.Selection(
        [('manual', 'Manual'), ('api', 'API')],
        default='manual', required=True,
        help='Manual entries come from the UI; API entries are uploaded by '
             'the future device API.')
    note = fields.Text()
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True,
    )

    _binding_uniq = models.Constraint(
        'unique(company_id, serial_identity_id, bound_serial_identity_id, '
        'binding_type)',
        'The same SN pair can only be bound once per binding type.',
    )

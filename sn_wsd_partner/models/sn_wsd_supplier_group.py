from odoo import api, fields, models

from odoo.exceptions import ValidationError


class SnWsdSupplierGroup(models.Model):
    """Supplier group: the number that prefixes the supplier code.

    The account keeps a two-level tree — 01, 02 ... 09, 10 (fees) carrying the
    sub-groups 10.001 (certification fees) and 10.002 (other fees), and 99 — so
    a group may sit under another one. The prefix of the generated supplier
    code always comes from the top-level group: a supplier filed under 10.001
    is numbered 10.xxx, like every other supplier of the fees group, and the
    whole tree branch shares one counter.

    Deliberately a model of its own, not a contact tag: a group numbers the
    suppliers that belong to it, a tag classifies contacts, and the two carry
    different life cycles and permissions."""

    _name = 'sn.wsd.supplier.group'
    _description = 'Supplier Group'
    _order = 'code, name'
    _rec_name = 'display_name'

    name = fields.Char(string='Name', required=True, translate=False)
    code = fields.Char(
        string='Code', required=True,
        help='Number of the group as the account shows it: two digits for a '
             'top-level group (01, 99) and the parent number plus a serial '
             'for a sub-group (10.001). Each code may exist once.')
    parent_id = fields.Many2one(
        'sn.wsd.supplier.group', string='Parent Group', index=True,
        ondelete='restrict',
        help='Top-level group this one sits under, if any.')
    child_ids = fields.One2many(
        'sn.wsd.supplier.group', 'parent_id', string='Sub-groups')
    prefix = fields.Char(
        string='Code Prefix', compute='_compute_prefix',
        help='Top-level number used to prefix the supplier code; equals the '
             'code itself for a top-level group.')
    active = fields.Boolean(default=True)
    display_name = fields.Char(
        string='Group', compute='_compute_display_name', store=False)
    supplier_count = fields.Integer(
        string='Suppliers', compute='_compute_supplier_count')

    _code_unique = models.Constraint(
        'unique(code)',
        'The group code must be unique.',
    )

    @api.depends('code', 'parent_id')
    def _compute_prefix(self):
        for group in self:
            root = group
            while root.parent_id:
                root = root.parent_id
            group.prefix = root.code or ''

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for group in self:
            group.display_name = '%s(%s)' % (group.code, group.name) \
                if group.code else group.name

    def _compute_supplier_count(self):
        counts = self.env['res.partner'].sudo()._read_group(
            [('supplier_categ_id', 'in', self.ids)],
            ['supplier_categ_id'], ['__count'])
        by_group = {group.id: count for group, count in counts}
        for group in self:
            group.supplier_count = by_group.get(group.id, 0)

    @api.constrains('parent_id')
    def _check_parent_depth(self):
        """The account numbers its groups with one level of sub-groups only:
        refuse a tree deeper than that before it reaches the coding rule."""
        for group in self:
            if group.parent_id.parent_id:
                raise ValidationError(self.env._(
                    'Supplier groups support one level of sub-groups only: '
                    '%s already sits under %s.', group.parent_id.display_name,
                    group.parent_id.parent_id.display_name))

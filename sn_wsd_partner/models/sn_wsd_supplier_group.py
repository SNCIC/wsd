from odoo import api, fields, models


class SnWsdSupplierGroup(models.Model):
    """Supplier group: the two-digit number that prefixes the supplier code
    (01, 02, 03, 05 ... 99 in the account).

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
        help='Code prefixed to the supplier code, e.g. 01 for the electronic '
             'components group. Two digits by convention; each code may exist '
             'once.')
    active = fields.Boolean(default=True)
    display_name = fields.Char(
        string='Group', compute='_compute_display_name', store=False)
    supplier_count = fields.Integer(
        string='Suppliers', compute='_compute_supplier_count')

    _code_unique = models.Constraint(
        'unique(code)',
        'The group code must be unique.',
    )

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

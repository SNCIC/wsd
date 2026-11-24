from odoo import api, fields, models


class EipCategory(models.Model):
    """EIP category dictionary (CATEGORY_CODE): platform-issued global
    reference data shared across companies, following the NQI
    dictionary precedent (no company_id)."""
    _name = 'sn.wsd.eip.category'
    _description = 'EIP Category'
    _order = 'code, id'

    code = fields.Char(string='Code', required=True, index=True)
    name = fields.Char(string='Name', required=True)
    display_name = fields.Char(
        string='Display Name', compute='_compute_display_name')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The category code must be unique.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s / %s' % (
                record.code, record.name)


class EipSubclass(models.Model):
    """EIP subclass dictionary (SUBCLASS_CODE) under a category; same
    global-dictionary treatment as the category."""
    _name = 'sn.wsd.eip.subclass'
    _description = 'EIP Subclass'
    _order = 'code, id'

    code = fields.Char(string='Code', required=True, index=True)
    name = fields.Char(string='Name', required=True)
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category', required=True,
        index=True, ondelete='cascade')
    display_name = fields.Char(
        string='Display Name', compute='_compute_display_name')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The subclass code must be unique.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s / %s' % (
                record.code, record.name)


class EipProcessCode(models.Model):
    """EIP process code dictionary (PROCESS_CODE). The spec ships no
    dictionary: delivered empty and maintained by the user; work
    reports and schedule process rows pick from here or free-type."""
    _name = 'sn.wsd.eip.process.code'
    _description = 'EIP Process Code'
    _order = 'code, id'

    code = fields.Char(string='Code', required=True, index=True)
    name = fields.Char(string='Name', required=True)
    display_name = fields.Char(
        string='Display Name', compute='_compute_display_name')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The process code must be unique.',
    )

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s / %s' % (
                record.code, record.name)

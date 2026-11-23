from odoo import api, fields, models


class NqiCodeSort(models.Model):
    """NQI code sort dictionary (PUB_CODE_SORT), preloaded from the
    NQI-issued public info workbook. Global reference data, shared
    across companies (no company_id, like other plain dictionaries)."""
    _name = 'sn.wsd.nqi.code.sort'
    _description = 'NQI Code Sort'
    _order = 'code_sort_id, id'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True)
    code_sort_id = fields.Char(string='Sort ID', index=True)
    code_type = fields.Char(string='Code Type', required=True, index=True)
    note = fields.Char(string='Note')

    _code_type_uniq = models.Constraint(
        'unique(code_type)',
        'A code type can only be declared once.',
    )


class NqiCode(models.Model):
    """NQI code dictionary (PUB_CODE / P_CODE), preloaded from the
    NQI-issued public info workbook. Every P_CODE-typed mirror column
    points here with a domain on ``code_type``."""
    _name = 'sn.wsd.nqi.code'
    _description = 'NQI Code'
    _order = 'code_type, code_id, id'

    code_id = fields.Char(string='Code ID', required=True, index=True)
    code_type = fields.Char(string='Code Type', required=True, index=True)
    value = fields.Char(string='Value')
    name = fields.Char(string='Name', required=True)
    note = fields.Char(string='Note')
    display_name = fields.Char(
        string='Display Name', compute='_compute_display_name')

    _code_uniq = models.Constraint(
        'unique(code_type, code_id)',
        'A code id must be unique inside its code type.',
    )

    @api.depends('code_id', 'code_type', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s / %s' % (
                record.code_id, record.name)

    def name_get(self):
        # keep the compact "code / name" form for m2o labels
        return [(record.id, record.display_name) for record in self]

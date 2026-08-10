from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_msd_material = fields.Boolean(string='MSD Material', tracking=True)
    msl_level_id = fields.Many2one(
        'sn.msd.level',
        string='MSL Level',
        tracking=True,
    )
    component_thickness = fields.Float(
        string='Component Thickness',
        tracking=True,
    )
    msd_control_rule_id = fields.Many2one(
        'sn.msd.control.rule',
        string='MSD Control Rule',
        compute='_compute_msd_control_rule_id',
    )

    @api.depends('is_msd_material', 'msl_level_id', 'component_thickness', 'company_id')
    def _compute_msd_control_rule_id(self):
        rule_model = self.env['sn.msd.control.rule']
        for product in self:
            company = product.company_id or self.env.company
            product.msd_control_rule_id = rule_model._match_rule(product.product_variant_id, company=company)

    @api.constrains('is_msd_material', 'msl_level_id', 'component_thickness')
    def _check_msd_required_fields(self):
        for product in self:
            if not product.is_msd_material:
                continue
            if not product.msl_level_id or product.component_thickness <= 0:
                raise ValidationError(_('MSD materials must have an MSL level and component thickness.'))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    is_msd_material = fields.Boolean(
        related='product_tmpl_id.is_msd_material',
        store=True,
    )
    msl_level_id = fields.Many2one(
        related='product_tmpl_id.msl_level_id',
        store=True,
    )
    component_thickness = fields.Float(
        related='product_tmpl_id.component_thickness',
        store=True,
    )
    msd_control_rule_id = fields.Many2one(
        'sn.msd.control.rule',
        string='MSD Control Rule',
        compute='_compute_msd_control_rule_id',
    )

    @api.depends('is_msd_material', 'msl_level_id', 'component_thickness', 'company_id')
    def _compute_msd_control_rule_id(self):
        rule_model = self.env['sn.msd.control.rule']
        for product in self:
            company = product.company_id or product.product_tmpl_id.company_id or self.env.company
            product.msd_control_rule_id = rule_model._match_rule(product, company=company)

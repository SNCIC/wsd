from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain


BOM_LOCKED_FIELDS = {
    'product_tmpl_id',
    'product_id',
    'product_qty',
    'product_uom_id',
    'type',
    'bom_line_ids',
    'byproduct_ids',
    'operation_ids',
    'x_process_route_id',
}

BOM_LINE_LOCKED_FIELDS = {
    'product_id',
    'product_qty',
    'product_uom_id',
    'operation_id',
    'bom_product_template_attribute_value_ids',
    'substitute_line_ids',
}


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    x_bom_stage_type = fields.Selection(
        [
            ('engineering', 'Engineering'),
            ('production', 'Production'),
        ],
        string='BoM Usage',
        default='production',
        required=True,
        index=True,
        tracking=True,
    )
    x_plm_state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('review', 'In Review'),
            ('released', 'Released'),
            ('obsolete', 'Obsolete'),
            ('cancelled', 'Cancelled'),
        ],
        string='PLM Status',
        default='draft',
        required=True,
        index=True,
        tracking=True,
    )
    x_revision = fields.Char(
        string='Revision',
        default='A.0',
        required=True,
        tracking=True,
    )
    x_previous_bom_id = fields.Many2one(
        'mrp.bom',
        string='Previous Revision',
        check_company=True,
        copy=False,
    )
    x_source_engineering_bom_id = fields.Many2one(
        'mrp.bom',
        string='Source Engineering BoM',
        check_company=True,
        copy=False,
    )
    x_production_bom_ids = fields.One2many(
        'mrp.bom',
        'x_source_engineering_bom_id',
        string='Production BoMs',
    )
    x_production_bom_count = fields.Integer(
        string='Production BoM Count',
        compute='_compute_x_production_bom_count',
    )
    x_effective_date = fields.Datetime(
        string='Effective Date',
        copy=False,
        tracking=True,
    )
    x_expire_date = fields.Datetime(
        string='Expiration Date',
        copy=False,
        tracking=True,
    )
    x_released_by = fields.Many2one(
        'res.users',
        string='Released By',
        copy=False,
        readonly=True,
    )
    x_released_date = fields.Datetime(
        string='Released On',
        copy=False,
        readonly=True,
    )
    x_is_current_revision = fields.Boolean(
        string='Current Revision',
        compute='_compute_x_is_current_revision',
        search='_search_x_is_current_revision',
    )
    x_revision_count = fields.Integer(
        string='Revision Count',
        compute='_compute_x_revision_count',
    )
    x_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        check_company=True,
        index=True,
    )

    @api.depends_context('sn_wsd_revision_display')
    def _compute_display_name(self):
        super()._compute_display_name()
        if not self.env.context.get('sn_wsd_revision_display'):
            return
        for bom in self:
            bom.display_name = bom.x_revision or bom.code or str(bom.id)

    @api.depends('x_production_bom_ids')
    def _compute_x_production_bom_count(self):
        for bom in self:
            bom.x_production_bom_count = len(bom.x_production_bom_ids)

    def _compute_x_revision_count(self):
        for bom in self:
            bom.x_revision_count = self.with_context(active_test=False).search_count(
                bom._get_revision_family_domain()
            )

    def _compute_x_is_current_revision(self):
        for bom in self:
            if bom.x_plm_state != 'released':
                bom.x_is_current_revision = False
                continue
            domain = bom._get_revision_family_domain()
            domain &= Domain('id', '!=', bom.id)
            domain &= Domain('x_plm_state', '=', 'released')
            domain &= Domain('active', '=', True)
            bom.x_is_current_revision = not bool(self.search_count(domain, limit=1))

    def _search_x_is_current_revision(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        released_boms = self.search([('x_plm_state', '=', 'released'), ('active', '=', True)])
        current_boms = released_boms.filtered('x_is_current_revision')
        domain = [('id', 'in', current_boms.ids)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            domain = [('id', 'not in', current_boms.ids)]
        return domain

    def _get_revision_family_domain(self):
        self.ensure_one()
        domain = Domain('company_id', 'in', [False, self.company_id.id])
        domain &= Domain('product_tmpl_id', '=', self.product_tmpl_id.id)
        domain &= Domain('product_id', '=', self.product_id.id if self.product_id else False)
        domain &= Domain('type', '=', self.type)
        domain &= Domain('x_bom_stage_type', '=', self.x_bom_stage_type)
        if self.x_source_engineering_bom_id:
            domain &= Domain('x_source_engineering_bom_id', '=', self.x_source_engineering_bom_id.id)
        elif self.x_bom_stage_type == 'production':
            domain &= Domain('x_source_engineering_bom_id', '=', False)
        return domain

    @api.constrains('x_bom_stage_type', 'x_source_engineering_bom_id')
    def _check_x_source_engineering_bom_id(self):
        for bom in self:
            if bom.x_bom_stage_type == 'engineering' and bom.x_source_engineering_bom_id:
                raise ValidationError(_('Engineering BoMs cannot reference a source engineering BoM.'))
            if bom.x_source_engineering_bom_id and bom.x_source_engineering_bom_id.x_bom_stage_type != 'engineering':
                raise ValidationError(_('The source BoM must be an engineering BoM.'))

    @api.constrains('x_process_route_id', 'company_id', 'x_bom_stage_type')
    def _check_process_route_scope(self):
        for bom in self:
            if not bom.x_process_route_id:
                continue
            route = bom.x_process_route_id
            if route.company_id != bom.company_id:
                raise ValidationError(_('The process route must belong to the same company as the bill of material.'))

    @api.constrains('x_effective_date', 'x_expire_date')
    def _check_x_effective_dates(self):
        for bom in self:
            if bom.x_effective_date and bom.x_expire_date and bom.x_effective_date >= bom.x_expire_date:
                raise ValidationError(_('The effective date must be earlier than the expiration date.'))

    def write(self, vals):
        if not self.env.context.get('allow_plm_locked_write') and BOM_LOCKED_FIELDS.intersection(vals):
            locked = self.filtered(lambda bom: bom.x_plm_state in ('released', 'obsolete'))
            if locked:
                raise UserError(_('Released or obsolete BoMs cannot be changed directly. Create a new revision instead.'))
        return super().write(vals)

    def action_submit_review(self):
        self.filtered(lambda bom: bom.x_plm_state == 'draft').write({'x_plm_state': 'review'})
        return True

    def _get_next_revision(self):
        self.ensure_one()
        revision = self.x_revision or 'A.0'
        if '.' in revision:
            prefix, suffix = revision.rsplit('.', 1)
            if suffix.isdigit():
                return f'{prefix}.{int(suffix) + 1}'
        return f'{revision}.1'

    def action_reset_draft(self):
        self.filtered(lambda bom: bom.x_plm_state in ('review', 'cancelled')).write({'x_plm_state': 'draft'})
        return True

    def action_cancel_plm(self):
        self.filtered(lambda bom: bom.x_plm_state in ('draft', 'review')).write({'x_plm_state': 'cancelled'})
        return True

    def action_release_plm(self):
        for bom in self:
            if bom.x_bom_stage_type == 'production' and not bom.x_process_route_id:
                raise UserError(_('A production BoM must have a process route before release.'))
            previous_revisions = self.search(bom._get_revision_family_domain() & Domain('id', '!=', bom.id) & Domain('x_plm_state', '=', 'released'))
            previous_revisions.with_context(allow_plm_locked_write=True).write({
                'x_plm_state': 'obsolete',
                'active': False,
                'x_expire_date': fields.Datetime.now(),
            })
            bom.with_context(allow_plm_locked_write=True).write({
                'x_plm_state': 'released',
                'active': True,
                'x_released_by': self.env.user.id,
                'x_released_date': fields.Datetime.now(),
            })
        return True

    def action_create_new_revision(self):
        self.ensure_one()
        if self.x_plm_state == 'cancelled':
            raise UserError(_('Cancelled BoMs cannot be copied into a new revision.'))
        if self.x_bom_stage_type == 'production' and self.x_process_route_id and self.x_process_route_id.x_plm_state == 'released':
            raise UserError(_('A new revision can only be created when the linked process route is not released. Release a new revision of the route first.'))
        new_bom = self.copy(default={
            'x_plm_state': 'draft',
            'x_revision': self._get_next_revision(),
            'x_previous_bom_id': self.id,
            'x_released_by': False,
            'x_released_date': False,
            'x_effective_date': False,
            'x_expire_date': False,
            'active': True,
        })
        if new_bom.x_bom_stage_type == 'production' and new_bom.x_process_route_id:
            new_bom._sync_process_route_operations()
        return {
            'type': 'ir.actions.act_window',
            'name': _('BoM Revision'),
            'res_model': 'mrp.bom',
            'res_id': new_bom.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_compare_revisions(self):
        self.ensure_one()
        available_boms = self.with_context(active_test=False).search(
            self._get_revision_family_domain(),
            order='create_date desc, id desc',
        )
        base_bom = self.x_previous_bom_id
        if not base_bom:
            base_bom = (available_boms - self)[:1]
        if not base_bom:
            raise UserError(_('No other revision is available for comparison.'))
        wizard = self.env['sn.wsd.bom.version.compare.wizard'].create({
            'base_bom_id': base_bom.id,
            'target_bom_id': self.id,
        })
        wizard._rebuild_comparison()
        return {
            'type': 'ir.actions.act_window',
            'name': _('BoM Version Comparison'),
            'res_model': 'sn.wsd.bom.version.compare.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_create_production_bom(self):
        self.ensure_one()
        if self.x_bom_stage_type != 'engineering':
            raise UserError(_('Production BoMs can only be generated from engineering BoMs.'))
        if self.x_plm_state not in ('review', 'released'):
            raise UserError(_('Submit or release the engineering BoM before generating a production BoM.'))
        new_bom = self.copy(default={
            'x_bom_stage_type': 'production',
            'x_plm_state': 'draft',
            'x_source_engineering_bom_id': self.id,
            'x_previous_bom_id': False,
            'x_released_by': False,
            'x_released_date': False,
            'x_effective_date': False,
            'x_expire_date': False,
            'active': True,
        })
        if new_bom.x_process_route_id:
            new_bom._sync_process_route_operations()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production BoM'),
            'res_model': 'mrp.bom',
            'res_id': new_bom.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_open_production_boms(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Production BoMs'),
            'res_model': 'mrp.bom',
            'view_mode': 'list,form',
            'domain': [('x_source_engineering_bom_id', '=', self.id)],
            'context': {
                'default_x_bom_stage_type': 'production',
                'default_x_source_engineering_bom_id': self.id,
                'default_product_tmpl_id': self.product_tmpl_id.id,
                'default_product_id': self.product_id.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_open_substitute_design(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Substitute Design'),
            'res_model': 'sn.wsd.bom.substitute.design.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_bom_id': self.id},
        }

    @api.model
    def _bom_find_domain(self, products, picking_type=None, company_id=False, bom_type=False):
        domain = super()._bom_find_domain(products, picking_type=picking_type, company_id=company_id, bom_type=bom_type)
        domain &= Domain('x_bom_stage_type', '=', 'production')
        domain &= Domain('x_plm_state', '=', 'released')
        return domain


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    x_substitution_role = fields.Selection(
        [
            ('none', 'None'),
            ('original', 'Original Material'),
            ('substitute', 'Substitute Material'),
        ],
        string='Substitution Role',
        default='none',
        required=True,
        copy=True,
        index=True,
    )
    x_substitution_origin_line_id = fields.Many2one(
        'mrp.bom.line',
        string='Original BoM Line',
        check_company=True,
        copy=False,
        ondelete='set null',
    )
    x_substitution_substitute_line_ids = fields.One2many(
        'mrp.bom.line',
        'x_substitution_origin_line_id',
        string='Substitute Lines',
    )
    x_substitution_original_product_id = fields.Many2one(
        'product.product',
        string='Original Material',
        check_company=True,
        copy=True,
    )
    x_substitution_substitute_product_id = fields.Many2one(
        'product.product',
        string='Substitute Material',
        check_company=True,
        copy=True,
    )
    x_substitution_qty = fields.Float(
        string='Substitution Qty',
        digits='Product Unit',
        copy=True,
    )
    x_substitution_note = fields.Char(
        string='Substitution Note',
        compute='_compute_x_substitution_note',
    )

    @api.depends(
        'x_substitution_role',
        'x_substitution_origin_line_id.product_id.display_name',
        'x_substitution_origin_line_id.x_substitution_substitute_line_ids.product_id.display_name',
        'x_substitution_origin_line_id.x_substitution_substitute_line_ids.x_substitution_qty',
        'x_substitution_substitute_line_ids.product_id.display_name',
        'x_substitution_substitute_line_ids.x_substitution_qty',
        'x_substitution_original_product_id.display_name',
        'x_substitution_substitute_product_id.display_name',
        'x_substitution_qty',
    )
    def _compute_x_substitution_note(self):
        for line in self:
            if line.x_substitution_role == 'original':
                parts = [
                    _('%(product)s x %(qty)s', product=sub_line.product_id.display_name, qty=sub_line.x_substitution_qty)
                    for sub_line in line.x_substitution_substitute_line_ids
                ]
                line.x_substitution_note = _('Substituted by %(items)s', items=', '.join(parts)) if parts else False
            elif line.x_substitution_role == 'substitute':
                original = line.x_substitution_original_product_id or line.x_substitution_origin_line_id.product_id
                line.x_substitution_note = _('Substitute for %(product)s x %(qty)s', product=original.display_name, qty=line.x_substitution_qty) if original else False
            else:
                line.x_substitution_note = False

    def write(self, vals):
        if not self.env.context.get('allow_plm_locked_write') and BOM_LINE_LOCKED_FIELDS.intersection(vals):
            locked = self.filtered(lambda line: line.bom_id.x_plm_state in ('released', 'obsolete'))
            if locked:
                raise UserError(_('Released or obsolete BoM lines cannot be changed directly. Create a new revision instead.'))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        bom_ids = {vals.get('bom_id') for vals in vals_list if vals.get('bom_id')}
        locked_boms = self.env['mrp.bom'].browse(bom_ids).filtered(lambda bom: bom.x_plm_state in ('released', 'obsolete'))
        if locked_boms and not self.env.context.get('allow_plm_locked_write'):
            raise UserError(_('Released or obsolete BoMs cannot receive new lines directly. Create a new revision instead.'))
        return super().create(vals_list)

    def unlink(self):
        locked = self.filtered(lambda line: line.bom_id.x_plm_state in ('released', 'obsolete'))
        if locked and not self.env.context.get('allow_plm_locked_write'):
            raise UserError(_('Released or obsolete BoM lines cannot be deleted directly. Create a new revision instead.'))
        return super().unlink()

    def action_open_substitute_design(self):
        self.ensure_one()
        if self.bom_id.x_bom_stage_type != 'engineering':
            raise UserError(_('Substitute design is only available on engineering BoMs.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Substitute Design'),
            'res_model': 'sn.wsd.bom.substitute.design.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bom_id': self.bom_id.id,
                'default_bom_line_id': self.id,
                'default_product_id': self.product_id.id,
            },
        }

    def action_open_apply_substitute(self):
        self.ensure_one()
        if self.bom_id.x_bom_stage_type != 'production':
            raise UserError(_('Substitutes can only be applied on production BoMs.'))
        if self.bom_id.x_plm_state in ('released', 'obsolete'):
            raise UserError(_('Released or obsolete production BoMs cannot be changed directly. Create a new revision instead.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Apply Substitute'),
            'res_model': 'sn.wsd.bom.apply.substitute.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bom_line_id': self.id,
                'default_bom_id': self.bom_id.id,
                'default_original_product_id': self.product_id.id,
                'default_original_qty': self.product_qty,
                'default_product_uom_id': self.product_uom_id.id,
                'default_operation_id': self.operation_id.id,
            },
        }

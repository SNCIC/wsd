from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Command

KNOWLEDGE_TYPE_SELECTION = [
    ('case', 'Fault Case'),
    ('sop', 'Standard Operating Procedure'),
    ('tip', 'Repair Tip'),
    ('faq', 'FAQ'),
]


class Knowledge(models.Model):
    """Equipment knowledge base: fault cases, SOPs, repair tips and FAQs
    distilled from daily maintenance work."""
    _name = 'sn.wsd.device.knowledge'
    _description = 'Equipment Knowledge'
    _order = 'id desc'
    _rec_name = 'name'

    kb_code = fields.Char(
        string='Knowledge Reference', default='/', copy=False,
        readonly=True, index=True)
    name = fields.Char(string='Knowledge Title', required=True)
    knowledge_type = fields.Selection(
        selection=KNOWLEDGE_TYPE_SELECTION, string='Knowledge Type',
        required=True, index=True)
    equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Equipment', index=True,
        ondelete='set null')
    equipment_code = fields.Char(
        related='equipment_id.code', store=True, string='Equipment Code')
    equipment_type_id = fields.Many2one(
        'sn.wsd.device.equipment.type', string='Applicable Equipment Type',
        index=True)
    repair_order_id = fields.Many2one(
        'sn.wsd.device.repair.order', string='Source Repair Order',
        index=True, ondelete='set null',
        help='Set when the knowledge is distilled from a repair order.')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    summary = fields.Char(string='Summary')
    content = fields.Html(string='Content', required=True)

    # ===== fault case fields =====
    fault_phenomenon = fields.Html(string='Fault Phenomenon')
    fault_cause = fields.Html(string='Fault Cause')
    solution = fields.Html(string='Solution')
    preventive_measures = fields.Html(string='Preventive Measures')

    # ===== SOP fields =====
    sop_step_ids = fields.One2many(
        'sn.wsd.device.knowledge.step', 'knowledge_id', string='SOP Steps')
    sop_tools = fields.Char(string='Required Tools')
    sop_spare_parts = fields.Char(string='Required Spare Parts')
    sop_safety_notes = fields.Html(string='Safety Notes')

    # ===== repair tip fields =====
    tip_scenario = fields.Char(string='Applicable Scenario')

    # ===== FAQ fields =====
    faq_answer = fields.Html(string='Answer')

    # ===== statistics =====
    view_count = fields.Integer(
        string='Views', readonly=True, copy=False, default=0)
    like_user_ids = fields.Many2many(
        'res.users', string='Liked By', copy=False,
        help='Each user can like a knowledge entry at most once.')
    favorite_user_ids = fields.Many2many(
        'res.users', 'sn_wsd_device_knowledge_favorite_rel',
        string='Favorited By', copy=False,
        help='Each user can favorite a knowledge entry at most once.')
    like_count = fields.Integer(string='Likes', compute='_compute_counts')
    favorite_count = fields.Integer(
        string='Favorites', compute='_compute_counts')
    liked_by_me = fields.Boolean(compute='_compute_counts')
    favorited_by_me = fields.Boolean(compute='_compute_counts')

    # ===== versioning =====
    version = fields.Char(string='Version', default='1.0', required=True)
    parent_id = fields.Many2one(
        'sn.wsd.device.knowledge', string='Parent Knowledge',
        index=True, ondelete='set null')
    note = fields.Char(string='Notes')

    @api.depends('like_user_ids', 'favorite_user_ids')
    def _compute_counts(self):
        for knowledge in self:
            knowledge.like_count = len(knowledge.like_user_ids)
            knowledge.favorite_count = len(knowledge.favorite_user_ids)
            knowledge.liked_by_me = self.env.user in knowledge.like_user_ids
            knowledge.favorited_by_me = \
                self.env.user in knowledge.favorite_user_ids

    @api.constrains(
        'knowledge_type', 'fault_phenomenon', 'fault_cause', 'solution')
    def _check_case_fields(self):
        for knowledge in self:
            if knowledge.knowledge_type != 'case':
                continue
            if not knowledge.fault_phenomenon \
                    or not knowledge.fault_cause or not knowledge.solution:
                raise ValidationError(_(
                    'Fault case knowledge requires the fault phenomenon, '
                    'the fault cause and the solution.'))

    @api.constrains('knowledge_type', 'sop_step_ids')
    def _check_sop_steps(self):
        for knowledge in self:
            if knowledge.knowledge_type == 'sop' \
                    and not knowledge.sop_step_ids:
                raise ValidationError(_(
                    'Standard operating procedure knowledge requires at '
                    'least one step.'))

    @api.constrains('knowledge_type', 'faq_answer')
    def _check_faq_answer(self):
        for knowledge in self:
            if knowledge.knowledge_type == 'faq' \
                    and not knowledge.faq_answer:
                raise ValidationError(_(
                    'FAQ knowledge requires the answer.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('kb_code') or vals.get('kb_code') == '/':
                vals['kb_code'] = self.env['ir.sequence'].next_by_code(
                    'sn.wsd.device.knowledge') or '/'
        return super().create(vals_list)

    def web_read(self, specification):
        """Count one view per detail open (the web client loads form
        records through this method)."""
        result = super().web_read(specification)
        if self.ids and not self.env.context.get('knowledge_skip_view_count'):
            self.env.cr.execute(
                "UPDATE sn_wsd_device_knowledge "
                "SET view_count = COALESCE(view_count, 0) + 1 "
                "WHERE id IN %s", [tuple(self.ids)])
            self.invalidate_recordset(['view_count'])
        return result

    def action_toggle_like(self):
        """Like or unlike: a user likes each entry at most once."""
        for knowledge in self:
            if self.env.user in knowledge.like_user_ids:
                knowledge.like_user_ids = [Command.unlink(self.env.user.id)]
            else:
                knowledge.like_user_ids = [Command.link(self.env.user.id)]
        return True

    def action_toggle_favorite(self):
        """Favorite or unfavorite: at most once per user."""
        for knowledge in self:
            if self.env.user in knowledge.favorite_user_ids:
                knowledge.favorite_user_ids = [
                    Command.unlink(self.env.user.id)]
            else:
                knowledge.favorite_user_ids = [
                    Command.link(self.env.user.id)]
        return True

    def action_new_version(self):
        """Copy the knowledge as a new minor version linked to this one."""
        self.ensure_one()
        try:
            major, minor = self.version.split('.')
            new_version = f'{major}.{int(minor) + 1}'
        except (ValueError, AttributeError):
            new_version = '1.1'
        new_knowledge = self.copy({
            'kb_code': '/',
            'name': self.name,
            'parent_id': self.id,
            'version': new_version,
            'view_count': 0,
            'like_user_ids': [Command.clear()],
            'favorite_user_ids': [Command.clear()],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Equipment Knowledge'),
            'res_model': self._name,
            'res_id': new_knowledge.id,
            'view_mode': 'form',
            'target': 'current',
        }


class KnowledgeStep(models.Model):
    """One step of a standard operating procedure."""
    _name = 'sn.wsd.device.knowledge.step'
    _description = 'Equipment Knowledge SOP Step'
    _order = 'sequence, id'

    knowledge_id = fields.Many2one(
        'sn.wsd.device.knowledge', string='Knowledge',
        required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Step Description', required=True)
    image = fields.Image(string='Step Image', max_width=1920, max_height=1920)

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    sn_shop_floor_employee_ids = fields.Many2many(
        'hr.employee',
        'sn_wsd_workcenter_employee_rel',
        'workcenter_id',
        'employee_id',
        string='Shop Floor Employees',
        help='If empty, every employee from the active companies can work on this work center.',
    )
    sn_shop_floor_enabled = fields.Boolean(string='Show on Shop Floor', default=True)
    sn_employee_costs_hour = fields.Monetary(
        string='Employee Hourly Cost',
        currency_field='currency_id',
        default=0.0,
    )

    @api.model
    def sn_get_employee_by_barcode(self, barcode):
        return self.env['hr.employee'].sudo().search([('barcode', '=', barcode)], limit=1).id

    def action_work_order(self):
        if (
            self.env.user.has_group('sn_wsd_workorder.group_sn_wsd_shop_floor_user')
            and not self.env.context.get('desktop_list_view')
        ):
            action = self.env['ir.actions.actions']._for_xml_id('sn_wsd_workorder.action_sn_wsd_shop_floor')
            context = action.get('context') or {}
            if isinstance(context, str):
                context = safe_eval(context)
            action['context'] = dict(context, workcenter_id=self.id)
            return action
        return super().action_work_order()

    @api.model
    def sn_shop_floor_set_blocked(self, workcenter_id, blocked=True, description=False):
        workcenter = self.browse(workcenter_id).exists()
        if not workcenter:
            raise UserError(_('The work center no longer exists.'))
        if not blocked:
            if workcenter.working_state == 'blocked':
                workcenter.unblock()
            return True

        if workcenter.working_state == 'blocked':
            return True
        workcenter.order_ids.filtered(lambda workorder: workorder.state == 'progress').sn_shop_floor_pause()
        loss = self.env['mrp.workcenter.productivity.loss'].search([
            ('manual', '=', True),
            ('loss_type', '=', 'availability'),
        ], limit=1)
        if not loss:
            loss_type = self.env['mrp.workcenter.productivity.loss.type'].search([
                ('loss_type', '=', 'availability'),
            ], limit=1)
            if not loss_type:
                raise UserError(_('Define an availability productivity loss category before blocking a work center.'))
            loss = self.env['mrp.workcenter.productivity.loss'].create({
                'name': _('Manual Block'),
                'manual': True,
                'loss_id': loss_type.id,
            })
        self.env['mrp.workcenter.productivity'].create({
            'workcenter_id': workcenter.id,
            'company_id': workcenter.company_id.id or self.env.company.id,
            'loss_id': loss.id,
            'description': description or _('Blocked from shop floor.'),
            'date_start': fields.Datetime.now(),
        })
        return True


class MrpWorkcenterProductivity(models.Model):
    _inherit = 'mrp.workcenter.productivity'

    employee_id = fields.Many2one('hr.employee', string='Employee', check_company=True)
    employee_cost = fields.Monetary(
        string='Employee Cost',
        compute='_compute_sn_employee_cost',
        store=True,
        currency_field='currency_id',
    )
    total_cost = fields.Float(string='Cost', compute='_compute_sn_total_cost')
    currency_id = fields.Many2one(related='company_id.currency_id')

    @api.depends('employee_id.hourly_cost', 'workcenter_id.sn_employee_costs_hour')
    def _compute_sn_employee_cost(self):
        for time in self:
            if time.employee_id and time.employee_id.hourly_cost:
                time.employee_cost = time.employee_id.hourly_cost
            else:
                time.employee_cost = time.workcenter_id.sn_employee_costs_hour

    @api.depends('duration', 'employee_cost')
    def _compute_sn_total_cost(self):
        for time in self:
            time.total_cost = time.employee_cost * time.duration / 60.0

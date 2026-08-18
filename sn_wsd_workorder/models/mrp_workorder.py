import json

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    sn_employee_ids = fields.Many2many(
        'hr.employee',
        'sn_wsd_workorder_employee_rel',
        'workorder_id',
        'employee_id',
        string='Working Employees',
        copy=False,
    )
    sn_employee_assigned_ids = fields.Many2many(
        'hr.employee',
        'sn_wsd_workorder_employee_assigned_rel',
        'workorder_id',
        'employee_id',
        string='Assigned Employees',
        domain="[('company_id', 'in', allowed_company_ids)]",
    )
    sn_allowed_employee_ids = fields.Many2many(
        related='workcenter_id.sn_shop_floor_employee_ids',
        string='Allowed Employees',
    )
    sn_all_employees_allowed = fields.Boolean(compute='_compute_sn_all_employees_allowed')
    sn_employee_costs_hour = fields.Float(string='Employee Cost per Hour', default=0.0)

    @api.depends('sn_allowed_employee_ids')
    def _compute_sn_all_employees_allowed(self):
        for workorder in self:
            workorder.sn_all_employees_allowed = not bool(workorder.sn_allowed_employee_ids)

    def _sn_get_session_employee(self):
        return self.env.user.employee_id

    def _sn_check_employee_can_work(self, employee):
        if not employee:
            raise UserError(_('You need to log in before processing the work order.'))

    def button_start(self, raise_on_invalid_state=False):
        if self.env.context.get('sn_shop_floor'):
            employee = self._sn_get_session_employee()
            self._sn_check_employee_can_work(employee)
        result = super().button_start(raise_on_invalid_state=raise_on_invalid_state)
        if self.env.context.get('sn_shop_floor'):
            employee = self._sn_get_session_employee()
            for workorder in self.filtered(lambda wo: wo.state not in ('done', 'cancel')):
                workorder.sn_start_employee(employee)
        return result

    def _should_start_timer(self):
        if self.env.context.get('sn_shop_floor'):
            return False
        return super()._should_start_timer()

    def button_finish(self):
        if self.env.context.get('sn_shop_floor'):
            for workorder in self:
                workorder.sn_employee_costs_hour = workorder.workcenter_id.sn_employee_costs_hour
        return super().button_finish()

    def action_mark_as_done(self):
        return super().action_mark_as_done()

    def sn_start_employee(self, employee):
        self.ensure_one()
        if not employee:
            return
        if employee not in self.sn_employee_ids:
            self.sn_employee_ids = [Command.link(employee.id)]
        if employee not in self.sn_employee_assigned_ids:
            self.sn_employee_assigned_ids = [Command.link(employee.id)]
        open_line = self.time_ids.filtered(lambda line: line.employee_id == employee and not line.date_end)
        if not open_line and self.state not in ('done', 'cancel'):
            values = self._prepare_timeline_vals(self.duration, fields.Datetime.now())
            values['employee_id'] = employee.id
            values['description'] = _('Time Tracking: %(user)s', user=employee.name)
            self.env['mrp.workcenter.productivity'].create(values)

    def sn_stop_employees(self, employee_ids):
        self.sn_employee_ids = [Command.unlink(employee_id) for employee_id in employee_ids]
        self.env['mrp.workcenter.productivity'].search([
            ('employee_id', 'in', employee_ids),
            ('workorder_id', 'in', self.ids),
            ('date_end', '=', False),
        ])._close()
        return True

    def sn_shop_floor_pause(self):
        for workorder in self:
            employee = workorder._sn_get_session_employee()
            employee_ids = employee.ids if employee and employee in workorder.sn_employee_ids else []
            if not employee_ids:
                employee_ids = workorder.sn_employee_ids.ids
            if employee_ids:
                workorder.sn_stop_employees(employee_ids)
            if workorder.state == 'progress' and not workorder.sn_employee_ids:
                workorder.with_context(sn_shop_floor=False).button_pending()
                state = 'ready'
                if workorder.product_uom_id and workorder.product_uom_id.compare(workorder.qty_ready, 0) <= 0:
                    state = 'blocked'
                workorder.write({'state': state})
        return True

    def button_pending(self):
        if self.env.context.get('sn_shop_floor'):
            employee = self._sn_get_session_employee()
            if employee:
                self.sn_stop_employees(employee.ids)
        return super().button_pending()

    def end_all(self):
        self.sn_employee_ids = [Command.clear()]
        return super().end_all()

    def action_open_sn_shop_floor(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('sn_wsd_workorder.action_sn_wsd_shop_floor')
        context = action.get('context') or {}
        if isinstance(context, str):
            context = safe_eval(context)
        action['context'] = dict(context, workcenter_id=self.workcenter_id.id, workorder_id=self.id)
        return action

    @api.model
    def sn_shop_floor_get_data(self, context=None):
        context = context or {}
        employee = self.env.user.employee_id
        limit = int(self.env['ir.config_parameter'].sudo().get_param(
            'sn_wsd_workorder.shop_floor_maximum_card_count',
            80,
        ))
        domain = [
            ('state', 'in', ('blocked', 'ready', 'progress')),
            ('production_id.state', 'in', ('confirmed', 'progress', 'to_close')),
            ('company_id', 'in', self.env.companies.ids),
            ('workcenter_id.sn_shop_floor_enabled', '=', True),
        ]
        if employee:
            domain.append(('sn_employee_assigned_ids', 'in', employee.id))
        else:
            domain.append(('id', '=', False))
        if context.get('production_id'):
            domain.append(('production_id', '=', context['production_id']))
        if context.get('workorder_id'):
            domain.append(('id', '=', context['workorder_id']))
        workorders = self.search(domain, order='date_start asc, sequence asc, id asc', limit=limit)
        return {
            'operator': {
                'id': employee.id,
                'name': employee.name,
            } if employee else False,
            'workorders': [workorder._sn_shop_floor_payload() for workorder in workorders],
            'limit': limit,
        }

    @api.model
    def sn_shop_floor_execute(self, workorder_id, operation, payload=None):
        workorder = self.browse(workorder_id).exists()
        if not workorder:
            raise UserError(_('The work order no longer exists.'))
        payload = payload or {}
        workorder = workorder.with_context(sn_shop_floor=True)
        workorder._sn_check_employee_can_work(workorder._sn_get_session_employee())
        if operation == 'start':
            workorder.button_start()
        elif operation == 'pause':
            workorder.sn_shop_floor_pause()
        elif operation == 'done':
            workorder.action_mark_as_done()
        elif operation == 'register_quantity':
            workorder.sn_shop_floor_register_quantity(
                payload.get('quantity'),
                finish=payload.get('finish'),
            )
        elif operation == 'consume_material':
            workorder.sn_shop_floor_consume_material(
                payload.get('move_id'),
                payload.get('quantity'),
            )
        else:
            raise UserError(_('Unsupported shop floor operation.'))
        return self.sn_shop_floor_get_data(payload.get('context') or {})

    @api.model
    def sn_shop_floor_employee_action(self, operation, employee_id=False, pin=False):
        employee = self.env['hr.employee'].browse(employee_id).exists() if employee_id else self.env.user.employee_id
        if not employee:
            raise UserError(_('Employee not found.'))
        if operation == 'login':
            if not employee.sn_shop_floor_login(pin):
                raise UserError(_('Invalid PIN.'))
        elif operation == 'logout':
            employee.sn_shop_floor_logout(pin, unchecked=True)
            employee.sn_shop_floor_stop_all()
        elif operation == 'owner':
            employee.sn_shop_floor_set_session_owner()
        else:
            raise UserError(_('Unsupported employee operation.'))
        return self.env['hr.employee'].sn_shop_floor_get_all_employees()

    def sn_shop_floor_register_quantity(self, quantity, finish=False):
        for workorder in self:
            qty = float(quantity or 0.0)
            if workorder.product_uom_id.compare(qty, 0) <= 0:
                raise UserError(_('Enter a positive quantity to report.'))
            if workorder.product_id.tracking == 'serial' and workorder.product_uom_id.compare(qty, 1) > 0:
                raise UserError(_('Serial-tracked products can only be reported one unit at a time.'))
            remaining = workorder.qty_remaining or (workorder.qty_production - workorder.qty_produced)
            if workorder.product_uom_id.compare(qty, remaining) > 0:
                raise UserError(_('The reported quantity cannot exceed the remaining quantity.'))

            report = workorder.action_register_terminal_report(
                source_type='manual',
                report_type='complete',
                operator_code=self._sn_get_session_employee().name,
                qty_in=qty,
                qty_ok=qty,
                remark=_('Shop floor quantity report'),
                payload_json=json.dumps({
                    'source': 'sn_wsd_workorder_shop_floor',
                    'finish': bool(finish),
                }),
            )
            if finish:
                workorder.action_mark_as_done()
        return True

    def sn_shop_floor_consume_material(self, move_id, quantity):
        self.ensure_one()
        move = self.env['stock.move'].browse(move_id).exists()
        if not move:
            raise UserError(_('The component move no longer exists.'))
        valid_moves = self.move_raw_ids | self.production_id.move_raw_ids
        if move not in valid_moves:
            raise UserError(_('The component does not belong to this work order.'))
        if move.state in ('done', 'cancel'):
            raise UserError(_('You cannot update a done or cancelled component.'))
        qty = float(quantity or 0.0)
        if move.product_uom.compare(qty, 0) < 0:
            raise UserError(_('The consumed quantity cannot be negative.'))
        move.quantity = qty
        move.picked = move.product_uom.compare(qty, 0) > 0
        return True

    def _sn_shop_floor_payload(self):
        self.ensure_one()
        production = self.production_id
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'barcode': self.barcode,
            'state': self.state,
            'working_state': self.working_state,
            'workcenter': self._sn_workcenter_payload(self.workcenter_id),
            'production': {
                'id': production.id,
                'name': production.name,
                'state': production.state,
                'product': production.product_id.display_name,
                'qty': production.product_qty,
                'qty_producing': production.qty_producing,
                'uom': production.product_uom_id.display_name,
                'origin': production.origin,
                'priority': production.priority,
                'mes_order': production.x_mes_order_id.display_name if 'x_mes_order_id' in production._fields and production.x_mes_order_id else False,
            },
            'product': self.product_id.display_name,
            'operation_type': self.x_meter_operation_type if 'x_meter_operation_type' in self._fields else False,
            'qty_producing': self.qty_producing,
            'qty_remaining': self.qty_remaining,
            'qty_produced': self.qty_produced,
            'qty_ready': self.qty_ready,
            'uom': self.product_uom_id.display_name,
            'duration': self.duration,
            'duration_expected': self.duration_expected,
            'employee_ids': self.sn_employee_ids.ids,
            'assigned_employee_ids': self.sn_employee_assigned_ids.ids,
            'allowed_employee_ids': self.sn_allowed_employee_ids.ids,
            'all_employees_allowed': self.sn_all_employees_allowed,
            'can_correct_reports': self.env.user.has_group('mrp.group_mrp_manager'),
            'components': [self._sn_move_payload(move) for move in self.move_raw_ids.filtered(lambda move: move.state not in ('done', 'cancel'))],
        }

    @api.model
    def _sn_workcenter_payload(self, workcenter):
        if not workcenter:
            return False
        return {
            'id': workcenter.id,
            'name': workcenter.display_name,
            'code': workcenter.code,
            'working_state': workcenter.working_state,
            'workshop': {
                'id': workcenter.x_workshop_id.id,
                'name': workcenter.x_workshop_id.display_name,
            } if workcenter.x_workshop_id else False,
            'production_line': {
                'id': workcenter.x_production_line_id.id,
                'name': workcenter.x_production_line_id.display_name,
            } if workcenter.x_production_line_id else False,
        }

    @api.model
    def _sn_move_payload(self, move):
        return {
            'id': move.id,
            'product': move.product_id.display_name,
            'planned_qty': move.product_uom_qty,
            'done_qty': move.quantity,
            'uom': move.product_uom.display_name,
            'picked': move.picked,
        }


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def action_open_sn_shop_floor(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('sn_wsd_workorder.action_sn_wsd_shop_floor')
        context = action.get('context') or {}
        if isinstance(context, str):
            context = safe_eval(context)
        context = dict(context)
        context.update({
            'production_id': self.id,
            'workcenter_id': self.workorder_ids[:1].workcenter_id.id if self.workorder_ids else False,
        })
        action['context'] = context
        return action

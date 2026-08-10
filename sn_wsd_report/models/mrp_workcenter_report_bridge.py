from odoo import models


class MrpWorkcenter(models.Model):
    _inherit = 'mrp.workcenter'

    def action_open_station_scan_wizard(self):
        self.ensure_one()
        if not self.x_active_workorder_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Active Work Order',
                    'message': 'This work center has no ready or in-progress work order to execute.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        active_workorder = self.x_active_workorder_ids[:1]
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_terminal_client_action',
            'name': 'Terminal Report',
            'context': {
                'default_workcenter_id': self.id,
                'default_workorder_id': active_workorder.id,
                'default_mode': 'manual',
                'default_report_type': 'complete' if active_workorder.state == 'progress' else 'start',
                'default_operator_code': active_workorder.x_meter_operator_code,
                'default_device_id': active_workorder.x_meter_equipment_id.id,
                'default_qty_in': active_workorder._suggest_report_input_qty(),
            },
        }

    def action_route_latest_exception_to_repair(self):
        self.ensure_one()
        exception_event = self.env['sn.wsd.mes.sn.travel'].search(
            [
                ('workcenter_id', '=', self.id),
                ('result', 'in', ['fail', 'hold']),
            ],
            order='event_time desc, id desc',
            limit=1,
        )
        if not exception_event:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Exception Event',
                    'message': 'This work center has no recent exception event to route.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        repair_workcenter = self.search([
            ('company_id', '=', self.company_id.id),
            ('x_production_line_id', '=', self.x_production_line_id.id),
            ('routing_line_ids.x_station_type', '=', 'repair'),
            ('active', '=', True),
        ], order='sequence asc, id asc', limit=1)
        if not repair_workcenter:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Repair Work Center Missing',
                    'message': 'No active repair work center is configured on this line.',
                    'type': 'danger',
                    'sticky': False,
                },
            }
        repair_workorder = repair_workcenter.x_active_workorder_ids[:1]
        if not repair_workorder:
            repair_workorder = self.env['mrp.workorder'].search([
                ('workcenter_id', '=', repair_workcenter.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='id asc', limit=1)
        if not repair_workorder:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Repair Work Order Missing',
                    'message': 'The repair work center has no ready or in-progress work order.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        route_note = f'Reroute from {self.code} exception'
        if exception_event.note:
            route_note = f'{route_note}: {exception_event.note}'
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_terminal_client_action',
            'name': 'Route To Repair',
            'context': {
                'default_workcenter_id': repair_workcenter.id,
                'default_workorder_id': repair_workorder.id,
                'default_mode': 'manual',
                'default_report_type': 'start',
                'default_serial_no': exception_event.internal_serial_id.serial_no,
                'default_operator_code': exception_event.operator_code,
                'default_remark': route_note,
                'default_qty_in': 1.0,
            },
        }

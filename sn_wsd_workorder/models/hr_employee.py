from datetime import datetime

from odoo import models
from odoo.http import request


EMPLOYEES_CONNECTED = 'sn_wsd_workorder_employees_connected'
SESSION_OWNER = 'sn_wsd_workorder_session_owner'


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def sn_shop_floor_pin_valid(self, pin=False):
        self.ensure_one()
        return self.sudo().pin == (pin or False)

    def sn_shop_floor_login(self, pin=False, set_in_session=True):
        self.ensure_one()
        if not self.sn_shop_floor_pin_valid(pin):
            return False
        if set_in_session and request:
            self._sn_shop_floor_connect()
            request.session[SESSION_OWNER] = self.id
        return True

    def sn_shop_floor_logout(self, pin=False, unchecked=False):
        self.ensure_one()
        if not request:
            return True
        connected = list(request.session.get(EMPLOYEES_CONNECTED, []))
        owner = request.session.get(SESSION_OWNER, False)
        if (unchecked or self.sn_shop_floor_pin_valid(pin)) and self.id in connected:
            connected.remove(self.id)
            request.session[EMPLOYEES_CONNECTED] = connected
            if owner == self.id:
                request.session[SESSION_OWNER] = connected[0] if connected else False
            return True
        return False

    def _sn_shop_floor_connect(self):
        self.ensure_one()
        if not request:
            return
        connected = list(request.session.get(EMPLOYEES_CONNECTED, []))
        if self.id in connected:
            connected.remove(self.id)
        request.session[EMPLOYEES_CONNECTED] = [self.id] + connected

    def sn_shop_floor_get_connected_ids(self):
        if request:
            return request.session.get(EMPLOYEES_CONNECTED, [])
        return [self.env.user.employee_id.id] if self.env.user.employee_id else []

    def sn_shop_floor_get_session_owner_id(self):
        if request:
            return request.session.get(SESSION_OWNER, False)
        return self.env.user.employee_id.id if self.env.user.employee_id else False

    def sn_shop_floor_get_all_employees(self, login=False):
        if login and self.env.user.employee_id and not self.sn_shop_floor_get_session_owner_id():
            self.env.user.employee_id.sn_shop_floor_login()
        domain = ['|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids)]
        employees = self.search(domain, order='name')
        connected_ids = [
            employee_id for employee_id in self.sn_shop_floor_get_connected_ids()
            if employee_id in employees.ids
        ]
        return {
            'owner_id': self.sn_shop_floor_get_session_owner_id(),
            'connected': self._sn_shop_floor_employee_payload(connected_ids),
            'all': [{'id': employee.id, 'name': employee.name} for employee in employees],
        }

    def _sn_shop_floor_employee_payload(self, employee_ids):
        result = [{'id': employee_id} for employee_id in employee_ids]
        if not result:
            return result
        workorders = self.env['mrp.workorder'].search([
            ('state', '=', 'progress'),
            ('sn_employee_ids', 'in', employee_ids),
        ])
        time_rows = self.env['mrp.workcenter.productivity']._read_group(
            [
                ('employee_id', 'in', employee_ids),
                ('workorder_id', 'in', workorders.ids),
            ],
            ['employee_id', 'workcenter_id'],
            ['duration:sum', 'date_end:array_agg', 'date_start:array_agg'],
        )
        for row in result:
            employee = self.browse(row['id'])
            row['name'] = employee.name
            row['workcenters'] = []
        for employee, workcenter, duration, end_dates, start_dates in time_rows:
            for end_date, start_date in zip(end_dates, start_dates):
                if not end_date and start_date:
                    duration += int((datetime.now() - start_date).total_seconds()) / 60
            row = next(item for item in result if item['id'] == employee.id)
            if any(not date for date in end_dates):
                row['workcenters'].append({
                    'id': workcenter.id,
                    'name': workcenter.name,
                    'duration': duration,
                    'ongoing': True,
                })
            elif end_dates:
                row['last_active'] = max(date for date in end_dates if date).isoformat()
        return result

    def sn_shop_floor_set_session_owner(self):
        self.ensure_one()
        if request:
            self._sn_shop_floor_connect()
            request.session[SESSION_OWNER] = self.id
        return self.sn_shop_floor_get_all_employees()

    def sn_shop_floor_stop_all(self):
        workorders = self.env['mrp.workorder'].search([
            ('state', '=', 'progress'),
            ('sn_employee_ids', 'in', self.ids),
        ])
        workorders.sn_stop_employees(self.ids)
        return True

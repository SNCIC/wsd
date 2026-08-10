from odoo import _, models


class MesApiMixin(models.AbstractModel):
    _name = 'sncic.mes.api.mixin'
    _description = 'MES API Helper Mixin'

    @staticmethod
    def _mes_ok(**payload):
        return {'ok': True, **payload}

    @staticmethod
    def _mes_error(code, message=None, **payload):
        return {
            'ok': False,
            'error': code,
            'message': message or code.replace('_', ' ').title(),
            **payload,
        }

    @staticmethod
    def _mes_user_error_message(code):
        mapping = {
            'station_not_found': _('Station not found.'),
            'station_not_mapped': _('The work order is not mapped to a MES station.'),
            'workorder_not_ready': _('The work order is not ready to start.'),
            'invalid_workorder_state': _('The work order state does not allow this operation.'),
            'serial_not_found': _('Serial number not found.'),
            'station_route_blocked': _('This serial cannot enter the current station according to the configured route.'),
            'serial_already_processed_on_station': _('This serial has already been processed on the current station.'),
        }
        return mapping.get(code, _(code.replace('_', ' ')))

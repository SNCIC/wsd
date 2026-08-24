from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SerialOperationHistory(models.Model):
    _inherit = 'sn.wsd.serial.operation.history'

    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='NG Defect Code',
        check_company=True,
        index=True,
        ondelete='restrict',
        help='Defect code scanned when the SN was rejected at this operation.',
    )


class MesOperationReport(models.Model):
    _inherit = 'sn.wsd.mes.operation.report'

    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='NG Defect Code',
        check_company=True,
        index=True,
        ondelete='restrict',
        help='Defect code recorded with the NG quantity (reserved for '
             'later use; the terminal does not fill it yet).',
    )


class MesOrder(models.Model):
    _inherit = 'sn.wsd.mes.order'

    def leave_station(self, serial_identity, result, scrap_reason=False,
                      ng_defect=False, operator_code=False):
        """NG passes must carry a defect code; it is stamped on the history
        row so the repair side knows what to fix."""
        if result == 'ng' and not ng_defect:
            raise ValidationError(_('Select a defect code.'))
        return super().leave_station(
            serial_identity, result, scrap_reason=scrap_reason,
            ng_defect=ng_defect, operator_code=operator_code)

    def _prepare_leave_history_vals(self, serial_identity, route_operation,
                                    wip, result, scrap_reason=False,
                                    ng_defect=False, operator_code=False):
        vals = super()._prepare_leave_history_vals(
            serial_identity, route_operation, wip, result,
            scrap_reason=scrap_reason, ng_defect=ng_defect,
            operator_code=operator_code)
        if result == 'ng' and ng_defect:
            vals['defect_code_id'] = ng_defect.id
        return vals

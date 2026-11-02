from odoo import fields, models
from odoo.exceptions import ValidationError


class MesOrderDevicePassGate(models.Model):
    """Device-domain station-pass gate (device-pass-gate change).

    One hook for every channel: when the caller carries an equipment code
    -- today only the device API (M_DEVICE_SN) does -- the equipment must
    exist in the ledger, be in use and (batch 2) not be overdue for spot
    checks / maintenance. Channels reporting no code skip the gate
    unchanged; a rejection rolls back the whole pass (one transaction).

    Lives in sn_wsd_mrp (the kernel's own module): sn_wsd_mrp already
    depends on sn_wsd_device, and the reverse dependency would be a cycle.
    The "what is wrong with this equipment" logic stays on the equipment
    model in sn_wsd_device (resolve_for_pass / _pass_gate_block_reason)."""
    _inherit = 'sn.wsd.mes.order'

    def pass_one_station(self, serial, workcenter, result='ok',
                         ng_defect=False, operator_code=False,
                         scrap_reason=False, equipment_code=False):
        self.ensure_one()
        if equipment_code:
            equipment = self.env[
                'sn.wsd.device.equipment'].resolve_for_pass(equipment_code)
            blocked = equipment._pass_gate_block_reason(fields.Datetime.now())
            if blocked:
                raise ValidationError(blocked)
        return super().pass_one_station(
            serial, workcenter, result=result, ng_defect=ng_defect,
            operator_code=operator_code, scrap_reason=scrap_reason,
            equipment_code=equipment_code)

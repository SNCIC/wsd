from odoo import api, models


class MesTestResult(models.Model):
    _inherit = 'sn.wsd.mes.test.result'

    def _wsd_sync_meter_archive(self):
        for record in self:
            if not record.internal_serial_id:
                continue
            archive = record.internal_serial_id
            vals = {
                'mes_order_id': record.mes_order_id.id or archive.mes_order_id.id,
                'current_route_operation_id': record.route_operation_id.id,
                'current_workcenter_id': record.workcenter_id.id,
                'production_id': record.production_id.id or archive.production_id.id,
            }
            if record.result == 'pass':
                if record.test_type in ('inspection', 'final_test', 'packaging'):
                    vals['final_result'] = 'pass'
            elif record.result == 'fail':
                vals['final_result'] = 'fail'
            if record.test_type == 'calibration':
                vals['final_verification_result'] = 'pass' if record.result == 'pass' else 'fail'
            if record.test_type == 'aging':
                vals['aging_result'] = 'pass' if record.result == 'pass' else 'fail'
            if record.test_type in ('inspection', 'final_test'):
                vals['verification_date'] = record.test_time
                vals['final_verification_result'] = 'pass' if record.result == 'pass' else 'fail'
            archive.write({k: v for k, v in vals.items() if v is not False})
            if archive.production_id:
                archive.production_id._update_meter_flow_state()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._wsd_sync_meter_archive()
        return records


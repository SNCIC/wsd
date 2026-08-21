from odoo import fields, models, _
from odoo.exceptions import UserError


class SnSmtZcWizard(models.TransientModel):
    _name = 'sn.smt.zc.wizard'
    _description = 'SMT Changeover Wizard'
    _inherit = 'sn.smt.operation.mixin'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    production_id = fields.Many2one('mrp.production', string='Current Manufacturing Order', required=True, check_company=True)
    target_production_id = fields.Many2one('mrp.production', string='Target Manufacturing Order', required=True, check_company=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', required=True, check_company=True)
    message = fields.Char(string='Message', readonly=True)

    def _check_substitute_compatibility(self, current_line, target_line):
        self.ensure_one()
        loaded_product = current_line.loaded_product_id
        if not loaded_product:
            return
        target_required = self.env['product.product'].search([
            ('default_code', '=', target_line.item_code),
        ], limit=1)
        if target_required and not self.target_production_id._is_allowed_substitute_product(target_required, loaded_product):
            raise UserError(_('Changeover aborted because the loaded substitute material is not compatible with the target manufacturing order.'))
        if not target_required and loaded_product.default_code != target_line.item_code:
            raise UserError(_('Changeover aborted because the loaded material is not compatible with the target manufacturing order.'))

    def _build_target_line_map(self, lines):
        return {
            (line.device_seq, line.table_no, line.loadpoint, line.item_code): line
            for line in lines
        }

    def action_changeover(self):
        self.ensure_one()
        if self.production_id == self.target_production_id:
            raise UserError(_('The target manufacturing order must be different from the current manufacturing order.'))
        if self.production_id.company_id != self.target_production_id.company_id:
            raise UserError(_('Changeover aborted.'))
        self._check_same_mes_order(self.production_id, self.target_production_id)
        if not self.target_production_id.x_smt_production_line_id:
            self.target_production_id.x_smt_production_line_id = self.production_id.x_smt_production_line_id
        if not self.target_production_id.x_smt_product_side:
            self.target_production_id.x_smt_product_side = self.production_id.x_smt_product_side
        if not self.target_production_id.x_production_line_id:
            self.target_production_id.x_production_line_id = self.target_production_id.x_smt_production_line_id
        if not self.target_production_id.x_workshop_id and self.target_production_id.x_smt_production_line_id:
            self.target_production_id.x_workshop_id = self.target_production_id.x_smt_production_line_id.workshop_id

        current_lines = self.production_id.x_smt_online_material_ids.filtered(lambda line: line.is_load == 'Y')
        if not current_lines:
            raise UserError(_('The current manufacturing order has no online materials.'))

        material_table = self.env['sn.smt.material.table']._match_for_production(self.target_production_id)
        if not material_table:
            raise UserError(_('No matching SMT material table was found for the target manufacturing order.'))
        self.target_production_id._validate_smt_material_table_scope(material_table)
        self.target_production_id._check_can_generate_smt_online_materials()

        self.production_id.x_smt_online_state = 'changeover'
        self.target_production_id.x_smt_online_material_ids.unlink()
        self.target_production_id.write({
            'x_smt_material_table_id': material_table.id,
            'x_smt_online_material_ids': [
                fields.Command.create(vals) for vals in material_table._prepare_online_material_vals(self.target_production_id)
            ],
            'x_smt_online_state': 'online',
        })

        target_lines = self.target_production_id.x_smt_online_material_ids
        target_line_map = self._build_target_line_map(target_lines)
        copied_records = self.env['sn.smt.operation.record']
        copied_traces = self.env['sn.smt.traceability']
        offline_material_model = self.env['sn.smt.offline.material']

        for current_line in current_lines:
            target_line = target_line_map.get((
                current_line.device_seq,
                current_line.table_no,
                current_line.loadpoint,
                current_line.item_code,
            ))
            if not target_line:
                continue
            self._check_substitute_compatibility(current_line, target_line)
            target_line.write({
                'is_load': 'Y',
                'is_qc_test': self._get_qc_flag(self.target_production_id),
                'loaded_material_lot_id': current_line.loaded_material_lot_id.id if current_line.loaded_material_lot_id else False,
                'loaded_feeder_id': current_line.loaded_feeder_id.id if current_line.loaded_feeder_id else False,
                'replace_count': current_line.replace_count,
            })
            if target_line.loaded_feeder_id:
                target_line.loaded_feeder_id.write({
                    'status': 'in_use',
                    'bound_production_id': self.target_production_id.id,
                })
            self._create_operation_bundle(
                self.target_production_id,
                online_material=target_line,
                operation_type='changeover_inherit',
                material_lot=target_line.loaded_material_lot_id if target_line.loaded_material_lot_id else False,
                feeder=target_line.loaded_feeder_id if target_line.loaded_feeder_id else False,
                is_online='Y',
                note='ZC',
            )
            old_records = self.env['sn.smt.operation.record'].search([
                ('production_id', '=', self.production_id.id),
                ('online_material_id', '=', current_line.id),
                ('is_online', '=', 'Y'),
            ])
            for record in old_records:
                copied_records |= record.copy({
                    'production_id': self.target_production_id.id,
                    'online_material_id': target_line.id,
                    'company_id': self.target_production_id.company_id.id,
                })
            old_traces = self.env['sn.smt.traceability'].search([
                ('production_id', '=', self.production_id.id),
                ('online_material_id', '=', current_line.id),
            ])
            for trace in old_traces:
                copied_traces |= trace.copy({
                    'production_id': self.target_production_id.id,
                    'online_material_id': target_line.id,
                    'company_id': self.target_production_id.company_id.id,
                })
            old_offline_records = offline_material_model.search([
                ('online_material_id', '=', current_line.id),
                ('is_online', '=', 'Y'),
            ])
            for offline_record in old_offline_records:
                duplicated = offline_material_model.search([
                    ('online_material_id', '=', target_line.id),
                    ('material_lot_id', '=', offline_record.material_lot_id.id),
                    ('feeder_id', '=', offline_record.feeder_id.id),
                    ('is_online', '=', 'Y'),
                ], limit=1)
                if not duplicated:
                    offline_record.copy({
                        'online_material_id': target_line.id,
                        'company_id': self.target_production_id.company_id.id,
                    })

        device_keys = {(line.device_seq, line.table_no) for line in current_lines}
        for device_seq, table_no in device_keys:
            clear_lines = current_lines.filtered(
                lambda line: line.device_seq == device_seq and line.table_no == table_no
            )
            self._finalize_unload_lines(
                self.production_id,
                clear_lines,
                unload_scope='changeover',
                clear_online_table=False,
            )

        self.production_id.x_smt_online_material_ids.unlink()
        self.production_id.x_smt_material_table_id = False
        self.production_id.x_smt_online_state = 'draft'
        # going offline is a MES-order concern (制令单 x_online_date); the
        # MO no longer carries an online stage
        self.production_id.x_mes_order_ids.filtered('x_online_date').action_offline()
        self._sync_production_after_smt_change(self.target_production_id)
        self.message = _('Changeover completed.')
        return {'type': 'ir.actions.act_window_close'}

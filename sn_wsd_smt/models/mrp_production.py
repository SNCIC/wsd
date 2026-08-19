from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_smt_production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='SMT Production Line',
        check_company=True,
        tracking=True,
    )
    x_smt_product_side = fields.Selection(
        [
            ('top', 'T Side'),
            ('bottom', 'B Side'),
            ('single', 'Single Side'),
        ],
        string='SMT Product Side',
        tracking=True,
    )
    x_smt_model_ver = fields.Char(string='SMT Model Version')
    x_smt_online_state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('online', 'Online'),
            ('changeover', 'Changeover'),
        ],
        string='SMT Online State',
        default='draft',
        tracking=True,
    )
    x_smt_material_table_id = fields.Many2one(
        'sn.smt.material.table',
        string='SMT Material Table',
        copy=False,
        check_company=True,
        tracking=True,
    )
    x_smt_online_material_ids = fields.One2many(
        'sn.smt.online.material',
        'production_id',
        string='SMT Online Materials',
    )
    x_smt_offline_material_ids = fields.One2many(
        'sn.smt.offline.material',
        'production_id',
        string='SMT Offline Materials',
    )
    x_smt_online_material_count = fields.Integer(
        string='SMT Online Material Count',
        compute='_compute_x_smt_online_material_count',
    )
    x_smt_consumption_count = fields.Integer(
        string='SMT Consumption Count', compute='_compute_x_smt_consumption_summary',
    )
    x_smt_consumed_points = fields.Float(
        string='SMT Consumed Points', compute='_compute_x_smt_consumption_summary',
    )

    @api.depends('x_smt_online_material_ids')
    def _compute_x_smt_online_material_count(self):
        for production in self:
            production.x_smt_online_material_count = len(production.x_smt_online_material_ids)

    @api.depends('x_smt_online_material_ids.consumption_ids.consumed_qty')
    def _compute_x_smt_consumption_summary(self):
        consumption_model = self.env['sn.smt.material.consumption']
        for production in self:
            records = consumption_model.search([('production_id', '=', production.id)])
            production.x_smt_consumption_count = len(records)
            production.x_smt_consumed_points = sum(records.mapped('consumed_qty'))

    def action_open_smt_consumption(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SMT Material Consumption'),
            'res_model': 'sn.smt.material.consumption',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
        }

    def _smt_consumption_reconciliation_snapshot(self):
        self.ensure_one()
        consumption_model = self.env['sn.smt.material.consumption']
        records = consumption_model.search([('production_id', '=', self.id)])
        consumed_by_product = {}
        for record in records:
            key = record.actual_item_code or record.required_item_code or '-'
            consumed_by_product[key] = consumed_by_product.get(key, 0.0) + record.consumed_qty
        issued_by_product = {
            move.product_id.default_code or move.product_id.display_name: move.quantity
            for move in self.move_raw_ids.filtered(lambda item: item.state != 'cancel')
        }
        return {
            'production_id': self.id,
            'production_name': self.name,
            'smt_consumption_count': len(records),
            'smt_consumed_points': sum(records.mapped('consumed_qty')),
            'consumed_by_product': consumed_by_product,
            'issued_by_product': issued_by_product,
        }

    def action_check_smt_consumption_reconciliation(self):
        self.ensure_one()
        snapshot = self._smt_consumption_reconciliation_snapshot()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('SMT Consumption Reconciliation'),
                'message': _(
                    'Product-SN consumption records: %(count)s; consumed points: %(points)s.',
                    count=snapshot['smt_consumption_count'],
                    points=snapshot['smt_consumed_points'],
                ),
                'type': 'info',
                'sticky': False,
            },
        }

    def _validate_smt_material_table_scope(self, material_table):
        self.ensure_one()
        table_item_codes = {
            code
            for code in material_table.detail_ids.mapped('item_code')
            if code
        }
        if not table_item_codes:
            return
        bom_item_codes = {
            code
            for code in self.move_raw_ids.filtered(lambda move: move.state != 'cancel').mapped('product_id.default_code')
            if code
        }
        extra_codes = sorted(table_item_codes - bom_item_codes)
        if extra_codes:
            raise ValidationError(_(
                'The SMT material table contains items that are not in the manufacturing order BOM: %s'
            ) % ', '.join(extra_codes))

    def _check_can_generate_smt_online_materials(self):
        self.ensure_one()
        if self.x_smt_online_state == 'online' and self.x_smt_online_material_ids:
            raise ValidationError(_(
                'The manufacturing order is already online. Use SMT unload, changeover, or material change operations instead.'
            ))
        protected_lines = self.x_smt_online_material_ids.filtered(
            lambda line: line.loaded_material_lot_id or line.offline_material_ids
        )
        if protected_lines:
            raise ValidationError(_(
                'SMT online materials cannot be regenerated after offline preparation or online loading has started.'
            ))
        existing_operations = self.env['sn.smt.operation.record'].search_count([
            ('production_id', '=', self.id),
            ('operation_type', 'in', [
                'offline_prepare',
                'online_load',
                'cart_load',
                'change',
                'continue',
                'changeover_inherit',
            ]),
        ], limit=1)
        if existing_operations:
            raise ValidationError(_(
                'SMT online materials cannot be regenerated because SMT operation records already exist.'
            ))

    def _get_smt_route_operation_for_feeder_lines(self):
        self.ensure_one()
        return self.x_mes_order_id.x_route_operation_ids.filtered(
            lambda operation: operation.operation_id.x_station_type == 'smt'
        )[:1]

    def _prepare_smt_feeder_line_values(self, online_material, sequence):
        self.ensure_one()
        product = self.env['product.product'].search([
            ('default_code', '=', online_material.item_code),
        ], limit=1)
        if not product:
            return False
        route_operation = self._get_smt_route_operation_for_feeder_lines()
        if not route_operation:
            return False
        source_move = self._find_matching_raw_moves(product)[:1]
        return {
            'online_material_id': online_material.id,
            'route_operation_id': route_operation.id,
            'production_id': self.id,
            'feeder_no': online_material.loadpoint or f'F{sequence:02d}',
            'device_seq': online_material.device_seq,
            'table_no': online_material.table_no,
            'loadpoint': online_material.loadpoint,
            'chanel_sn': online_material.chanel_sn,
            'feeder_spec': online_material.feeder_spec,
            'is_tray': online_material.is_tray,
            'expected_product_id': product.id,
            'source_move_id': source_move.id if source_move else False,
            'expected_qty': online_material.point_qty or source_move.product_uom_qty or 1.0,
            'state': 'pending',
        }

    def _generate_smt_feeder_lines_from_online_materials(self):
        for production in self:
            route_operation = production._get_smt_route_operation_for_feeder_lines()
            if not route_operation:
                continue
            active_lines = production.x_smt_online_material_ids.filtered(lambda line: line.is_skip != 'Y')
            protected_lines = production.feeder_line_ids.filtered(
                lambda line: line.state not in ('pending', 'returned')
            )
            if protected_lines:
                raise ValidationError(_(
                    'SMT feeder lines cannot be regenerated after feeder verification has started.'
                ))
            production.feeder_line_ids.filtered(lambda line: line.state == 'pending').unlink()
            commands = []
            for sequence, online_material in enumerate(
                active_lines.sorted(lambda line: (line.device_seq, line.table_no, line.loadpoint, line.id)),
                start=1,
            ):
                values = production._prepare_smt_feeder_line_values(online_material, sequence)
                if values:
                    commands.append(fields.Command.create(values))
            if commands:
                production.write({'feeder_line_ids': commands})

    def _prepare_smt_online_materials(self):
        """Generate the SMT online snapshot without changing the generic MO state."""
        self.ensure_one()
        production = self
        if production.x_smt_online_state == 'online' and production.x_smt_online_material_ids:
            return production.x_smt_online_material_ids
        if not production.x_smt_production_line_id:
            raise ValidationError(_('Please set the SMT production line first.'))
        if not production.x_smt_product_side:
            raise ValidationError(_('Please set the SMT product side first.'))
        if not production.x_production_line_id:
            production.x_production_line_id = production.x_smt_production_line_id
        if not production.x_workshop_id:
            production.x_workshop_id = production.x_smt_production_line_id.workshop_id
        material_table = self.env['sn.smt.material.table']._match_for_production(production)
        if not material_table:
            raise ValidationError(_('No matching SMT material table was found for the manufacturing order.'))
        production._validate_smt_material_table_scope(material_table)
        production._check_can_generate_smt_online_materials()
        production.x_smt_online_material_ids.unlink()
        production.write({
            'x_smt_material_table_id': material_table.id,
            'x_smt_online_material_ids': [
                fields.Command.create(vals) for vals in material_table._prepare_online_material_vals(production)
            ],
            'x_smt_online_state': 'prepared',
        })
        production._generate_smt_feeder_lines_from_online_materials()
        return production.x_smt_online_material_ids

    def action_smt_online(self):
        for production in self:
            if not production.x_smt_production_line_id:
                raise ValidationError(_('Please set the SMT production line first.'))
            if not production.x_smt_product_side:
                raise ValidationError(_('Please set the SMT product side first.'))
            if not production.x_workshop_id:
                production.x_workshop_id = production.x_smt_production_line_id.workshop_id
            # Online is carried by the MES orders (制令单): the SMT online
            # materials are prepared by the sn.wsd.mes.order online hook.
            production._action_online_mes_orders()
        return True

    def action_open_smt_online_materials(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SMT Online Materials'),
            'res_model': 'sn.smt.online.material',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }

    def _open_smt_wizard(self, xmlid):
        self.ensure_one()
        view = self.env.ref(xmlid)
        return {
            'type': 'ir.actions.act_window',
            'target': 'new',
            'res_model': view.model,
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'context': {'default_production_id': self.id},
        }

    def action_open_smt_bl_wizard(self):
        return self._open_smt_wizard('sn_wsd_smt.view_sn_smt_bl_wizard_form')

    def action_open_smt_tp_wizard(self):
        return self._open_smt_wizard('sn_wsd_smt.view_sn_smt_tp_wizard_form')

    def action_open_smt_material_query_wizard(self):
        return self._open_smt_wizard('sn_wsd_smt.view_sn_smt_material_query_wizard_form')

    def action_open_smt_lcsl_wizard(self):
        return self._open_smt_wizard('sn_wsd_smt.view_sn_smt_lcsl_wizard_form')

    def action_open_smt_xl_wizard(self):
        return self._open_smt_wizard('sn_wsd_smt.view_sn_smt_xl_wizard_form')

    def action_open_smt_zc_wizard(self):
        return self._open_smt_wizard('sn_wsd_smt.view_sn_smt_zc_wizard_form')

    def action_open_smt_change_wizard(self):
        return self._open_smt_wizard('sn_wsd_smt.view_sn_smt_change_wizard_form')


class MesOrderSmtOnline(models.Model):
    """Hook the SMT online-material preparation onto the MES-order (制令单)
    online flow: replacing the legacy MO-level online, the SMT table is now
    prepared when the MES order goes online."""

    _inherit = 'sn.wsd.mes.order'

    def action_online(self):
        smt_productions = self.mapped('production_id').filtered('x_has_smt_operations')
        if smt_productions:
            smt_productions._prepare_smt_online_materials()
        super().action_online()
        if smt_productions:
            smt_productions.write({'x_smt_online_state': 'online'})
        return True

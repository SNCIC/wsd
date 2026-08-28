# -*- coding: utf-8 -*-
"""投料（插件/装配，无料站表）：关键物料管控清单驱动的在线料行。

放在 sn_wsd_barcode 而不是 sn_wsd_smt 的原因：本模块同时依赖
sn_wsd_smt（在线料/扣点）与 sn_wsd_drawing_material（清单），而
sn_wsd_smt 加清单依赖会成环（drawing_material → workorder →
quality → api → smt）。

职责：
- sn.smt.online.material 扩展：清单行/工序实例/制具/辅料引用 + 约束
- mrp.production 扩展：制令单上线时按清单拆行
- sn.smt.loading.service 扩展：投料扫码 / 状态视图 / 全部下料 /
  下线时制具/辅料联动
- sn.smt.material.consumption 扩展：关键物料行过站门禁 + usage_times
  扣点（SMT 路线单走原逻辑）
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SnSmtOnlineMaterialDrawing(models.Model):
    _inherit = 'sn.smt.online.material'

    drawing_material_line_id = fields.Many2one(
        'sn.wsd.drawing.material.line',
        string='Drawing Material Line',
        index=True,
        ondelete='restrict',
        check_company=True,
    )
    drawing_material_type = fields.Selection(
        related='drawing_material_line_id.material_type',
        store=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Route Operation',
        index=True,
        ondelete='cascade',
        check_company=True,
        help='Operation instance the critical-material rows belong to; '
             'the pass-station gate is scoped per operation.',
    )
    tooling_id = fields.Many2one(
        'sn.tooling',
        string='Loaded Tooling',
        copy=False,
        index=True,
        ondelete='restrict',
        check_company=True,
    )
    consumable_info_id = fields.Many2one(
        'sn.consumable.info',
        string='Loaded Consumable',
        copy=False,
        index=True,
        ondelete='restrict',
        check_company=True,
    )
    last_operation_type = fields.Selection(
        selection_add=[('drawing_load', 'Drawing Material Load')],
        ondelete={'drawing_load': 'cascade'},
    )

    # 关键物料清单行同单只拆一次（smt_table 行该字段为空，不受约束影响）。
    _drawing_online_material_unique = models.Constraint(
        'unique(company_id, mes_order_id, drawing_material_line_id)',
        'Each drawing material line is split once per MES order.',
    )

    @api.constrains('source', 'device_seq', 'table_no', 'loadpoint',
                    'drawing_material_line_id', 'route_operation_id')
    def _check_source_fields(self):
        for record in self:
            if record.source == 'smt_table':
                if not (record.device_seq and record.table_no and record.loadpoint):
                    raise ValidationError(_(
                        'SMT material table rows require device, table and loadpoint.'))
            else:
                if not (record.drawing_material_line_id and record.route_operation_id):
                    raise ValidationError(_(
                        'Drawing material rows require a list line and a route operation.'))


class SnSmtMaterialLogDrawing(models.Model):
    _inherit = 'sn.smt.material.log'

    operation_type = fields.Selection(
        selection_add=[('drawing_load', 'Drawing Material Load')],
        ondelete={'drawing_load': 'cascade'},
    )


class MesOrderDrawingSplit(models.Model):
    _inherit = 'sn.wsd.mes.order'

    def _prepare_drawing_online_materials(self):
        """非 SMT 路线制令单：上线时按关键物料管控清单拆行。
        图号+车间+工序+面别 命中已维护清单 → 每清单行一条 drawing_list
        在线料行（挂工序实例，门禁按工序隔离）；没维护清单 → 0 行不管控。
        SMT 路线单以料站表为准，不重复拆。"""
        self.ensure_one()
        if self._is_smt_route_order():
            return self.env['sn.smt.online.material']
        existing = self.x_smt_online_material_ids.filtered(
            lambda line: line.source == 'drawing_list')
        if existing:
            return existing
        drawing_model = self.env['sn.wsd.drawing.material']
        online_model = self.env['sn.smt.online.material']
        drawing_no = self.product_id.default_code
        created = online_model
        for route_op in self.x_route_operation_ids:
            if not route_op.operation_id:
                continue
            workshop = (route_op.workcenter_id.x_workshop_id
                        or self.x_workshop_id)
            if not workshop:
                continue
            lst = drawing_model.search([
                ('company_id', '=', self.company_id.id),
                ('workshop_id', '=', workshop.id),
                ('x_drawing_no', '=', drawing_no),
                ('operation_id', '=', route_op.operation_id.id),
                ('x_side', '=', self.x_side),
            ], limit=1)
            if not lst or not lst.line_ids:
                continue
            for line in lst.line_ids:
                created += online_model.create({
                    'source': 'drawing_list',
                    'mes_order_id': self.id,
                    'drawing_material_line_id': line.id,
                    'route_operation_id': route_op.id,
                    'model_code': drawing_no or self.product_id.name,
                    'process_face': lst.x_side,
                    'item_code': self._drawing_line_item_code(line),
                    'workcenter_id': route_op.workcenter_id.id,
                    'production_line_id': self.production_line_id.id,
                    'company_id': self.company_id.id,
                })
        return created

    def _drawing_line_item_code(self, line):
        ref = line.material_ref
        if not ref:
            return ''
        if line.material_type == 'material' and hasattr(ref, 'default_code'):
            return ref.default_code or ''
        return ref.code or ref.name or ''

    def action_online(self):
        res = super().action_online()
        for order in self.filtered(lambda o: not o._is_smt_route_order()):
            order._prepare_drawing_online_materials()
        return res


class SnSmtLoadingServiceDrawing(models.AbstractModel):
    _inherit = 'sn.smt.loading.service'

    @api.model
    def _drawing_rows(self, mes_order):
        return mes_order.x_smt_online_material_ids.filtered(
            lambda line: line.source == 'drawing_list'
        ).sorted(lambda line: (line.route_operation_id.sequence or 0, line.id))

    @api.model
    def drawing_status(self, mes_order):
        """投料屏视图：应上/已上/未上 + 每行当前状态（含制具/辅料行）。"""
        rows = self._drawing_rows(mes_order)
        loaded = rows.filtered(lambda line: line.is_load == 'Y')
        return {
            'mes_order_id': mes_order.id,
            'mes_order_name': mes_order.display_name,
            'summary': {
                'required_qty': len(rows),
                'loaded_qty': len(loaded),
                'unloaded_qty': len(rows) - len(loaded),
                'line_complete': bool(rows) and len(loaded) == len(rows),
            },
            'rows': [{
                'online_material_id': line.id,
                'item_code': line.item_code,
                'material_type': line.drawing_material_type or 'material',
                'usage_times': line.drawing_material_line_id.usage_times or 1,
                'operation': line.route_operation_id.display_name or '',
                'load_status': line.is_load,
                'loaded_name': (line.loaded_material_lot_id.name
                                or line.tooling_id.sn
                                or line.consumable_info_id.sn or ''),
            } for line in rows],
        }

    @api.model
    def load_drawing_barcode(self, mes_order, barcode, workcenter=False):
        """投料扫码：物料盘号 / 制具个体SN / 辅料个体SN → 命中本单未上线
        清单行 → 上线（物料挂 lot，制具/辅料挂个体并联动各自状态机）。
        同一物料行换盘 = 先下线该行再扫新盘覆盖。"""
        barcode = (barcode or '').strip()
        if not barcode:
            raise UserError(_('The scanned barcode is empty.'))
        unloaded = self._drawing_rows(mes_order).filtered(
            lambda line: line.is_load != 'Y')
        if not unloaded:
            raise UserError(_('All critical material rows are already loaded online.'))

        company_domain = [
            '|', ('company_id', '=', False),
            ('company_id', '=', mes_order.company_id.id),
        ]
        lot = self.env['stock.lot'].search(
            [('name', '=', barcode)] + company_domain, limit=1)
        if lot:
            return self._load_drawing_material_row(
                mes_order, unloaded, lot, workcenter=workcenter)
        tooling = self.env['sn.tooling'].search(
            [('sn', '=', barcode)] + company_domain, limit=1)
        if tooling:
            return self._load_drawing_tooling_row(mes_order, unloaded, tooling)
        consumable = self.env['sn.consumable.info'].search(
            [('sn', '=', barcode)] + company_domain, limit=1)
        if consumable:
            return self._load_drawing_consumable_row(mes_order, unloaded, consumable)
        raise UserError(_(
            'No material lot, tooling or consumable matches the barcode %s.',
            barcode))

    def _load_drawing_material_row(self, mes_order, unloaded, lot, workcenter=False):
        target = unloaded.filtered(
            lambda line: line.drawing_material_type == 'material'
            and line.drawing_material_line_id.material_ref == lot.product_id)
        if not target:
            raise UserError(_(
                'The material %s is not in the critical material list of this order.',
                lot.name))
        line = target[0]
        # 与 SMT 共用的三条：同盘不得重复在线 / 未过期 / 数量为正。
        # 单账本：上料数量取该盘在手数量（_set_loaded_quantity 内统一），
        # 余量拦截按 usage_times 与在手余量比对。
        if self.env['sn.smt.online.material'].search_count([
            ('loaded_material_lot_id', '=', lot.id),
            ('is_load', '=', 'Y'),
        ], limit=1):
            raise ValidationError(_('The material is already loaded online.'))
        self._check_material_expiration(lot)
        line.write({
            'is_load': 'Y',
            'loaded_material_lot_id': lot.id,
            'workcenter_id': (workcenter or line.workcenter_id).id,
        })
        line._set_loaded_quantity(lot, operation_type='drawing_load')
        self._log(
            mes_order, line, 'drawing_load', material_lot=lot,
            workcenter=workcenter, qty_before=0.0,
            qty_after=line.loaded_qty, note='TL')
        return {
            'online_material_id': line.id,
            'item_code': line.item_code,
            'message': _('Critical material %s loaded (%s).', line.item_code, lot.name),
        }

    def _load_drawing_tooling_row(self, mes_order, unloaded, tooling):
        target = unloaded.filtered(
            lambda line: line.drawing_material_type == 'tooling'
            and line.drawing_material_line_id.material_ref == tooling.template_id)
        if not target:
            raise UserError(_(
                'The tooling %s is not in the critical material list of this order.',
                tooling.sn))
        occupied = self.env['sn.smt.online.material'].search_count([
            ('tooling_id', '=', tooling.id),
            ('is_load', '=', 'Y'),
        ], limit=1)
        if occupied:
            raise UserError(_(
                'Tooling %s is already online on another order. Unload it first.',
                tooling.sn))
        line = target[0]
        # 投料扫码一步到位：在库个体先补领用，再上线（状态机其余规则不动）。
        if tooling.state == 'idle':
            tooling.action_issue()
        tooling.action_online()
        line.write({'is_load': 'Y', 'tooling_id': tooling.id})
        self._log(
            mes_order, line, 'drawing_load', qty_before=0.0, qty_after=0.0,
            note='TL')
        return {
            'online_material_id': line.id,
            'item_code': line.item_code,
            'message': _('Tooling %s loaded (%s).', line.item_code, tooling.sn),
        }

    def _load_drawing_consumable_row(self, mes_order, unloaded, consumable):
        target = unloaded.filtered(
            lambda line: line.drawing_material_type == 'consumable'
            and line.drawing_material_line_id.material_ref == consumable.template_id)
        if not target:
            raise UserError(_(
                'The consumable %s is not in the critical material list of this order.',
                consumable.sn))
        occupied = self.env['sn.smt.online.material'].search_count([
            ('consumable_info_id', '=', consumable.id),
            ('is_load', '=', 'Y'),
        ], limit=1)
        if occupied:
            raise UserError(_(
                'Consumable %s is already online on another order. Unload it first.',
                consumable.sn))
        line = target[0]
        self.env['sn.consumable.service'].load(consumable.sn, mes_order.id)
        line.write({'is_load': 'Y', 'consumable_info_id': consumable.id})
        self._log(
            mes_order, line, 'drawing_load', qty_before=0.0, qty_after=0.0,
            note='TL')
        return {
            'online_material_id': line.id,
            'item_code': line.item_code,
            'message': _('Consumable %s loaded (%s).', line.item_code, consumable.sn),
        }

    @api.model
    def unload_drawing_all(self, mes_order):
        """全部下料（PDA 投料屏/制令单按钮共用）：本单全部在线料下线，
        制具/辅料个体联动下线。"""
        result = self.unload(mes_order, scope='order')
        return {
            'unloaded_qty': result['unloaded_qty'],
            'message': _('%s online material row(s) unloaded.', result['unloaded_qty']),
        }

    def _release_position(self, mes_order, online_material, operation_type='unload',
                          note=False, keep_feeder=False):
        """drawing_list 行：先联动制具/辅料下线，再走原下线收尾。"""
        old_tooling = online_material.tooling_id
        old_consumable = online_material.consumable_info_id
        if old_tooling:
            self.env['sn.tooling.service'].offline(old_tooling.sn)
        if old_consumable:
            self.env['sn.consumable.service'].unload(old_consumable.sn)
        online_material = super()._release_position(
            mes_order, online_material, operation_type=operation_type,
            note=note, keep_feeder=keep_feeder)
        online_material.write({'tooling_id': False, 'consumable_info_id': False})
        return online_material


class SnSmtMaterialConsumptionDrawing(models.Model):
    _inherit = 'sn.smt.material.consumption'

    @api.model
    def _drawing_rows_for_operation(self, route_operation):
        """关键物料清单拆出行按工序实例隔离：同一制令单多工序各有清单时，
        过站门禁只查当前工序的行。"""
        return route_operation.mes_order_id.x_smt_online_material_ids.filtered(
            lambda line: line.source == 'drawing_list'
            and line.route_operation_id.id == route_operation.id
        )

    @staticmethod
    def _line_is_loaded(line):
        if line.drawing_material_type in ('tooling', 'consumable'):
            return line.is_load == 'Y' and bool(
                line.tooling_id or line.consumable_info_id)
        return line.is_load == 'Y' and bool(line.loaded_material_lot_id)

    @api.model
    def validate_for_serial(self, route_operation, identity=False):
        mes_order = route_operation.mes_order_id
        if mes_order._is_smt_route_order():
            return super().validate_for_serial(route_operation, identity)
        # 关键物料清单门禁：行在就管（与行类型无关），全部上线才放行；
        # 该工序没拆行 = 没维护清单 = 不管控。制具/辅料行只上门禁不扣量。
        drawing_rows = self._drawing_rows_for_operation(route_operation)
        if not drawing_rows:
            return self.env['sn.smt.online.material']
        unloaded = drawing_rows.filtered(
            lambda line: not self._line_is_loaded(line))
        if unloaded:
            names = ', '.join(
                unloaded.mapped(lambda line: line.item_code or line.display_name))
            raise ValidationError(_(
                'Critical materials are not loaded online: %s. Load them '
                'before the product can pass this station.', names))
        material_rows = drawing_rows.filtered(
            lambda line: line.drawing_material_type == 'material')
        if not material_rows:
            return self.env['sn.smt.online.material']
        self.env.cr.execute(
            'SELECT id FROM sn_smt_online_material WHERE id IN %s FOR UPDATE',
            [tuple(material_rows.ids)],
        )
        material_rows.invalidate_recordset(['consumed_qty', 'remaining_qty'])
        # 无点数盘（loaded_qty=0）按不限量处理，不做余量拦截。
        shortages = material_rows.filtered(
            lambda line: line.loaded_qty > 0
            and line.remaining_qty
            < (line.drawing_material_line_id.usage_times or 1.0))
        if shortages:
            shortage = shortages[0]
            raise ValidationError(_(
                'Critical material %(material)s has insufficient quantity.',
                material=shortage.loaded_material_lot_id.name,
            ))
        return material_rows

    @api.model
    def consume_for_serial(self, route_operation, identity=False, operator_code=None,
                           external_event_id=None, source_system=None, note=None):
        mes_order = route_operation.mes_order_id
        if mes_order._is_smt_route_order():
            return super().consume_for_serial(
                route_operation, identity=identity, operator_code=operator_code,
                external_event_id=external_event_id,
                source_system=source_system, note=note)
        lines = self.validate_for_serial(route_operation, identity)
        if not lines:
            return self.env['sn.smt.material.consumption']
        # 清单行按 (SN, 工序) 幂等：同单多工序各有清单，各扣各的。
        existing = self.search([
            ('serial_identity_id', '=', identity.id),
            ('mes_order_id', '=', mes_order.id),
            ('route_operation_id', '=', route_operation.id),
            ('online_material_id.source', '=', 'drawing_list'),
            ('product_qty', '>', 0),
        ], limit=1)
        if existing:
            return existing
        created = self.env['sn.smt.material.consumption']
        for line in lines:
            # 清单行扣减量 = 每台产品消耗次数（usage_times）。
            point_qty = line.drawing_material_line_id.usage_times or 1.0
            before = line.remaining_qty
            after = before - point_qty
            record = self.create({
                'company_id': route_operation.company_id.id,
                'serial_identity_id': identity.id,
                'mes_order_id': mes_order.id,
                'route_operation_id': route_operation.id,
                'online_material_id': line.id,
                'material_lot_id': line.loaded_material_lot_id.id,
                'point_qty': point_qty,
                'product_qty': 1.0,
                'consumed_qty': point_qty,
                'qty_before': before,
                'qty_after': max(after, 0.0),
                'operator_code': operator_code,
                'external_event_id': external_event_id,
                'source_system': source_system,
                'note': note,
            })
            created |= record
            line.write({
                'last_consumed_serial_id': identity.id,
                'last_consumed_at': record.consumed_at,
            })
        return created

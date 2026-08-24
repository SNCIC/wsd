import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class MesOrderSmtOnline(models.Model):
    """制令单上线钩子：按 图号+面别 匹配料站表并拆行生成在线料表。
    制造订单（mrp.production）不再是 SMT 域的锚点。"""

    _inherit = 'sn.wsd.mes.order'

    x_smt_online_material_ids = fields.One2many(
        'sn.smt.online.material',
        'mes_order_id',
        string='SMT Online Materials',
    )
    x_smt_material_table_id = fields.Many2one(
        'sn.smt.material.table',
        string='SMT Material Table',
        copy=False,
        check_company=True,
    )
    x_smt_online_material_count = fields.Integer(
        string='SMT Online Material Count',
        compute='_compute_x_smt_online_material_count',
    )
    x_smt_loaded_material_count = fields.Integer(
        string='SMT Loaded Material Count',
        compute='_compute_x_smt_online_material_count',
    )
    x_smt_consumption_count = fields.Integer(
        string='SMT Consumption Count',
        compute='_compute_x_smt_consumption_summary',
    )
    x_smt_consumed_points = fields.Float(
        string='SMT Consumed Points',
        compute='_compute_x_smt_consumption_summary',
    )

    @api.depends('x_smt_online_material_ids.is_load')
    def _compute_x_smt_online_material_count(self):
        for order in self:
            order.x_smt_online_material_count = len(order.x_smt_online_material_ids)
            order.x_smt_loaded_material_count = len(
                order.x_smt_online_material_ids.filtered(lambda line: line.is_load == 'Y')
            )

    @api.depends('x_smt_online_material_ids.consumption_ids.consumed_qty')
    def _compute_x_smt_consumption_summary(self):
        consumption_model = self.env['sn.smt.material.consumption']
        for order in self:
            records = consumption_model.search([('mes_order_id', '=', order.id)])
            order.x_smt_consumption_count = len(records)
            order.x_smt_consumed_points = sum(records.mapped('consumed_qty'))

    def _is_smt_route_order(self):
        """SMT 识别以工艺路线头上的工艺类型为准（sn.wsd.process.route.x_process_type，
        制令单私有路线经 route_id 指回公共路线）：路线工艺类型为 SMT 即在上线时
        按 图号+面别 拆行。工序段/工位类型/车间名称均不参与判定。"""
        self.ensure_one()
        route = self.x_mes_route_id.route_id if self.x_mes_route_id else self.env['sn.wsd.process.route']
        return route.x_process_type == 'smt'

    def _check_can_generate_smt_online_materials(self):
        self.ensure_one()
        protected_lines = self.x_smt_online_material_ids.filtered(
            lambda line: line.loaded_material_lot_id or line.is_load == 'Y'
        )
        if protected_lines:
            raise ValidationError(_(
                'SMT online materials cannot be regenerated after online loading has started.'
            ))
        existing_logs = self.env['sn.smt.material.log'].search_count([
            ('mes_order_id', '=', self.id),
        ], limit=1)
        if existing_logs:
            raise ValidationError(_(
                'SMT online materials cannot be regenerated because SMT material logs already exist.'
            ))

    def _prepare_smt_online_materials(self):
        """按 图号+面别 匹配料站表并拆行；匹配不到生成 0 行并记录提示（不阻断上线）。"""
        self.ensure_one()
        if self.x_smt_online_material_ids:
            return self.x_smt_online_material_ids
        material_table = self.env['sn.smt.material.table']._match_for_mes_order(self)
        if not material_table:
            _logger.info(
                'MES order %s (drawing %s, side %s) has no matching SMT '
                'material table; no online material rows were generated.',
                self.name, self.product_id.default_code, self.x_side,
            )
            return self.env['sn.smt.online.material']
        self._check_can_generate_smt_online_materials()
        self.write({
            'x_smt_material_table_id': material_table.id,
            'x_smt_online_material_ids': [
                fields.Command.create(vals)
                for vals in material_table._prepare_online_material_vals(self)
            ],
        })
        return self.x_smt_online_material_ids

    def action_online(self):
        smt_orders = self.filtered(lambda order: order._is_smt_route_order())
        for order in smt_orders:
            order._prepare_smt_online_materials()
        return super().action_online()

    def action_open_smt_online_materials(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'SMT Online Materials',
            'res_model': 'sn.smt.online.material',
            'view_mode': 'list',
            'domain': [('mes_order_id', '=', self.id)],
            'context': {'default_mes_order_id': self.id},
        }

    def action_smt_batch_unload(self):
        """整单批量下料：所有在线料站一次下线（余量保留在卷上）。
        与转机继承互不冲突——转机流程内部自行收口源单，不经过此按钮。"""
        self.ensure_one()
        try:
            result = self.env['sn.smt.loading.service'].unload(self, scope='order')
        except ValidationError as error:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'type': 'warning', 'title': _('Batch Unload'), 'message': str(error)},
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Batch Unload'),
                'message': _('%(count)s material positions were unloaded; remaining points stay on the reels.',
                             count=result.get('unloaded_qty', 0)),
            },
        }

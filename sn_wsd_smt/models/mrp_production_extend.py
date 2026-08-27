from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MrpProductionExtend(models.Model):
    _name = 'mrp.production'
    _inherit = ['mrp.production']

    x_smt_pcb_panel_count = fields.Integer(
        string='PCB Panel Count',
        compute='_compute_smt_pcb_panel_count',
        store=False,
    )
    # One2many reverse link to panel records through production_id.
    x_smt_pcb_panel_ids = fields.One2many(
        'sn.smt.pcb.panel',
        'production_id',
        string='SMT PCB Panels',
    )

    @api.depends('x_smt_pcb_panel_ids')
    def _compute_smt_pcb_panel_count(self):
        """Compute the related SMT PCB panel record count."""
        for production in self:
            production.x_smt_pcb_panel_count = len(production.x_smt_pcb_panel_ids)

    def action_open_smt_pcb_panels(self):
        """Open the SMT PCB panel list."""
        self.ensure_one()
        return {
            'name': 'SMT PCB Panels',
            'type': 'ir.actions.act_window',
            'res_model': 'sn.smt.pcb.panel',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'create': False},
        }

    def _get_smt_effective_pcb_board_qty(self):
        self.ensure_one()
        return self.env['sn.smt.pcb.board'].search_count([
            ('panel_id.production_id', '=', self.id),
            '|',
            ('state', '=', False),
            ('state', 'in', ['active', 'scrapped']),
        ])

    def _get_smt_pcb_board_capacity_values(self, requested_qty=0):
        self.ensure_one()
        planned_qty = int(self.product_uom_id.round(self.product_qty))
        existing_qty = self._get_smt_effective_pcb_board_qty()
        allowed_extra_qty = 0
        available_qty = max(planned_qty + allowed_extra_qty - existing_qty, 0)
        return {
            'planned_qty': planned_qty,
            'existing_qty': existing_qty,
            'requested_qty': int(requested_qty or 0),
            'allowed_extra_qty': allowed_extra_qty,
            'available_qty': available_qty,
        }

    def _check_smt_pcb_board_capacity(self, requested_qty):
        self.ensure_one()
        values = self._get_smt_pcb_board_capacity_values(requested_qty)
        if values['requested_qty'] > values['available_qty']:
            raise ValidationError(_(
                'SMT PCB board quantity exceeds manufacturing order planned quantity. '
                'Planned: %(planned_qty)s, existing effective: %(existing_qty)s, requested: %(requested_qty)s, available: %(available_qty)s.'
            ) % values)
        return values

    def _post_inventory(self, cancel_backorder=False):
        # 标准完工路径（meter 打包流程之外的制令单）过账前同样按流水
        # 净值回填领料 move；幂等防护在 _smt_backfill_raw_moves 内
        self._smt_backfill_raw_moves()
        return super()._post_inventory(cancel_backorder=cancel_backorder)

    def _smt_backfill_raw_moves(self):
        """SMT/整机关键物料 完工倒冲回填（覆写 sn_wsd_mrp 的空钩子）：
        被消耗流水覆盖的组件，其领料 move 的批次与数量以流水净值为准——
        扣的卷 = 上线扫描的物料SN，扣的量 = MES 实际消耗，不经过 BOM
        翻译、不交给预留/FEFO 选批次。流水有而 BOM 无的产品（替代料）
        动态补建领料 move；未管控组件（BOM 有、流水无）不动，维持原生
        BOM 倒冲。"""
        for production in self:
            net_by_lot = self.env['sn.smt.material.consumption']._net_consumption_by_lot(production)
            if not net_by_lot:
                continue
            open_moves = production.move_raw_ids.filtered(
                lambda move: move.state not in ('done', 'cancel'))
            # 幂等：该产品已有过账的领料 move（首次完工已按流水回填过，
            # 复完工/恢复流程再进来）时不再重复回填，防止双重扣减
            settled_products = production.move_raw_ids.filtered(
                lambda move: move.state == 'done').mapped('product_id')
            by_product = {}
            for lot, qty in net_by_lot.items():
                if lot.product_id in settled_products:
                    continue
                by_product.setdefault(lot.product_id, []).append((lot, qty))
            used_moves = self.env['stock.move']
            net_products = set(by_product.keys())
            # 替代料上线的原 BOM 行同样清零：流水产品可替代的目标产品，
            # 本单实际未耗（被替代），不得再按 BOM 倒冲重复扣料
            for net_product in list(net_products):
                for origin in self.env['product.product'].search([
                    ('substitute_ids', 'in', net_product.ids),
                ]):
                    if origin not in net_products:
                        net_products.add(origin)
            for product, lot_qtys in by_product.items():
                total = sum(qty for _lot, qty in lot_qtys)
                move = (open_moves - used_moves).filtered(
                    lambda mv, p=product: mv.product_id == p)[:1]
                if move:
                    used_moves |= move
                else:
                    # 替代料上线：BOM 没有该组件行，按流水净值补建领料 move
                    move = self.env['stock.move'].create(
                        production._get_move_raw_values(product, total, product.uom_id))
                    move._action_confirm(merge=False)
                production._smt_backfill_move_lines(move, lot_qtys)
            # 同产品多出的 BOM 行（含被替代料顶替的）不再倒冲，交给
            # 既有 moves_to_cancel 走取消
            backfilled_products = tuple(net_products)
            for extra in (open_moves - used_moves).filtered(
                lambda mv, ps=backfilled_products: mv.product_id in ps
            ):
                extra.picked = False

    def _smt_backfill_move_lines(self, move, lot_qtys):
        """把领料 move 的移动行替换为按卷回填的行：一卷一行，批次=流水卷，
        数量=净值（产品单位换算到 move 单位）。"""
        self.ensure_one()
        if move.move_line_ids:
            move.move_line_ids.unlink()
        line_vals = []
        for lot, qty in lot_qtys:
            quantity = lot.product_id.uom_id._compute_quantity(qty, move.product_uom)
            if quantity <= 0:
                continue
            line_vals.append({
                'move_id': move.id,
                'picking_id': move.picking_id.id,
                'company_id': move.company_id.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'quantity': quantity,
                'lot_id': lot.id,
                'lot_name': lot.name,
            })
        if line_vals:
            self.env['stock.move.line'].create(line_vals)
            move.picked = True

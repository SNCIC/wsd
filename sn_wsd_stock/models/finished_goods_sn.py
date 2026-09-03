from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError


class MesOrderFinishedMaterialSn(models.Model):
    """完工入库批级物料SN（finished-goods-material-sn）。

    override ``sn.wsd.mes.order._mes_finished_material_lot``（mrp 侧 hook）：
    tracking='lot' 的产出按与来料同构的 5 段码建 lot——
    ``料号$公司码$批次段$数量$序号``。批次段=MO 合同号（空则当天日期，
    外贸无合同号/半成品自然落日期）；序号复用来料全局序列
    ``sn.wsd.material.serial``（永续递增，码天然唯一）；批次段同时写入
    lot.arrival_batch_no（入库批次），来源收货单挂 source_picking_id
    回链制令单。"""

    _inherit = 'sn.wsd.mes.order'

    def _mes_finished_material_lot(self, qty, picking):
        self.ensure_one()
        mo = self.production_id
        product = mo.product_id
        if product.tracking != 'lot':
            return self.env['stock.lot']
        product_code = (product.default_code or '').strip()
        if not product_code:
            raise ValidationError(_(
                'Product %(product)s must have an internal reference to '
                'generate its material SN.', product=product.display_name))
        sequence = self.env['ir.sequence'].next_by_code(
            'sn.wsd.material.serial')
        if not sequence:
            raise UserError(_('The material serial sequence is not configured.'))
        company_code = (self.company_id.partner_id.ref or '').strip()
        batch_no = (mo.x_contract_no or '').strip() or fields.Date.context_today(
            self).strftime('%Y%m%d')
        name = '$'.join([
            product_code, company_code, batch_no, str(int(qty)), sequence])
        if self.env['stock.lot'].search_count([
            ('name', '=', name),
            ('product_id', '=', product.id),
            '|', ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ]):
            raise ValidationError(
                _('The material SN already exists: %s', name))
        return self.env['stock.lot'].create({
            'name': name,
            'product_id': product.id,
            'company_id': self.company_id.id,
            'arrival_batch_no': batch_no,
            'material_sn_base': name,
            'initial_quantity': qty,
            'source_picking_id': picking.id,
        })


class StockPickingFinishedSn(models.Model):
    """完工收货单上的物料标签入口（finished-goods-material-sn）。

    成品库路径（待验证）：一键补齐批级码——按移动需求量生成 lot 并挂
    picked 收货行，随后即可过账；线边直验/已完成单：直接重打已有 lot 的
    ZPL（补打）。按钮可见性复用来料的 can_print_material_labels（扩到
    完工收货类型，含已完成）。"""

    _inherit = 'stock.picking'

    def action_print_finished_material_labels(self):
        self.ensure_one()
        order = self.x_mes_order_id
        if not order:
            raise UserError(_(
                'Material labels are only available on completion receipts '
                'linked to an MES order.'))
        lots = self.env['stock.lot']
        for move in self.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
                and m.product_id.tracking == 'lot'):
            existing = move.move_line_ids.filtered(
                lambda l: l.quantity).mapped('lot_id')
            lots |= existing
            if existing:
                continue
            qty = move.product_uom_qty
            lot = order._mes_finished_material_lot(qty, self)
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': self.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'quantity': qty,
                'lot_id': lot.id,
                'lot_name': lot.name,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'company_id': self.company_id.id,
                'picked': True,
            })
            lots |= lot
        # 已完成单（线边补打）没有待处理移动——重打行上已有的码
        # （完成后的行只在 move 上可见，picking 级 one2many 为空）
        if not lots:
            lots = self.move_ids.move_line_ids.mapped('lot_id')
        if not lots:
            raise UserError(_(
                'Nothing to print: no tracked product on this receipt.'))
        action = self.env.ref(
            'sn_wsd_stock.action_report_incoming_material_label_zpl'
        ).report_action(lots, config=False)
        action['close_on_report_download'] = True
        return action


class MesOrderMeterLotEnrich(models.Model):
    """台级物料SN lot 的批次属性与回链（finished-goods-material-sn）。"""

    _inherit = 'sn.wsd.mes.order'

    def _mes_meter_lot(self, sn, product, picking):
        lot = super()._mes_meter_lot(sn, product, picking)
        if lot and not lot.arrival_batch_no:
            mo = self.production_id
            lot.write({
                'arrival_batch_no': (mo.x_contract_no or '').strip()
                or fields.Date.context_today(self).strftime('%Y%m%d'),
                'material_sn_base': lot.name,
                'initial_quantity': 1.0,
                'source_picking_id': picking.id,
            })
        return lot


class MeterPackRecordSnLots(models.Model):
    """箱号/托盘号快捷键（finished-goods-material-sn）：扫箱/托 → 按包装
    记录解析整箱/整托的表SN → SN-lot 集合（箱/托号不是库存码）。"""

    _inherit = 'sn.wsd.meter.pack.record'

    def _mes_sn_lots(self):
        lots = self.env['stock.lot']
        for record in self:
            sn = (record.serial_identity_id.name or '').strip()
            if not sn:
                continue
            lots |= lots.search([
                ('name', '=', sn),
                ('product_id', '=', record.product_id.id),
            ])
        return lots

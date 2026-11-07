from odoo import api, fields, models, _

from .demo_data import get_warehouse_demo_data

PICKING_STATE_LABELS = {
    'draft': _('Draft'),
    'waiting': _('Waiting'),
    'confirmed': _('Waiting Availability'),
    'assigned': _('Ready'),
    'done': _('Done'),
    'cancel': _('Cancelled'),
}

LOSS_ALERT_THRESHOLD = 10.0
MAX_TABLE_ROWS = 10
MAX_LATEST_ROWS = 8


class SnWsdWarehouseDashboardService(models.AbstractModel):
    _name = 'sn.wsd.warehouse.dashboard.service'
    _description = 'Warehouse Stock Dashboard Service'

    @api.model
    def _get_quant_domain(self, warehouse_id=None, category_id=None):
        domain = [('location_id.usage', '=', 'internal')]
        if warehouse_id:
            warehouse = self.env['stock.warehouse'].browse(int(warehouse_id))
            if warehouse.exists() and warehouse.view_location_id:
                domain.append(('location_id', 'child_of', warehouse.view_location_id.id))
        if category_id:
            domain.append(('product_id.categ_id', 'child_of', int(category_id)))
        return domain

    @api.model
    def _get_picking_base_domain(self, warehouse_id=None, date_from=None, date_to=None):
        domain = [('state', '!=', 'cancel')]
        if warehouse_id:
            domain.append(('picking_type_id.warehouse_id', '=', int(warehouse_id)))
        if date_from:
            domain.append(('scheduled_date', '>=', date_from))
        if date_to:
            domain.append(('scheduled_date', '<=', date_to))
        return domain

    @api.model
    def _prepare_issue_line(self, picking, move):
        spec = ', '.join(
            move.product_id.product_template_attribute_value_ids.mapped('name')
        ) or '-'
        date_done = picking.date_done or picking.scheduled_date
        return {
            'picking_name': picking.name or '/',
            'product_name': move.product_id.display_name or '-',
            'product_code': move.product_id.default_code or '-',
            'spec': spec,
            'qty': move.quantity or move.product_uom_qty or 0.0,
            'uom': move.product_uom.name or '',
            'user_name': picking.user_id.name or picking.partner_id.name or '-',
            'time': fields.Datetime.to_string(date_done) if date_done else '',
            'state': picking.state,
            'state_label': PICKING_STATE_LABELS.get(picking.state, picking.state),
        }

    @api.model
    def _prepare_quant_row(self, quant):
        diff = quant.inventory_diff_quantity or 0.0
        return {
            'product_code': quant.product_id.default_code or '-',
            'product_name': quant.product_id.display_name or '-',
            'book_qty': quant.quantity or 0.0,
            'real_qty': quant.inventory_quantity or 0.0,
            'diff_qty': diff,
            'location_name': quant.location_id.display_name or '-',
            'uom': quant.product_uom_id.name or '',
            'alert': abs(diff) >= LOSS_ALERT_THRESHOLD,
        }

    @api.model
    def get_warehouse_screen_data(self, warehouse_id=None, category_id=None, date_from=None, date_to=None):
        today = fields.Date.context_today(self)
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        quant_domain = self._get_quant_domain(warehouse_id, category_id)
        quants = self.env['stock.quant'].search(quant_domain)

        total_stock = sum(quants.mapped('quantity'))

        # 无任何库存单据且零库存时启用集中管理的占位演示数据（见 demo_data.py），
        # 存在真实数据后自动切回真实查询。
        has_pickings = self.env['stock.picking'].search_count([('state', '!=', 'cancel')])
        if not has_pickings and total_stock == 0.0:
            data = get_warehouse_demo_data()
            data['summary']['is_demo'] = True
            data['filter_options'] = {
                'warehouses': [
                    {'id': w.id, 'name': w.name}
                    for w in self.env['stock.warehouse'].search([], order='sequence, id')
                ],
                'categories': [
                    {'id': c.id, 'name': c.name}
                    for c in self.env['product.category'].search([], order='parent_path', limit=60)
                ],
            }
            return data
        gain_quants = quants.filtered(lambda q: (q.inventory_diff_quantity or 0.0) > 0.0)
        loss_quants = quants.filtered(lambda q: (q.inventory_diff_quantity or 0.0) < 0.0)
        gain_total = sum(gain_quants.mapped('inventory_diff_quantity'))
        loss_total = -sum(loss_quants.mapped('inventory_diff_quantity'))

        gain_rows = sorted(
            gain_quants, key=lambda q: q.inventory_diff_quantity, reverse=True
        )[:MAX_TABLE_ROWS]
        loss_rows = sorted(
            loss_quants, key=lambda q: q.inventory_diff_quantity
        )[:MAX_TABLE_ROWS]

        picking_domain = self._get_picking_base_domain(warehouse_id, date_from, date_to)
        picking_domain.append(('picking_type_id.code', '=', 'outgoing'))
        outgoing_pickings = self.env['stock.picking'].search(
            picking_domain, order='date_done desc, scheduled_date desc, id desc', limit=40
        )

        issue_lines = []
        today_issue_qty = 0.0
        today_pickings = outgoing_pickings.filtered(
            lambda p: p.date_done and p.date_done.date() == today
        )
        category_prefix = False
        if category_id:
            categ = self.env['product.category'].browse(int(category_id))
            if categ.exists() and categ.parent_path:
                category_prefix = categ.parent_path
        for picking in outgoing_pickings:
            for move in picking.move_ids:
                if category_prefix:
                    move_path = move.product_id.categ_id.parent_path or ''
                    if not move_path.startswith(category_prefix):
                        continue
                issue_lines.append(self._prepare_issue_line(picking, move))
        for picking in today_pickings:
            for move in picking.move_ids:
                today_issue_qty += move.quantity or 0.0
        issue_lines = issue_lines[:MAX_TABLE_ROWS * 2]

        # 当前操作状态：入库 / 出库 / 移库 / 盘点
        local_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = fields.Datetime.now() - (now - local_midnight)
        today_start_str = fields.Datetime.to_string(today_start_utc)
        active_domain = self._get_picking_base_domain(warehouse_id, date_from, date_to)
        active_domain.append(('state', 'in', ['waiting', 'confirmed', 'assigned']))
        active_pickings = self.env['stock.picking'].search(active_domain)
        operation_stats = []
        for code, label in [
            ('incoming', _('Incoming')),
            ('outgoing', _('Outgoing')),
            ('internal', _('Internal Transfer')),
        ]:
            typed = active_pickings.filtered(
                lambda p, c=code: p.picking_type_id.code == c
            )
            done_today_domain = self._get_picking_base_domain(warehouse_id, date_from, date_to)
            done_today_domain += [
                ('picking_type_id.code', '=', code),
                ('state', '=', 'done'),
                ('date_done', '>=', today_start_str),
            ]
            done_today = self.env['stock.picking'].search_count(done_today_domain)
            operation_stats.append({
                'code': code,
                'label': label,
                'active_count': len(typed),
                'ready_count': len(typed.filtered(lambda p: p.state == 'assigned')),
                'done_today': done_today,
            })
        pending_inventory_count = len(quants.filtered(
            lambda q: q.inventory_quantity_set and (q.inventory_diff_quantity or 0.0) != 0.0
        ))
        inventory_adjust_domain = [
            ('is_inventory', '=', True),
            ('state', '=', 'done'),
            ('date', '>=', today_start_str),
        ]
        inventory_done_today = self.env['stock.move'].search_count(inventory_adjust_domain)
        operation_stats.append({
            'code': 'inventory',
            'label': _('Inventory'),
            'active_count': pending_inventory_count,
            'ready_count': 0,
            'done_today': inventory_done_today,
        })

        # 最新动态
        latest_domain = self._get_picking_base_domain(warehouse_id, date_from, date_to)
        latest_pickings = self.env['stock.picking'].search(
            latest_domain, order='write_date desc, id desc', limit=MAX_LATEST_ROWS
        )
        type_labels = {
            'incoming': _('Incoming'),
            'outgoing': _('Outgoing'),
            'internal': _('Internal Transfer'),
        }
        latest_operations = [
            {
                'name': p.name or '/',
                'type_label': type_labels.get(p.picking_type_id.code, p.picking_type_id.name),
                'state': p.state,
                'state_label': PICKING_STATE_LABELS.get(p.state, p.state),
                'partner_name': p.partner_id.name or '',
                'user_name': p.user_id.name or '-',
                'time': fields.Datetime.to_string(p.write_date or p.scheduled_date or p.date_done or fields.Datetime.now()),
            }
            for p in latest_pickings
        ]

        warehouses = self.env['stock.warehouse'].search([], order='sequence, id')
        categories = self.env['product.category'].search([], order='parent_path', limit=60)

        return {
            'summary': {
                'today_issue_qty': today_issue_qty,
                'gain_total': gain_total,
                'loss_total': loss_total,
                'total_stock': total_stock,
                'active_operation_count': len(active_pickings),
                'pending_inventory_count': pending_inventory_count,
                'today_date': fields.Date.to_string(today),
                'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
            },
            'issue_lines': issue_lines,
            'gain_rows': [self._prepare_quant_row(q) for q in gain_rows],
            'loss_rows': [self._prepare_quant_row(q) for q in loss_rows],
            'operation_stats': operation_stats,
            'latest_operations': latest_operations,
            'filter_options': {
                'warehouses': [{'id': w.id, 'name': w.name} for w in warehouses],
                'categories': [{'id': c.id, 'name': c.name} for c in categories],
            },
        }

    @api.model
    def action_open_warehouse_screen(self):
        client_action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_warehouse_screen_client',
            raise_if_not_found=False,
        )
        if client_action:
            action = client_action.read()[0]
            action['name'] = _('Warehouse Stock Board')
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_warehouse_screen_action',
            'name': _('Warehouse Stock Board'),
            'target': 'fullscreen',
            'context': {},
        }

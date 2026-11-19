# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

# 看板为厂内中文大屏，标签直接固定中文（与本模块其它大屏一致）
NODE_LABELS = [
    ('sale', '销售接单'),
    ('material', '物料齐套'),
    ('production', '生产开工'),
    ('stations', '工序过站'),
    ('test', '质量检测'),
    ('receipt', '完工入库'),
    ('delivery', '销售发货'),
]

SALE_STATE_LABELS = {
    'draft': '报价单',
    'sent': '报价已发送',
    'sale': '销售订单',
    'done': '已锁定',
    'cancel': '已取消',
}

MO_STATE_LABELS = {
    'draft': '草稿',
    'confirmed': '已确认',
    'progress': '生产中',
    'to_close': '待关闭',
    'done': '已完工',
    'cancel': '已取消',
}

PICKING_STATE_LABELS = {
    'draft': '草稿',
    'waiting': '等待',
    'confirmed': '待处理',
    'assigned': '已就绪',
    'done': '已完成',
    'cancel': '已取消',
}

MES_STATE_LABELS = {
    'released': '已下达',
    'picked': '已领料',
    'in_progress': '生产中',
    'done': '已完工',
    'cancelled': '已取消',
}

RESULT_LABELS = {
    'ok': '通过',
    'ng': '不良',
    'scrap': '报废',
    'hold': '挂起',
    'in_progress': '在制',
}


class SnWsdOrderFlowDashboardService(models.AbstractModel):
    _name = 'sn.wsd.order.flow.dashboard.service'
    _description = 'Order Full-Flow Dashboard Service'

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _dt_str(self, dt):
        if not dt:
            return ''
        local = fields.Datetime.context_timestamp(self, dt)
        return local.strftime('%Y-%m-%d %H:%M')

    def _day_str(self, dt):
        if not dt:
            return ''
        local = fields.Datetime.context_timestamp(self, dt)
        return local.strftime('%m-%d %H:%M')

    def _node(self, key, status, title, time_str, qty_text, detail=''):
        return {
            'key': key,
            'label': dict(NODE_LABELS).get(key, key),
            'status': status,  # pending / active / done
            'title': title,
            'time': time_str,
            'qty': qty_text,
            'detail': detail,
        }

    # ------------------------------------------------------------------
    # main entry
    # ------------------------------------------------------------------
    @api.model
    def get_order_flow_data(self, so_id=None):
        SaleOrder = self.env['sale.order']
        today = fields.Date.context_today(self)
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())

        orders = SaleOrder.search([], order='date_order desc, id desc', limit=12)
        order = SaleOrder.browse(int(so_id)) if so_id else orders[:1]
        if not order:
            return {
                'summary': {
                    'order_count': 0,
                    'in_production': 0,
                    'done_output': 0,
                    'shipped_qty': 0,
                    'today_date': fields.Date.to_string(today),
                    'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                },
                'order_options': [],
                'nodes': [],
                'stations': [],
                'tests': [],
                'traces': [],
                'order_info': {},
            }

        # ------------------------------------------------------------------
        # linked records
        # ------------------------------------------------------------------
        # 最新代码里 MO 通过 origin 关联销售订单，MES 制令单再通过
        # production_id 反向关联 MO；补货单生成的 MO 不带 origin，改用
        # reference_ids.sale_ids 兜底。旧写法只按单条 MO 取制令单，
        # 双面板（一个 MO 两张制令单）会漏关联。
        mos = self.env['mrp.production'].search([('origin', '=', order.name)])
        if not mos:
            mos = self.env['mrp.production'].search(
                [('reference_ids.sale_ids', 'in', [order.id])])
        mo = mos[:1]
        mes = self.env['sn.wsd.mes.order'].search(
            [('production_id', 'in', mos.ids)], order='id', limit=1) if mos else \
            self.env['sn.wsd.mes.order']
        mroute = mes.x_mes_route_id if mes else self.env['sn.wsd.mes.order.route']
        mops = mroute.operation_ids.sorted('sequence') if mroute else \
            self.env['sn.wsd.mes.order.route.operation']

        pickings = self.env['stock.picking'].search([
            ('origin', '=', order.name), ('state', '!=', 'cancel')])
        delivery = pickings.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]
        issue_pickings = mes.picking_ids.filtered(
            lambda p: p.state != 'cancel') if mes else \
            self.env['stock.picking']
        issue_done = issue_pickings.filtered(lambda p: p.state == 'done')
        receipt = self.env['stock.picking'].search([
            ('x_mes_order_id', '=', mes.id),
            ('picking_type_id.code', 'in', ('incoming', 'internal')),
            ('state', '!=', 'cancel'),
        ], order='id desc', limit=1) if mes else self.env['stock.picking']

        # ------------------------------------------------------------------
        # node status
        # ------------------------------------------------------------------
        planned_qty = mes.planned_qty if mes else (mo.product_qty if mo else 0.0)
        # produced_qty 是最新代码里 MES 制令单的产出聚合字段；
        # x_done_qty 是完工入库数量，x_sn_wip_count 是官方在制 SN 台数。
        output_qty = mes.produced_qty if mes else 0.0
        done_qty = mes.x_done_qty if mes else 0.0
        wip_qty = mes.x_sn_wip_count if mes else 0

        # 节点 1：销售接单
        sale_time = self._dt_str(order.date_order)
        sale_node = self._node(
            'sale', 'done' if order.state in ('sale', 'done') else 'active',
            _('%s · %s') % (order.name, order.partner_id.name or ''),
            sale_time,
            _('%s 台 / ¥%s') % (
                self._fmt_qty(sum(order.order_line.mapped('product_uom_qty'))),
                '{:,.0f}'.format(order.amount_untaxed or 0.0)),
        )

        # 节点 2：物料齐套
        if issue_pickings:
            all_done = all(p.state == 'done' for p in issue_pickings)
            last_dt = max(
                (p.date_done for p in issue_done if p.date_done), default=None)
            material_node = self._node(
                'material', 'done' if all_done else 'active',
                _('领料 %s 单') % len(issue_pickings),
                self._dt_str(last_dt) if all_done else _('发料中'),
                self._fmt_qty(mes.picked_qty if mes else 0.0),
            )
        else:
            material_node = self._node(
                'material', 'pending', _('待领料'), '', '')

        # 节点 3：生产开工
        if mo:
            started = mo.state in ('progress', 'to_close', 'done') or \
                (mes and mes.x_online_date)
            mo_time = self._dt_str(
                mes.x_online_date or mo.date_start or mo.create_date)
            production_node = self._node(
                'production', 'done' if started else 'active',
                _('%s · %s') % (mo.name, mo.product_id.display_name or ''),
                mo_time,
                _('%s 台') % self._fmt_qty(mo.product_qty),
                MO_STATE_LABELS.get(mo.state, mo.state),
            )
        else:
            production_node = self._node(
                'production', 'pending', _('待排产'), '', '')

        # 节点 4：工序过站
        stations = self._station_rows(mes, mops, planned_qty)
        if stations:
            passed_total = sum(s['passed'] for s in stations)
            last_exit = max(
                (s['out_dt'] for s in stations if s['out_dt']), default=None)
            all_passed = output_qty and output_qty + 0.0001 >= planned_qty
            stations_node = self._node(
                'stations', 'done' if all_passed else 'active',
                _('%s 道工序 · 在制 %s') % (
                    len(stations), self._fmt_qty(wip_qty)),
                self._day_str(last_exit) if last_exit else '',
                self._fmt_qty(passed_total),
            )
        else:
            stations_node = self._node(
                'stations', 'pending', _('待上线'), '', '')

        # 节点 5：质量测试
        tests = self.env['sn.wsd.mes.test.result'].search(
            [('mes_order_id', '=', mes.id)] if mes else
            [('id', '=', 0)], order='test_time desc', limit=40)
        test_total = len(tests)
        test_ok = len(tests.filtered(lambda t: t.result == 'ok'))
        test_ng = len(tests.filtered(lambda t: t.result in ('ng', 'hold')))
        test_last = tests[:1]
        test_node = self._node(
            'test', 'done' if test_total and (mo and mo.state == 'done')
            else ('active' if test_total else 'pending'),
            _('直通率 %s%%') % (
                round(test_ok / test_total * 100.0, 1) if test_total else '0'),
            self._dt_str(test_last.test_time) if test_last else '',
            _('%s / %s 笔') % (self._fmt_qty(test_ok), self._fmt_qty(test_total)),
            _('NG %s') % self._fmt_qty(test_ng) if test_ng else '',
        )

        # 节点 6：完工入库
        if done_qty:
            receipt_node = self._node(
                'receipt',
                'done' if done_qty + 0.0001 >= planned_qty else 'active',
                _('完工入库 %s') % (receipt.name or ''),
                self._dt_str(
                    max((p.date_done for p in
                         self.env['stock.picking'].search([
                             ('x_mes_order_id', '=', mes.id),
                             ('state', '=', 'done')]) if p.date_done),
                        default=None)),
                self._fmt_qty(done_qty),
            )
        else:
            receipt_node = self._node(
                'receipt', 'pending', _('待完工'), '', '')

        # 节点 7：销售发货
        if delivery:
            delivery_node = self._node(
                'delivery', 'done' if delivery.state == 'done' else 'active',
                _('%s · %s') % (
                    delivery.name,
                    PICKING_STATE_LABELS.get(delivery.state, delivery.state)),
                self._dt_str(delivery.date_done),
                self._fmt_qty(sum(
                    delivery.move_ids.mapped('quantity')) or 0.0),
            )
        else:
            delivery_node = self._node(
                'delivery', 'pending', _('待发货'), '', '')

        nodes = [sale_node, material_node, production_node, stations_node,
                 test_node, receipt_node, delivery_node]

        # ------------------------------------------------------------------
        # 明细：测试记录 / SN 追踪
        # ------------------------------------------------------------------
        test_rows = [{
            'time': self._dt_str(t.test_time),
            'serial_no': t.serial_identity_id.name or '-',
            'station': t.workcenter_code or '-',
            'test_type': t.test_type,
            'result': t.result,
            'result_label': RESULT_LABELS.get(t.result, t.result),
            'cycle_sec': round(t.cycle_time_sec or 0.0, 1),
            'status': 'danger' if t.result == 'ng'
                else 'warning' if t.result == 'hold' else 'normal',
        } for t in tests[:10]]

        histories = self.env['sn.wsd.serial.operation.history'].search(
            [('mes_order_id', '=', mes.id)] if mes else [('id', '=', 0)],
            order='out_date desc, id desc', limit=14)
        trace_rows = [{
            'time': self._dt_str(h.out_date or h.in_date),
            'serial_no': h.serial_identity_id.name or '-',
            'station': h.workcenter_id.code or '-',
            'operation': h.route_operation_id.name or '-',
            'result': h.result,
            'result_label': RESULT_LABELS.get(h.result, h.result),
            'status': 'danger' if h.result in ('ng', 'scrap')
                else 'warning' if h.result == 'in_progress' else 'normal',
        } for h in histories]

        # ------------------------------------------------------------------
        # summary
        # ------------------------------------------------------------------
        shipped = 0.0
        if delivery and delivery.state == 'done':
            shipped = sum(delivery.move_ids.mapped('quantity'))
        return {
            'summary': {
                'order_count': len(orders),
                # 在产口径取 MES 制令单在制状态数，旧写法把全部销售订单数
                # 当成在产订单数。
                'in_production': self.env['sn.wsd.mes.order'].search_count(
                    [('state', 'in', ('picked', 'in_progress'))]),
                'done_output': output_qty,
                'wip_qty': wip_qty,
                'shipped_qty': shipped,
                'today_date': fields.Date.to_string(today),
                'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'is_demo': False,
            },
            'order_options': [{
                'id': o.id,
                'name': o.name,
                'partner': o.partner_id.name or '-',
                'product': (o.order_line[:1].product_id.display_name or '-'),
                'qty': self._fmt_qty(
                    sum(o.order_line.mapped('product_uom_qty'))),
            } for o in orders],
            'current_order_id': order.id,
            'nodes': nodes,
            'stations': [self._station_public(s) for s in stations],
            'tests': test_rows,
            'traces': trace_rows,
            'order_info': {
                'name': order.name,
                # 客户优先取销售订单，最新代码里 MES 制令单也有 x_partner_id
                # （从来源销售单解析），备单场景可作为兜底。
                'partner': order.partner_id.name
                    or (mes.x_partner_id.name if mes else '') or '-',
                'product': order.order_line[:1].product_id.display_name or '-',
                'qty': self._fmt_qty(
                    sum(order.order_line.mapped('product_uom_qty'))),
                'amount': '{:,.2f}'.format(order.amount_untaxed or 0.0),
                'date_order': self._dt_str(order.date_order),
                'state': SALE_STATE_LABELS.get(order.state, order.state),
                'mo_name': mo.name if mo else '-',
                'mo_state': MO_STATE_LABELS.get(mo.state, mo.state) if mo else '-',
                'mes_name': mes.name if mes else '-',
                'mes_state': MES_STATE_LABELS.get(mes.state, mes.state) if mes else '-',
                'line': mes.production_line_id.name or '-' if mes else '-',
                'plan_date': fields.Date.to_string(mes.date_plan) if mes
                    and mes.date_plan else '-',
                'planned_qty': self._fmt_qty(planned_qty),
                'output_qty': self._fmt_qty(output_qty),
                # 完成进度统一取官方 x_progress_rate（完工入库÷排产，
                # 双面板 T 面按产出÷排产），不再用产出÷排产自行推算。
                'progress_rate': round(mes.x_progress_rate or 0.0, 1)
                    if mes else 0.0,
            },
        }

    def _fmt_qty(self, value):
        value = value or 0.0
        return ('%d' % round(value)) if abs(value - round(value)) < 0.001 \
            else '%.1f' % value

    # ------------------------------------------------------------------
    # station rows
    # ------------------------------------------------------------------
    def _station_rows(self, mes, mops, planned_qty):
        rows = []
        if not mes:
            return rows
        for m_op in mops:
            histories = m_op.serial_history_ids
            wips = m_op.serial_wip_ids
            ok_histories = histories.filtered(lambda h: h.result == 'ok')
            passed_sns = set(ok_histories.mapped('serial_identity_id').ids)
            ng_sns = set(histories.filtered(
                lambda h: h.result in ('ng', 'scrap')
            ).mapped('serial_identity_id').ids)
            wip_sns = set(wips.mapped('serial_identity_id').ids)
            out_dts = ok_histories.mapped('out_date')
            rows.append({
                'op_id': m_op.id,
                'step_code': m_op.x_step_code or '-',
                'name': m_op.name or '-',
                'workcenter': m_op.workcenter_id.code or '-',
                'passed': len(passed_sns),
                'wip': len(wip_sns),
                'ng': len(ng_sns),
                'qty_total': planned_qty,
                'pass_rate': round(len(passed_sns) / planned_qty * 100.0, 1)
                    if planned_qty else 0.0,
                'in_dt': min(histories.mapped('in_date')) if histories
                    and all(histories.mapped('in_date')) else None,
                'out_dt': max(out_dts) if out_dts else None,
            })
        return rows

    def _station_public(self, s):
        return {
            'step_code': s['step_code'],
            'name': s['name'],
            'workcenter': s['workcenter'],
            'passed': s['passed'],
            'wip': s['wip'],
            'ng': s['ng'],
            'qty_total': s['qty_total'],
            'pass_rate': s['pass_rate'],
            'time': self._day_str(s['out_dt']),
            'status': self._station_status(s),
        }

    def _station_status(self, s):
        if s['passed'] and not s['wip'] and \
                s['passed'] + 0.0001 >= s['qty_total']:
            return 'done'
        if s['passed'] or s['wip']:
            return 'active'
        return 'pending'

    # ------------------------------------------------------------------
    # action
    # ------------------------------------------------------------------
    @api.model
    def action_open_order_flow_screen(self):
        client_action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_order_flow_screen_client',
            raise_if_not_found=False,
        )
        if client_action:
            action = client_action.read()[0]
            action['name'] = _('Order Flow Board')
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_order_flow_screen_action',
            'name': _('Order Flow Board'),
            'target': 'fullscreen',
            'path': 'sn-wsd-order-flow-display',
            'context': {},
        }

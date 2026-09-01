# -*- coding: utf-8 -*-
"""Shop-floor station terminal services on the MES order.

Lives here (not in sn_wsd_mrp) because it filters work centers by
``sn_shop_floor_enabled``, a field of this module; sn_wsd_mrp must stay
loadable without it. One round trip per terminal action: mutate + return
the full refreshed payload."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MesOrderStationServices(models.Model):
    _inherit = 'sn.wsd.mes.order'

    @api.model
    def sn_station_floor_data(self, workcenter_id=False):
        """Everything the station terminal needs for one work center."""
        Workcenter = self.env['mrp.workcenter']
        workcenters = Workcenter.search([
            ('sn_shop_floor_enabled', '=', True),
            ('company_id', '=', self.env.company.id),
        ])
        payload = {'workcenters': [{
            'id': wc.id,
            'label': '%s [%s]' % (wc.display_name, wc.x_operation_id.display_name)
            if wc.x_operation_id else wc.display_name,
            'line_id': wc.x_production_line_id.id or False,
            'line_name': wc.x_production_line_id.name or '',
        } for wc in workcenters]}
        workcenter = workcenters.filtered(lambda wc: wc.id == workcenter_id)
        if not workcenter:
            workcenter = workcenters.filtered(lambda wc: wc.x_operation_id)[:1]
        payload['workcenter'] = {
            'id': workcenter.id,
            'name': workcenter.display_name,
            'operation': workcenter.x_operation_id.display_name or '',
        }
        payload['orders'] = []
        payload['wip'] = []
        payload['scrap_reasons'] = [{
            'id': r.id, 'name': r.display_name,
        } for r in self.env['sn.wsd.scrap.reason'].search([
            ('company_id', 'in', [self.env.company.id, False]),
        ])]
        # signed-in operators for the header badge; login=True keeps the
        # previous behaviour -- the current Odoo user's employee is the
        # terminal operator until someone switches with a PIN
        payload['employees'] = self.env[
            'hr.employee'].sn_shop_floor_get_all_employees(login=True)
        if not (workcenter and workcenter.x_operation_id):
            return payload
        operation = workcenter.x_operation_id
        order_domain = [
            ('state', 'not in', ('cancelled', 'done')),
            # offline orders stay listed: their in-progress boards must keep
            # flowing to the end operation; only feeding is gated (offline
            # orders reject new SNs inside scan_enter)
            ('x_mes_route_id.operation_ids.operation_id', '=', operation.id),
        ]
        # a line-bound work center serves exactly its own line's order
        if workcenter.x_production_line_id:
            order_domain.append(
                ('production_line_id', '=', workcenter.x_production_line_id.id))
        live = self.search(order_domain)
        Workshop = self.env['sn.mrp.workshop']
        for order in live:
            route = order.x_mes_route_id
            op = route.operation_ids.filtered(
                lambda o: o.operation_id == operation)
            # line-side destinations: workshops whose line-side location
            # belongs to the order's own warehouse
            warehouse = order.production_id.picking_type_id.warehouse_id
            workshops = Workshop.search([
                ('component_location_id', '!=', False),
                ('company_id', '=', order.company_id.id),
            ]).filtered(
                lambda ws: ws.component_location_id.warehouse_id == warehouse)
            payload['orders'].append({
                'id': order.id,
                'name': order.name,
                'state': order.state,
                'product': order.product_id.display_name,
                'partner': order.x_partner_id.display_name or '',
                'planned_qty': order.planned_qty,
                'manage_mode': order.x_manage_mode,
                'input_qty': order.x_input_qty,
                'output_qty': order.x_output_qty,
                'workorder_input_qty': order.x_workorder_input_qty,
                'done_qty': order.x_done_qty,
                'can_done': order.state == 'in_progress' and order.x_output_qty > 0,
                'workshops': [{'id': ws.id, 'name': ws.name} for ws in workshops],
                'op': {
                    'id': op.id,
                    'label': op.display_label,
                    'wip_qty': op.x_wip_qty,
                    'ok_qty': op.x_ok_qty,
                    'ng_qty': op.x_ng_qty,
                    'scrap_qty': op.x_scrap_qty,
                    'reported_qty': op.x_reported_qty,
                    'reported_ok_qty': op.x_reported_ok_qty,
                    'reported_ng_qty': op.x_reported_ng_qty,
                    'reported_scrap_qty': op.x_reported_scrap_qty,
                    'reported_effective': op.x_reported_ok_qty + op.x_reported_scrap_qty,
                    'is_input_point': op == route.x_daily_input_operation_id,
                    'is_output_point': op == route.x_daily_output_operation_id,
                    'is_workorder_input': op == route.x_workorder_input_operation_id,
                },
            })
        wip_domain = [
            ('route_operation_id.operation_id', '=', operation.id),
            ('mes_order_id', 'in', live.ids),
        ]
        wip_total = self.env['sn.wsd.serial.wip'].search_count(wip_domain)
        # browsing stays snappy on huge WIP backlogs (aging ovens...): cap
        # the rendered rows, scanning never depends on the list
        wip_rows = self.env['sn.wsd.serial.wip'].search(
            wip_domain, order='in_date desc', limit=20)
        payload['wip_total'] = wip_total
        payload['wip'] = [{
            'id': row.id,
            'sn': row.serial_identity_id.name,
            'order_id': row.mes_order_id.id,
            'order_name': row.mes_order_id.name,
            'in_date': fields.Datetime.to_string(row.in_date) if row.in_date else '',
        } for row in wip_rows]
        return payload

    @api.model
    def sn_station_scan(self, workcenter_id, code, order_id=False):
        """One scan box for the whole terminal.

        Routing: order barcode -> switch the current order; WIP SN at this
        station's operation -> return its row for the leave action; a WIP SN
        elsewhere -> hard hint; anything else -> feed the currently
        selected order (start stations only, all binding rules apply)."""
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
        code = (code or '').strip()
        if not code:
            raise ValidationError(_('Nothing to scan.'))
        Wip = self.env['sn.wsd.serial.wip']
        # 1) manufacturing-order barcode -> switch the current order
        order = self.search([('name', '=', code)])
        if order:
            return {
                'action': 'select_order',
                'order_id': order.id,
                'data': self.sn_station_floor_data(workcenter_id),
            }
        # 2) a WIP SN at this station's operation (any live order)
        wip = Wip.search([
            ('serial_identity_id.name', '=', code),
            ('route_operation_id.operation_id', '=', workcenter.x_operation_id.id),
            ('mes_order_id.state', 'not in', ('cancelled', 'done')),
        ], limit=1)
        if wip:
            return {
                'action': 'leave',
                'wip_id': wip.id,
                'order_id': wip.mes_order_id.id,
            }
        # 3) a WIP SN parked at another operation: this scan is its ARRIVAL
        #    here -- the parked operation completes OK and the board moves
        #    into this station's WIP (one scan per board per station)
        elsewhere = Wip.search([
            ('serial_identity_id.name', '=', code),
            ('mes_order_id.state', 'not in', ('cancelled', 'done')),
        ], limit=1)
        if elsewhere:
            target = elsewhere.mes_order_id
            op_row = target.x_mes_route_id.operation_ids.filtered(
                lambda o: o.operation_id == workcenter.x_operation_id)
            if not op_row:
                raise ValidationError(_(
                    'SN %(sn)s is in progress at operation %(op)s of order '
                    '%(order)s; this work center runs no operation of that '
                    'order.', sn=code,
                    op=elsewhere.route_operation_id.display_label,
                    order=target.name))
            passed = self.env['sn.wsd.serial.operation.history'].search_count([
                ('serial_identity_id', '=', elsewhere.serial_identity_id.id),
                ('mes_order_id', '=', target.id),
                ('route_operation_id', '=', op_row.id),
                ('result', '=', 'ok'),
            ])
            if passed:
                raise ValidationError(_(
                    'SN %(sn)s already passed %(op)s of order %(order)s.',
                    sn=code, op=op_row.display_label, order=target.name))
            # the parked operation hands the board over with OK; the enter
            # below validates reachability against the fresh history row.
            # Cache the fields first -- leave_station unlinks the WIP row,
            # and stale record reads would raise MissingError.
            serial_rec = elsewhere.serial_identity_id
            held = target.must_hold_for_fai(serial_rec, op_row)
            target.leave_station(serial_rec, 'ok')
            # 首件保持：出站 OK 已把到位登记落库；检验未判定时下一工序
            # 不得接板——板停在途，判定通过后再扫即接走（不得 raise 回滚
            # 到位登记）
            if held:
                return {
                    'action': 'entered',
                    'order_id': target.id,
                    'data': self.sn_station_floor_data(workcenter_id),
                    'message': target.fai_hold_message(serial_rec, held),
                }
            target.scan_enter(code, workcenter)
            if op_row.x_allow_exit:
                return self._leave_action(code, target)
            return {
                'action': 'entered',
                'order_id': target.id,
                'data': self.sn_station_floor_data(workcenter_id),
            }
        # 4) no WIP row anywhere: new SN feeding (start operations only)
        #    or an in-flow SN in transit (e.g. after a device report at a
        #    fork) being picked up by this station
        target = self.browse(order_id) if order_id \
            else self._find_live_order_for_workcenter(workcenter)
        if not target:
            raise ValidationError(_(
                'Unknown SN %(sn)s: select a MES order first (scan its '
                'barcode or tap it below).', sn=code))
        op_row = target.x_mes_route_id.operation_ids.filtered(
            lambda o: o.operation_id == workcenter.x_operation_id)
        if not op_row:
            raise ValidationError(_(
                'Work center %(wc)s runs no operation of MES order '
                '%(order)s.', wc=workcenter.display_name, order=target.name))
        History = self.env['sn.wsd.serial.operation.history']
        serial = self.env['sn.wsd.serial.identity'].search([
            ('name', '=', code),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', target.company_id.id),
        ], limit=1)
        in_flow = serial and History.search_count([
            ('serial_identity_id', '=', serial.id),
            ('mes_order_id', '=', target.id),
        ])
        if in_flow:
            passed = History.search_count([
                ('serial_identity_id', '=', serial.id),
                ('mes_order_id', '=', target.id),
                ('route_operation_id', '=', op_row.id),
                ('result', '=', 'ok'),
            ])
            if passed:
                raise ValidationError(_(
                    'SN %(sn)s already passed %(op)s of order %(order)s.',
                    sn=code, op=op_row.display_label, order=target.name))
            # 首件保持：样本在途且首件未判定 → 下道工序不得接板
            held = target.must_hold_for_fai(serial, op_row)
            if held:
                raise ValidationError(target.fai_hold_message(serial, held))
            # transit pickup: the upstream op is already OK in the history
            target.scan_enter(code, workcenter)
            if op_row.x_allow_exit:
                return self._leave_action(code, target)
            return {
                'action': 'entered',
                'order_id': target.id,
                'data': self.sn_station_floor_data(workcenter_id),
            }
        if op_row and not op_row.x_allow_entry:
            raise ValidationError(_(
                'Feeding happens at a start operation only: this work '
                'center runs %(op)s of order %(order)s. Switch to a start '
                'station to feed SN %(sn)s.',
                op=op_row.display_label, order=target.name, sn=code))
        target.scan_enter(code, workcenter)
        return {
            'action': 'entered',
            'order_id': target.id,
            'data': self.sn_station_floor_data(workcenter_id),
        }

    def _leave_action(self, code, target):
        """WIP row of `code` on `target` as the leave payload for the
        frontend (the station completes the board with its OK/NG/scrap
        mode)."""
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id.name', '=', code),
            ('mes_order_id', '=', target.id),
        ], limit=1)
        return {
            'action': 'leave',
            'wip_id': wip.id,
            'order_id': target.id,
        }

    @api.model
    def sn_station_scan_leave(self, workcenter_id, code):
        """PDA station-pass scan: same one-scan kernel as the terminal.

        Returns ``{'wip_id', 'order_id', 'leave'}``: ``leave=True`` means
        the station must complete the board now with its OK/NG/scrap mode
        (end operation, or NG/scrap on a parked board); ``leave=False``
        means the scan merely parked the board here (feeding or arrival
        pull) and the caller must NOT call sn_station_leave."""
        result = self.sn_station_scan(workcenter_id, code, False)
        if result.get('action') == 'leave':
            return {
                'wip_id': result['wip_id'],
                'order_id': result['order_id'],
                'leave': True,
            }
        # entered / select_order: nothing to leave -- surface the parked
        # WIP row (if any) so the caller can refresh its counters
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id.name', '=', (code or '').strip()),
            ('route_operation_id.operation_id', '=',
             self.env['mrp.workcenter'].browse(workcenter_id).x_operation_id.id),
            ('mes_order_id.state', 'not in', ('cancelled', 'done')),
        ], limit=1)
        return {
            'wip_id': wip.id if wip else False,
            'order_id': wip.mes_order_id.id if wip else False,
            'leave': False,
        }

    def _find_live_order_for_workcenter(self, workcenter):
        """The online station-mode MES order running through this work center."""
        if not workcenter or not workcenter.x_operation_id:
            return self.env['sn.wsd.mes.order']
        orders = self.search([
            ('state', 'not in', ('cancelled', 'done')),
            ('x_online_date', '!=', False),
            ('x_manage_mode', '=', 'station'),
        ]).filtered(lambda o: (
            not workcenter.x_production_line_id
            or o.production_line_id == workcenter.x_production_line_id))
        for order in orders:
            if order.x_mes_route_id.operation_ids.filtered(
                    lambda r: r.operation_id == workcenter.x_operation_id):
                return order
        return self.env['sn.wsd.mes.order']

    def sn_station_enter(self, sn, workcenter_id):
        """Terminal entry: this order + SN + work center."""
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
        self.scan_enter(sn, workcenter)
        return self.sn_station_floor_data(workcenter_id)

    @api.model
    def sn_station_leave(self, wip_id, result, scrap_reason_id=False,
                         ng_defect_code_id=False):
        """Terminal exit: act on one WIP row, keyed by its own work center."""
        wip = self.env['sn.wsd.serial.wip'].browse(wip_id)
        # capture before leave_station unlinks the WIP row
        workcenter_id = wip.workcenter_id.id or False
        if result == 'ok' and not wip.route_operation_id.x_allow_exit:
            # one-scan kernel: a mid-route station completes its boards when
            # the NEXT station scans them (arrival pull); an OK scan on a
            # board still parked here would write the OK prematurely
            raise ValidationError(_(
                'SN %(sn)s is parked at %(op)s of order %(order)s (not the '
                'end operation): it flows on when the next station scans '
                'it. Use NG or scrap here if this station rejects it.',
                sn=wip.serial_identity_id.name,
                op=wip.route_operation_id.display_label,
                order=wip.mes_order_id.name))
        reason = self.env['sn.wsd.scrap.reason'].browse(
            int(scrap_reason_id) if scrap_reason_id else False)
        defect = self.env['sn.wsd.quality.defect.code'].browse(
            int(ng_defect_code_id) if ng_defect_code_id else False)
        finished = wip.mes_order_id.leave_station(
            wip.serial_identity_id, result, scrap_reason=reason,
            ng_defect=defect)
        return {
            'finished': finished,
            'data': self.sn_station_floor_data(workcenter_id),
        }

    @api.model
    def sn_resolve_ng_defect(self, code):
        """Resolve a scanned defect code for the two-step NG flow.

        Exact code match first, then exact name, within the terminal
        company. Returns {'id', 'name'} or False when nothing matches."""
        code = (code or '').strip()
        if not code:
            return False
        DefectCode = self.env['sn.wsd.quality.defect.code']
        base = [('company_id', '=', self.env.company.id)]
        defect = (
            DefectCode.search(base + [('code', '=ilike', code)], limit=1)
            or DefectCode.search(base + [('name', '=ilike', code)], limit=1))
        if not defect:
            return False
        return {'id': defect.id, 'name': defect.display_name}

    def sn_station_report(self, workcenter_id, qty_ok, qty_ng=0.0, qty_scrap=0.0,
                          scrap_reason_id=False):
        """Terminal reporting: this order + work center + three counters."""
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
        route_operation = self._resolve_route_operation(workcenter)
        reason = self.env['sn.wsd.scrap.reason'].browse(
            int(scrap_reason_id) if scrap_reason_id else False)
        self.report_operation_qty(route_operation, qty_ok, qty_ng, qty_scrap,
                                  scrap_reason=reason)
        return self.sn_station_floor_data(workcenter_id)

    def sn_station_done(self, qty, destination='stock', workshop_id=False):
        """Terminal completion (完工入库): this order + quantity +
        destination. Line-side workshops come from the order's warehouse."""
        # the select's value arrives as a string over RPC
        workshop = self.env['sn.mrp.workshop'].browse(
            int(workshop_id) if workshop_id else False)
        self.sudo().action_complete(qty, destination, workshop=workshop)
        return {
            'done_qty': self.x_done_qty,
            'state': self.state,
        }


class MrpProductionShopFloor(models.Model):
    _inherit = 'mrp.production'

    def action_open_sn_shop_floor(self):
        self.ensure_one()
        # direct client action dict: ir.actions.actions lost _for_xmlid in 19
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_shop_floor',
            'name': _('Shop Floor'),
            'target': 'fullscreen',
            'context': {'production_id': self.id},
        }

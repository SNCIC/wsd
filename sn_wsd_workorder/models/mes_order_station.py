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
        # batch station pass entry visibility: managers only (the
        # service double-checks the group server-side)
        payload['can_batch_pass'] = self.env.user.has_group(
            'mrp.group_mrp_manager')
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
        # strict one-scan-per-station keeps no parking rows: a board sits at
        # the operation of its latest pass record (in progress while an NG
        # decision is pending). The floor counters and the "in progress
        # here" list follow that definition, not the WIP table.
        current_rows = {}
        for order in live:
            current_rows.update(order.serial_current_route_operations())

        def _still_in_flow(row):
            # finished (OK through the end operation) and scrapped boards
            # have left the flow: not "in progress" anywhere
            if row.result == 'scrap':
                return False
            return not (row.result == 'ok'
                        and row.route_operation_id.x_allow_exit)

        current_rows = {
            serial_id: row for serial_id, row in current_rows.items()
            if _still_in_flow(row)}
        op_current = {}
        for row in current_rows.values():
            op_current[row.route_operation_id.id] = \
                op_current.get(row.route_operation_id.id, 0) + 1
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
                    'wip_qty': op_current.get(op.id, 0),
                    'entered_qty': op.x_entered_qty,
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
        current = [
            row for row in current_rows.values()
            if row.route_operation_id.operation_id == operation]
        current.sort(
            key=lambda r: (r.out_date or r.in_date or fields.Datetime.now(),
                           r.id), reverse=True)
        # browsing stays snappy on huge backlogs (aging ovens...): cap the
        # rendered rows, scanning never depends on the list
        wip_rows = current[:20]
        serial_ids = [row.serial_identity_id.id for row in wip_rows]
        wip_by_serial = {}
        if serial_ids:
            wip_by_serial = {
                wip.serial_identity_id.id: wip.id
                for wip in self.env['sn.wsd.serial.wip'].search([
                    ('serial_identity_id', 'in', serial_ids)])
            }
        payload['wip_total'] = len(current)
        payload['wip'] = [{
            'id': row.id,
            # real WIP id only while the board waits for an NG decision;
            # the leave endpoint needs it for the two-step NG flow
            'wip_id': wip_by_serial.get(row.serial_identity_id.id, False),
            'sn': row.serial_identity_id.name,
            'order_id': row.mes_order_id.id,
            'order_name': row.mes_order_id.name,
            'result': row.result,
            'in_date': fields.Datetime.to_string(
                row.out_date or row.in_date) if (row.out_date or row.in_date)
                else '',
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
        # 3) a WIP SN at another operation: strict one-scan-per-station --
        #    the board must finish (OK/NG/scrap) the station it sits at
        #    before any other station can scan it. No arrival pull: the
        #    scanned station records its own verdict, never the previous one.
        elsewhere = Wip.search([
            ('serial_identity_id.name', '=', code),
            ('mes_order_id.state', 'not in', ('cancelled', 'done')),
        ], limit=1)
        if elsewhere:
            raise ValidationError(_(
                'SN %(sn)s is in progress at operation %(op)s of order '
                '%(order)s; it must leave that station first.',
                sn=code, op=elsewhere.route_operation_id.display_label,
                order=elsewhere.mes_order_id.name))
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
            blocked = target._pass_scan_blocked(serial, op_row)
            if blocked:
                raise ValidationError(blocked)
            # one scan = one station pass: enter here, the caller completes
            # this very station with its OK/NG/scrap mode (no parking at the
            # successor, no pull from an earlier station)
            target.scan_enter(code, workcenter)
            return self._leave_action(code, target)
        if op_row and not op_row.x_allow_entry:
            raise ValidationError(_(
                'Feeding happens at a start operation only: this work '
                'center runs %(op)s of order %(order)s. Switch to a start '
                'station to feed SN %(sn)s.',
                op=op_row.display_label, order=target.name, sn=code))
        target.scan_enter(code, workcenter)
        return self._leave_action(code, target)

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

        Returns ``{'wip_id', 'order_id', 'leave'}``: a successful scan always
        leaves the board in progress at the scanned station, so the caller
        completes this very station with its OK/NG/scrap mode."""
        result = self.sn_station_scan(workcenter_id, code, False)
        if result.get('action') == 'leave':
            return {
                'wip_id': result['wip_id'],
                'order_id': result['order_id'],
                'leave': True,
            }
        # select_order: the scan switched the terminal order, nothing to
        # complete (an unknown SN raises before reaching this branch)
        return {
            'wip_id': False,
            'order_id': result.get('order_id') or False,
            'leave': False,
        }

    @api.model
    def sn_station_clear(self, workcenter_id, code, order_id=False):
        """Station clear entry (清除过站) shared by the PDA and the terminal.

        Resolves the scanned SN against the live orders of this work center
        -- the explicitly selected one, else the single order holding the
        SN's pass records -- then runs the one clear kernel
        ``action_clear_station_pass`` (managers only, audit logged).
        Returns the cleared history-row count and the refreshed floor
        payload."""
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
        code = (code or '').strip()
        if not code:
            raise ValidationError(_('Nothing to scan.'))
        serial = self.env['sn.wsd.serial.identity'].search([
            ('name', '=', code),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not serial:
            raise ValidationError(_(
                'SN %(sn)s is unknown; SNs register themselves when they '
                'enter a start operation.', sn=code))
        History = self.env['sn.wsd.serial.operation.history']
        Wip = self.env['sn.wsd.serial.wip']
        orders = (
            History.search([('serial_identity_id', '=', serial.id)])
            .mapped('mes_order_id')
            | Wip.search([('serial_identity_id', '=', serial.id)])
            .mapped('mes_order_id')
        ).filtered(lambda o: o.state not in ('cancelled', 'done'))
        if workcenter.x_operation_id:
            orders = orders.filtered(lambda o: o.x_mes_route_id.operation_ids.filtered(
                lambda r: r.operation_id == workcenter.x_operation_id))
        if order_id:
            # the terminal picked its order: clear there even when the SN's
            # rows sit elsewhere -- the kernel then says "no records on it"
            orders = orders.filtered(lambda o: o.id == order_id) \
                or self.browse(order_id)
        elif len(orders) > 1:
            raise ValidationError(_(
                'SN %(sn)s has station-pass records on several live MES '
                'orders (%(orders)s); select one order first.',
                sn=code, orders=', '.join(orders.mapped('name'))))
        order = orders[:1] or self._find_live_order_for_workcenter(workcenter)
        if not order:
            raise ValidationError(_(
                'SN %(sn)s has no station-pass records on a live MES order '
                'of this work center.', sn=code))
        cleared = order.action_clear_station_pass(serial)
        return {
            'cleared': cleared,
            'data': self.sn_station_floor_data(workcenter_id),
        }

    def sn_station_enter(self, sn, workcenter_id):
        """Terminal entry: this order + SN + work center."""
        workcenter = self.env['mrp.workcenter'].browse(workcenter_id)
        self.scan_enter(sn, workcenter)
        return self.sn_station_floor_data(workcenter_id)

    @api.model
    def sn_station_leave(self, wip_id, result, scrap_reason_id=False,
                         ng_defect_code_id=False):
        """Terminal exit: act on one WIP row, keyed by its own work center.

        Strict one-scan-per-station: every operation completes on its own
        scan, so OK is accepted on any operation (end or mid-route)."""
        wip = self.env['sn.wsd.serial.wip'].browse(wip_id)
        # capture before leave_station unlinks the WIP row
        workcenter_id = wip.workcenter_id.id or False
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

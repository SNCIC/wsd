# -*- coding: utf-8 -*-
"""Private (per-MES-order) process route — the executable form of the common
route template.

The common route lives as a JSON flow graph (editing-friendly). When a MES
order is created, that graph is materialized here into plain rows + edges so
SN execution and operation reporting only ever touch indexed tables:

  sn.wsd.mes.order.route           per-order container (counters snapshot)
  sn.wsd.mes.order.route.operation one row per operation, blocked_by = edges
  sn.wsd.serial.operation.history  append-only SN station history (station mode)
  sn.wsd.serial.wip                current station of each SN (station mode)
  sn.wsd.mes.operation.report      per-operation reported qty (report mode)

Rows with execution records (history/report) are frozen: syncing from the
common route AND local edits never mutate them, so an SN's walked path never
deforms. Local edits set ``is_customized``: the order then stops following the
common route automatically (manual sync still available) and nothing ever
flows back into the common route.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MesOrderRoute(models.Model):
    """Private route container of a MES order (1:1)."""
    _name = 'sn.wsd.mes.order.route'
    _description = 'MES Order Process Route'
    _order = 'mes_order_id, id'
    _rec_name = 'mes_order_id'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', required=True, index=True, ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company', related='mes_order_id.company_id', store=True, index=True,
    )
    manage_mode = fields.Selection(
        related='mes_order_id.x_manage_mode', store=True, index=True,
    )
    route_id = fields.Many2one(
        'sn.wsd.process.route', string='Source Common Route', index=True,
        ondelete='set null', readonly=True,
    )
    source_version = fields.Integer(readonly=True)
    is_customized = fields.Boolean(
        string='Customized',
        help='Set on the first local edit: the order stops following the '
             'common route automatically until a manual sync accepts it back.',
    )
    operation_ids = fields.One2many(
        'sn.wsd.mes.order.route.operation', 'mes_route_id',
    )
    # Counter configuration snapshot — same counters as the common route, but
    # pointing at the private operation rows so statistics join straight onto
    # execution records.
    x_daily_input_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='制令单投入工序', ondelete='restrict',
    )
    x_daily_output_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='制令单产出工序', ondelete='restrict',
    )
    x_material_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='物料关联工序', ondelete='restrict',
    )
    x_workorder_input_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='工单投入工序', ondelete='restrict',
    )
    x_aging_start_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='老化开始工序', ondelete='restrict',
    )
    x_aging_end_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='老化结束工序', ondelete='restrict',
    )

    _order_route_uniq = models.Constraint(
        'unique(mes_order_id)',
        'A MES order can only have one private process route.',
    )

    # ------------------------------------------------------------------
    # build / sync from the common route
    # ------------------------------------------------------------------
    def _resolve_common_route(self, mes_order):
        """Resolve the common route for the order's product drawing number.

        Fail hard — no fallback (same policy as the cycle gate)."""
        drawing = mes_order.product_id.x_drawing_no
        workshop = mes_order.production_line_id.workshop_id
        route = self.env['sn.wsd.process.route']._find_current_route_by_drawing_no(
            drawing, mes_order.company_id.id, workshop_id=workshop.id)
        if not route:
            raise ValidationError(_(
                'No released process route is bound to drawing number "%(drawing)s". '
                'Bind the route first.',
                drawing=drawing or _('(empty)'),
            ))
        graph = route._flow_graph()
        if not graph['nodes']:
            raise ValidationError(_(
                'The process route bound to drawing number "%(drawing)s" has no '
                'flow graph yet. Draw the flow before creating MES orders.',
                drawing=drawing,
            ))
        return route, graph

    def _build_from_common(self, mes_order):
        """Initial materialization: create container + rows + edges + counters."""
        route, graph = self._resolve_common_route(mes_order)
        mes_route = self.create({
            'mes_order_id': mes_order.id,
            'route_id': route.id,
            'source_version': route.version,
        })
        mes_route._apply_graph(graph, route)
        return mes_route

    def _apply_graph(self, graph, common_route=None):
        """Make the private rows match `graph`.

        Rows carrying execution records are frozen (kept as-is, edges
        included); everything else follows the graph. With ``common_route``
        (sync) the source and counters follow the common route; without it
        (local edit) they are preserved and only validated."""
        self.ensure_one()
        nodes = graph['nodes']
        edges = graph['edges'] or []
        # Cycle gate: a cyclic graph is rejected outright, no fallback.
        adjacency = {}
        for edge in edges:
            src, tgt = edge.get('source'), edge.get('target')
            if src and tgt and src != tgt:
                adjacency.setdefault(tgt, set()).add(src)
        self.env['sn.wsd.process.route']._check_route_graph_cycle(adjacency)

        RouteOp = self.env['sn.wsd.mes.order.route.operation']
        existing = RouteOp.search([('mes_route_id', '=', self.id)])
        frozen = existing._has_execution_records()
        by_op = {op.operation_id.id: op for op in existing}

        node_by_op = {}
        for node in nodes:
            op_id = node.get('operation_id')
            if op_id:
                node_by_op[op_id] = node

        removed = existing.filtered(
            lambda op: op not in frozen and op.operation_id.id not in node_by_op)
        if removed & frozen:
            raise ValidationError(_(
                'Operations with execution records cannot be removed: %s',
                ', '.join((removed & frozen).mapped('display_label')),
            ))
        # counters pointing at rows about to be removed:
        # - sync mode: detach them now, the common version re-assigns below;
        # - local edit: refuse (the counters are part of the configuration).
        counter_fields = ('x_daily_input_operation_id', 'x_daily_output_operation_id',
                          'x_material_operation_id', 'x_workorder_input_operation_id',
                          'x_aging_start_operation_id', 'x_aging_end_operation_id')
        if common_route:
            vals_clear = {f: False for f in counter_fields if self[f] and self[f] in removed}
            if vals_clear:
                self.write(vals_clear)
        else:
            clash = [(f, self[f]) for f in counter_fields if self[f] and self[f] in removed]
            if clash:
                raise ValidationError(_(
                    'Counter operation %(op)s is no longer part of the route; '
                    'clear or move it before saving.',
                    op=clash[0][1].display_label,
                ))
        removed.unlink()

        for op_id, node in node_by_op.items():
            vals = {
                'operation_id': op_id,
                'name': node.get('name'),
                'x_step_code': node.get('step_code'),
                'x_station_type': node.get('x_station_type'),
                'sequence': node.get('sequence') or 100,
                'time_cycle_manual': node.get('time_cycle_manual') or 0.0,
                'x_allow_entry': bool(node.get('x_allow_entry')),
                'x_allow_exit': bool(node.get('x_allow_exit')),
                'is_input': bool(node.get('x_allow_entry')),
                'x_canvas_x': node.get('x'),
                'x_canvas_y': node.get('y'),
            }
            current = by_op.get(op_id)
            if current and current in frozen:
                continue
            if current:
                current.write(vals)
            else:
                RouteOp.create(dict(vals, mes_route_id=self.id))

        rows = RouteOp.search([('mes_route_id', '=', self.id)])
        row_by_op = {op.operation_id.id: op for op in rows}
        uid_to_op = {}
        for node in nodes:
            op_id = node.get('operation_id')
            if op_id and node.get('uid') is not None:
                uid_to_op[str(node['uid'])] = op_id
        new_deps = {}
        for edge in edges:
            src_op = uid_to_op.get(str(edge.get('source')))
            tgt_op = uid_to_op.get(str(edge.get('target')))
            if src_op and tgt_op:
                new_deps.setdefault(tgt_op, set()).add(src_op)
        for row in rows:
            if row in frozen:
                continue
            fresh_ids = [row_by_op[o].id for o in new_deps.get(row.operation_id.id, ()) if o in row_by_op]
            # edges pointing at frozen rows are kept as-is (their side is frozen)
            kept_frozen = row.blocked_by_ids.filtered(lambda r: r in frozen)
            row.blocked_by_ids = kept_frozen | RouteOp.browse(fresh_ids)

        if common_route:
            counter_map = {
                'x_daily_input_operation_id': common_route.x_daily_input_operation_id,
                'x_daily_output_operation_id': common_route.x_daily_output_operation_id,
                'x_material_operation_id': common_route.x_material_operation_id,
                'x_workorder_input_operation_id': common_route.x_workorder_input_operation_id,
                'x_aging_start_operation_id': common_route.x_aging_start_operation_id,
                'x_aging_end_operation_id': common_route.x_aging_end_operation_id,
            }
            vals = {'route_id': common_route.id, 'source_version': common_route.version}
            for fname, common_op in counter_map.items():
                if not common_op:
                    vals[fname] = False
                    continue
                target = row_by_op.get(common_op.id)
                if target is None:
                    raise ValidationError(_(
                        'Counter operation "%(op)s" is not part of the route flow '
                        'graph of route %(route)s.',
                        op=common_op.display_name, route=common_route.display_name,
                    ))
                current = self[fname]
                if current and current in frozen:
                    continue
                vals[fname] = target.id
            self.write(vals)
        else:
            # Local edit: counters must still point at rows of this graph.
            row_ids = set(rows.ids)
            for fname in ('x_daily_input_operation_id', 'x_daily_output_operation_id',
                          'x_material_operation_id', 'x_workorder_input_operation_id',
                          'x_aging_start_operation_id', 'x_aging_end_operation_id'):
                if self[fname] and self[fname].id not in row_ids:
                    raise ValidationError(_(
                        'Counter operation %(op)s is no longer part of the route; '
                        'clear or move it before saving.',
                        op=self[fname].display_label,
                    ))

    def save_route_graph(self, graph):
        """Local edit entry: apply the graph to the private route only.

        Never touches the common route; marks the order as customized."""
        self.ensure_one()
        self._apply_graph(graph)
        self.is_customized = True
        return True

    # ------------------------------------------------------------------
    # canvas payload + execution state for the front-end
    # ------------------------------------------------------------------
    def get_route_graph(self):
        """Render the private route as {nodes, edges} for the flow editor."""
        self.ensure_one()
        nodes, edges = [], []
        for op in self.operation_ids:
            nodes.append({
                'uid': op.id,
                'id': op.id,
                'operation_id': op.operation_id.id,
                'name': op.name,
                'step_code': op.x_step_code,
                'sequence': op.sequence,
                'x_station_type': op.x_station_type,
                'is_input': op.is_input,
                'x_allow_entry': op.x_allow_entry,
                'x_allow_exit': op.x_allow_exit,
                'x': op.x_canvas_x,
                'y': op.x_canvas_y,
            })
        for op in self.operation_ids:
            for dep in op.blocked_by_ids:
                edges.append({'source': dep.id, 'target': op.id})
        return {'nodes': nodes, 'edges': edges}

    def _execution_state_map(self):
        """op row id -> 'done' | 'wip' | 'ng' | 'partial' | None (+ qty info).

        Reads the stored per-operation counters — no per-node searches."""
        self.ensure_one()
        result = {}
        if self.manage_mode == 'report':
            planned = self.mes_order_id.planned_qty or 0.0
            for op in self.operation_ids:
                effective = op.x_reported_ok_qty + op.x_reported_scrap_qty
                if effective + 0.00001 >= planned and planned > 0:
                    result[op.id] = 'done'
                elif op.x_reported_qty > 0:
                    result[op.id] = 'partial:%s/%s' % (effective, planned)
                else:
                    result[op.id] = None
            return result
        for op in self.operation_ids:
            state = None
            if op.x_ok_qty:
                state = 'done'
            elif op.x_ng_qty:
                state = 'ng'
            if op.x_wip_qty:
                state = 'wip'
            result[op.id] = state
        return result


class MesOrderRouteOperation(models.Model):
    """One operation row of a private route (a waypoint on the map)."""
    _name = 'sn.wsd.mes.order.route.operation'
    _description = 'MES Order Route Operation'
    _order = 'mes_route_id, sequence, id'
    _rec_name = 'display_label'

    mes_route_id = fields.Many2one(
        'sn.wsd.mes.order.route', required=True, index=True, ondelete='cascade',
    )
    mes_order_id = fields.Many2one(
        related='mes_route_id.mes_order_id', store=True, index=True,
    )
    company_id = fields.Many2one(
        related='mes_route_id.company_id', store=True, index=True,
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation', required=True, index=True, ondelete='restrict',
    )
    name = fields.Char()
    display_label = fields.Char(compute='_compute_display_label')
    x_step_code = fields.Char()
    x_station_type = fields.Selection(
        related='operation_id.x_station_type', store=True,
    )
    sequence = fields.Integer(default=100)
    time_cycle_manual = fields.Float(default=60.0)
    x_canvas_x = fields.Integer(
        string='Canvas X', aggregator=None,
        help='Saved canvas position so the flow editor restores the layout.',
    )
    x_canvas_y = fields.Integer(
        string='Canvas Y', aggregator=None,
        help='Saved canvas position so the flow editor restores the layout.',
    )
    x_allow_entry = fields.Boolean(
        string='Start Operation',
        help="Manual flag, same semantics as the common route editor: SNs "
             "are fed into the order from operations flagged here.",
    )
    x_allow_exit = fields.Boolean(string='End Operation')
    is_input = fields.Boolean(
        string='Input Operation',
        help="Mirror of x_allow_entry kept for search/execution convenience.",
    )
    blocked_by_ids = fields.Many2many(
        'sn.wsd.mes.order.route.operation',
        'mes_order_route_operation_rel', 'dest_id', 'src_id',
        string='Preceded By',
        help="Edges of the flow graph: this operation is reachable once ANY "
             "predecessor is completed (parallel branches are OR-joined).",
    )
    successor_ids = fields.Many2many(
        'sn.wsd.mes.order.route.operation',
        'mes_order_route_operation_rel', 'src_id', 'dest_id',
        string='Successors',
    )
    serial_history_ids = fields.One2many(
        'sn.wsd.serial.operation.history', 'route_operation_id',
    )
    serial_wip_ids = fields.One2many(
        'sn.wsd.serial.wip', 'route_operation_id',
    )
    report_ids = fields.One2many(
        'sn.wsd.mes.operation.report', 'route_operation_id',
    )
    # Execution counters (event-driven stored computes): each pass/report
    # rewrites this row inside the same transaction, so the flow canvas,
    # order quantities and station terminals read them with zero aggregation.
    x_wip_qty = fields.Integer(
        string='In Progress', compute='_compute_pass_statistics', store=True,
        help='SNs currently at this operation.',
    )
    x_ok_qty = fields.Integer(
        string='Passed', compute='_compute_pass_statistics', store=True,
        help='SNs that left this operation with result OK.',
    )
    x_ng_qty = fields.Integer(
        string='Rejected', compute='_compute_pass_statistics', store=True,
        help='SNs that left this operation with result NG.',
    )
    x_scrap_qty = fields.Float(
        string='Scrapped', compute='_compute_pass_statistics', store=True,
        help='Scrapped amount: SNs that left with result Scrap (station '
             'mode) or accumulated scrap reports (report mode).',
    )
    x_reported_qty = fields.Float(
        string='Reported Quantity', compute='_compute_pass_statistics', store=True,
        help='Accumulated reported quantity (report mode): OK + NG + scrap, '
             'the invested amount.',
    )
    x_reported_ok_qty = fields.Float(
        string='Reported OK', compute='_compute_pass_statistics', store=True,
        help='Accumulated OK reported quantity (report mode).',
    )
    x_reported_ng_qty = fields.Float(
        string='Reported NG', compute='_compute_pass_statistics', store=True,
        help='Accumulated NG reported quantity (report mode).',
    )
    x_reported_scrap_qty = fields.Float(
        string='Reported Scrap', compute='_compute_pass_statistics', store=True,
        help='Accumulated scrap reported quantity (report mode).',
    )
    x_yield_rate = fields.Float(
        string='Yield Rate', compute='_compute_pass_statistics', store=True,
        help='OK passes divided by OK + NG passes (scrap included in '
             'report mode).',
    )

    _route_op_uniq = models.Constraint(
        'unique(mes_route_id, operation_id)',
        'Each operation appears at most once in a MES order route.',
    )

    @api.depends('name', 'x_step_code', 'operation_id')
    def _compute_display_label(self):
        for op in self:
            op.display_label = ' / '.join(
                filter(None, [op.x_step_code, op.name])) or op.operation_id.display_name

    @api.depends('serial_history_ids.result', 'serial_wip_ids',
                 'report_ids.qty_ok', 'report_ids.qty_ng', 'report_ids.qty_scrap')
    def _compute_pass_statistics(self):
        for op in self:
            reports = op.report_ids
            ok_qty = sum(reports.mapped('qty_ok'))
            ng_qty = sum(reports.mapped('qty_ng'))
            scrap_qty = sum(reports.mapped('qty_scrap'))
            op.x_reported_ok_qty = ok_qty
            op.x_reported_ng_qty = ng_qty
            op.x_reported_scrap_qty = scrap_qty
            op.x_reported_qty = ok_qty + ng_qty + scrap_qty
            op.x_wip_qty = len(op.serial_wip_ids)
            histories = op.serial_history_ids
            op.x_ok_qty = len(histories.filtered(lambda h: h.result == 'ok'))
            op.x_ng_qty = len(histories.filtered(lambda h: h.result == 'ng'))
            if op.mes_route_id.manage_mode == 'report':
                op.x_scrap_qty = scrap_qty
                passed = ok_qty + ng_qty + scrap_qty
                op.x_yield_rate = (ok_qty / passed) if passed else 0.0
            else:
                op.x_scrap_qty = len(histories.filtered(lambda h: h.result == 'scrap'))
                passed = op.x_ok_qty + op.x_ng_qty + op.x_scrap_qty
                op.x_yield_rate = (op.x_ok_qty / passed) if passed else 0.0

    def _has_execution_records(self):
        """Rows already walked/reported by SNs — frozen for sync & edits."""
        History = self.env['sn.wsd.serial.operation.history']
        Report = self.env['sn.wsd.mes.operation.report']
        busy = History.search([('route_operation_id', 'in', self.ids)]).mapped('route_operation_id')
        busy |= Report.search([('route_operation_id', 'in', self.ids)]).mapped('route_operation_id')
        return busy

    # ------------------------------------------------------------------
    # reachability (OR-join semantics: ANY predecessor completed suffices)
    # ------------------------------------------------------------------
    def _completed_operations(self, mes_order, serial_identity=None):
        """Set of completed operation rows for the reachability check.

        station mode: history rows with result='ok' for this SN in this order.
        report mode : operations whose reported qty reached the order's plan.
        """
        if mes_order.x_manage_mode == 'report':
            done_ids = set()
            for op in self:
                effective = sum(op.report_ids.mapped('qty_ok')) \
                    + sum(op.report_ids.mapped('qty_scrap'))
                if effective + 0.00001 >= mes_order.planned_qty:
                    done_ids.add(op.id)
            return self.browse(done_ids)
        domain = [
            ('mes_order_id', '=', mes_order.id),
            ('route_operation_id', 'in', self.ids),
            ('result', '=', 'ok'),
        ]
        if serial_identity:
            domain.append(('serial_identity_id', '=', serial_identity.id))
        return self.env['sn.wsd.serial.operation.history'].search(domain).mapped('route_operation_id')

    def _reachable_operations(self, mes_order, serial_identity=None):
        done = self._completed_operations(mes_order, serial_identity)
        return self.filtered(lambda op: not op.blocked_by_ids or op.blocked_by_ids & done)


class SerialOperationHistory(models.Model):
    """Append-only record: SN passed this operation of this MES order.

    Only result='ok' counts as completed for reachability; 'ng' blocks the
    successors until handled (repair/scrap flows are out of scope for now).
    """
    _name = 'sn.wsd.serial.operation.history'
    _description = 'SN Operation History'
    _order = 'out_date desc, id desc'

    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', required=True, index=True, ondelete='restrict',
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', required=True, index=True, ondelete='restrict',
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', required=True, index=True, ondelete='restrict',
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Work Center', index=True, ondelete='set null',
        help='Work center where the SN entered this operation (copied from '
             'the WIP row on leave, kept for equipment-level traceability).',
    )
    result = fields.Selection(
        [('ok', 'OK'), ('ng', 'NG'), ('scrap', 'Scrap'), ('skipped', 'Skipped')],
        required=True, index=True,
    )
    in_date = fields.Datetime()
    out_date = fields.Datetime(default=fields.Datetime.now)
    company_id = fields.Many2one(
        'res.company', related='mes_order_id.company_id', store=True, index=True,
    )

    _history_uniq = models.Constraint(
        'unique(serial_identity_id, route_operation_id)',
        'An SN passes an operation of a MES order only once (re-entry rules '
        'are handled at the operation level, not by duplicating history).',
    )


class SerialWip(models.Model):
    """Where an SN currently is — at most one row per SN."""
    _name = 'sn.wsd.serial.wip'
    _description = 'SN Work In Progress'
    _order = 'in_date desc, id desc'

    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', required=True, index=True, ondelete='restrict',
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', required=True, index=True, ondelete='restrict',
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', required=True, index=True, ondelete='restrict',
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Work Center', index=True, ondelete='set null',
        help='Work center where the SN is currently being processed.',
    )
    in_date = fields.Datetime(default=fields.Datetime.now)
    company_id = fields.Many2one(
        'res.company', related='mes_order_id.company_id', store=True, index=True,
    )

    _wip_serial_uniq = models.Constraint(
        'unique(serial_identity_id)',
        'An SN can be in progress at only one operation at a time.',
    )


class MesOperationReport(models.Model):
    """Coarse mode: per-operation reported quantities (no SN tracking).

    One report carries the three counters of a batch: OK (counts towards
    completion), NG (statistic only -- rework re-reports as OK later) and
    Scrap (consumes quota and generates native scrap orders)."""
    _name = 'sn.wsd.mes.operation.report'
    _description = 'MES Operation Report'
    _order = 'id desc'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', required=True, index=True, ondelete='cascade',
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', required=True, index=True, ondelete='restrict',
    )
    qty_ok = fields.Float(string='OK Quantity', required=True)
    qty_ng = fields.Float(
        string='NG Quantity',
        help='Reworkable defects of this batch. Pure statistic: it does '
             'not consume the plan quota; reworked boards are re-reported '
             'as OK.',
    )
    qty_scrap = fields.Float(
        string='Scrap Quantity',
        help='Unrecoverable loss of this batch. Consumes the plan quota '
             'and generates a native scrap order per component.',
    )
    reported_by = fields.Many2one(
        'res.users', default=lambda self: self.env.user,
    )
    reported_at = fields.Datetime(default=fields.Datetime.now)
    company_id = fields.Many2one(
        'res.company', related='mes_order_id.company_id', store=True, index=True,
    )

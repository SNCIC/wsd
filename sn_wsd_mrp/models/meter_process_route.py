import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .constants import PROCESS_SECTION_SELECTION, STATION_TYPE_SELECTION


class SnWsdOperation(models.Model):
    _name = 'sn.wsd.operation'
    _description = 'Standard Operation'
    _order = 'code, id'
    _check_company_auto = True

    code = fields.Char(string='Operation Code', index=True, copy=False)
    name = fields.Char(string='Operation', required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    x_workcenter_ids = fields.Many2many(
        'mrp.workcenter',
        'sn_wsd_operation_workcenter_rel',
        'operation_id',
        'workcenter_id',
        string='Work Centers',
        check_company=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        help='Work centers that can execute this operation.',
    )
    x_station_type = fields.Selection(
        STATION_TYPE_SELECTION,
        string='Operation Type',
        default='assembly',
        required=True,
    )
    x_process_section = fields.Selection(
        PROCESS_SECTION_SELECTION,
        string='Process Section',
    )
    time_mode = fields.Selection(
        [('manual', 'Fixed'), ('auto', 'Computed')],
        string='Duration Computation',
        default='manual',
        required=True,
    )
    time_mode_batch = fields.Integer(string='Computed On Last', default=10)
    time_cycle_manual = fields.Float(string='Manual Duration', default=60)
    cost_mode = fields.Selection(
        [('actual', 'Actual time'), ('estimated', 'Theorical time')],
        string='Cost Based On',
        default='actual',
        required=True,
    )
    x_max_test_count = fields.Integer(
        string='Max Test Count',
        required=True,
        default=1,
    )
    note = fields.Text(string='Notes')

    _operation_code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The operation code must be unique per company.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                code = self.env['ir.sequence'].next_by_code('sn.wsd.operation')
                if not code:
                    raise UserError(_(
                        'The coding rule is not configured. Please create an ir.sequence '
                        'with code %s in Settings > Technical > Sequences.'
                    ) % 'sn.wsd.operation')
                vals['code'] = code
        return super().create(vals_list)

class MeterProcessRoute(models.Model):
    _name = 'sn.wsd.process.route'
    _description = 'Meter Process Route'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Route Name', required=True)
    code = fields.Char(string='Route Code', required=True, index=True)
    x_drawing_no = fields.Char(
        string='Drawing No.',
        index=True,
        tracking=True,
        help='Stable drawing number linking this route to its product. '
             'This is the joining key shared with the BOM (both resolve via 图号).',
    )
    version = fields.Integer(
        string='Version',
        default=0,
        tracking=True,
        copy=False,
        help='Current flow version. Bumps only when the flow graph changes on a '
             'confirmed route; editing other fields never bumps it. 0 means the '
             'route has never been confirmed.',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    # ---- standalone confirmation lifecycle (not tied to PLM) ----
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')],
        string='State',
        default='draft',
        required=True,
        index=True,
        tracking=True,
        help='Draft: being edited (flow changes are pending). Confirmed: current '
             'version is live; saving a changed flow graph moves it back to Draft '
             'until confirmed or cancelled.',
    )
    confirmed_by = fields.Many2one(
        'res.users',
        string='Confirmed By',
        copy=False,
        readonly=True,
    )
    confirmed_date = fields.Datetime(
        string='Confirmed On',
        copy=False,
        readonly=True,
    )
    x_version_ids = fields.One2many(
        'sn.wsd.process.route.version',
        'route_id',
        string='Flow Versions',
        copy=False,
    )
    x_version_count = fields.Integer(
        string='Version Count',
        compute='_compute_x_version_count',
    )
    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Workshop',
        required=True,
        check_company=True,
        index=True,
    )
    meter_product_type = fields.Selection(
        [
            ('single_phase', 'Single Phase'),
            ('three_phase', 'Three Phase'),
            ('collector', 'Collector'),
            ('terminal', 'Terminal'),
            ('other', 'Other'),
        ],
        string='Meter Product Type',
    )
    x_production_side = fields.Selection(
        [('single', 'Single'), ('top', 'Top (T)'), ('bottom', 'Bottom (B)')],
        string='Production Side',
    )
    x_production_stage = fields.Selection(
        [('smt', 'SMT'), ('insertion', 'Insertion'), ('assembly', 'Assembly')],
        string='Production Stage',
    )
    x_is_default = fields.Boolean(
        string='Default',
        default=False,
    )
    x_predecessor_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Predecessor Route',
        ondelete='set null',
        index=True,
    )
    bom_ids = fields.One2many(
        'mrp.bom',
        'x_process_route_id',
        string='Linked Bills of Material',
    )
    bom_count = fields.Integer(
        string='Linked BoM Count',
        compute='_compute_route_counts',
    )
    route_operation_ids = fields.One2many(
        'sn.wsd.process.route.operation',
        'route_id',
        string='Route Operations',
        copy=True,
    )
    operation_count = fields.Integer(
        string='Route Operation Count',
        compute='_compute_route_counts',
    )
    route_flow_html = fields.Html(
        string='Route Flow Diagram',
        compute='_compute_route_flow_html',
    )
    route_flow_text = fields.Char(
        string='Flow',
        compute='_compute_route_flow_text',
    )
    route_flow_json = fields.Text(
        string='Route Flow JSON',
        help='Flow graph {nodes, edges} edited by the route flow editor. This is the '
             'source of truth for the common route template; operations are materialised '
             'into work-order routes at generation time.',
    )
    x_drawing_ids = fields.One2many(
        'sn.wsd.process.route.drawing',
        'route_id',
        string='Drawing Numbers',
        copy=False,
    )
    x_drawing_count = fields.Integer(
        string='Drawing Count',
        compute='_compute_x_drawing_count',
    )
    note = fields.Text(string='Notes')

    # ---- statistics settings (统计设置) ----
    x_flow_operation_ids = fields.Many2many(
        'sn.wsd.operation',
        'sn_wsd_route_flow_operation_rel',
        'route_id',
        'operation_id',
        string='Flow Operations',
        compute='_compute_x_flow_operation_ids',
        store=True,
        help='Operations used by the flow graph. Statistics settings may only '
             'reference these operations.',
    )
    x_daily_input_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='制令单投入工序',
        check_company=True,
        tracking=True,
        help='Daily-order input quantity is counted from this operation onwards.',
    )
    x_daily_output_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='制令单产出工序',
        check_company=True,
        tracking=True,
        help='Daily-order output / qualified quantity is counted at this operation.',
    )
    x_material_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='物料关联工序',
        check_company=True,
        tracking=True,
        help='Operation material consumption is attributed to.',
    )
    x_workorder_input_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='工单投入工序',
        check_company=True,
        tracking=True,
        help='Work-order input quantity is counted from this operation onwards.',
    )
    x_aging_start_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='老化开始工序',
        check_company=True,
        tracking=True,
        help='Start boundary of the aging statistics window.',
    )
    x_aging_end_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='老化结束工序',
        check_company=True,
        tracking=True,
        help='End boundary of the aging statistics window.',
    )
    x_section_stat_ids = fields.One2many(
        'sn.wsd.route.section.stat',
        'route_id',
        string='工段统计',
        copy=False,
    )

    _route_code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The process route code must be unique per company.',
    )

    @api.depends('route_flow_json', 'route_operation_ids', 'bom_ids')
    def _compute_route_counts(self):
        for route in self:
            route.bom_count = len(route.bom_ids)
            # Operation count comes from the flow JSON (source of truth).
            route.operation_count = len(route._flow_graph()['nodes'])

    @api.depends('x_drawing_ids')
    def _compute_x_drawing_count(self):
        for route in self:
            route.x_drawing_count = len(route.x_drawing_ids)

    @api.depends('x_version_ids')
    def _compute_x_version_count(self):
        for route in self:
            route.x_version_count = len(route.x_version_ids)

    @api.depends('route_flow_json', 'route_operation_ids')
    def _compute_x_flow_operation_ids(self):
        """Mirror the operations used by the flow graph, so statistics fields can
        be domain-restricted to operations actually on the route."""
        for route in self:
            op_ids = list(dict.fromkeys(
                n.get('operation_id')
                for n in route._flow_graph()['nodes']
                if n.get('operation_id')
            ))
            route.x_flow_operation_ids = self.env['sn.wsd.operation'].browse(op_ids).exists()

    @api.depends(
        'route_operation_ids',
        'route_operation_ids.blocked_by_route_operation_ids',
        'route_operation_ids.sequence',
        'route_operation_ids.operation_id.name',
        'route_operation_ids.x_step_code',
    )
    def _compute_route_flow_html(self):
        """Render a simple node+arrow flow diagram as HTML for the form view."""
        for route in self:
            ops = route.route_operation_ids.sorted(lambda r: (r.sequence, r.id))
            if not ops:
                route.route_flow_html = False
                continue
            parts = [
                '<div style="display:flex;align-items:center;flex-wrap:wrap;gap:6px;padding:12px;background:#fafafa;border-radius:8px;">'
            ]
            for op in ops:
                deps = ', '.join(op.blocked_by_route_operation_ids.mapped('name')) or '-'
                parts.append(
                    '<div style="background:#fff;border:1px solid #4285f4;border-radius:8px;'
                    'padding:10px 12px;min-width:150px;box-shadow:0 1px 3px rgba(0,0,0,0.12);">'
                    '<div style="font-weight:bold;font-size:13px;color:#1a73e8;border-bottom:1px solid #e0e0e0;padding-bottom:4px;margin-bottom:6px;">'
                    '%s &middot; %s</div>'
                    '<div style="font-size:11px;color:#555;line-height:1.7;">'
                    '工位类型: %s<br/>'
                    '手动时长: %s<br/>'
                    '前置工序: %s'
                    '</div></div>'
                    % (op.x_step_code or '', op.name or '', op.x_station_type or '-',
                       op.time_cycle_manual or 0, deps)
                )
                parts.append('<span style="color:#4285f4;font-size:22px;font-weight:bold;">&rarr;</span>')
            if parts and parts[-1].endswith('&rarr;</span>'):
                parts.pop()
            parts.append('</div>')
            route.route_flow_html = ''.join(parts)

    @api.depends('route_flow_json', 'route_operation_ids')
    def _compute_route_flow_text(self):
        for route in self:
            nodes = route._flow_graph()['nodes']
            nodes = sorted(nodes, key=lambda n: (n.get('sequence') or 0, str(n.get('uid', ''))))
            route.route_flow_text = ' → '.join(
                (n.get('step_code') or n.get('name') or '') for n in nodes
            ) if nodes else False

    @api.model
    def _find_current_route_by_drawing_no(self, drawing_no, company_id=None):
        """Return the current confirmed+active route bound to the given drawing number.

        A route may bind multiple drawing numbers (物料编号/图号) via
        sn.wsd.process.route.drawing. This helper resolves the current effective
        route for a given 图号; falls back to the legacy single ``x_drawing_no`` on
        the route when no binding exists (migration compatibility).
        """
        if not drawing_no:
            return self.env['sn.wsd.process.route']
        bound_route_ids = self.env['sn.wsd.process.route.drawing'].search(
            [('x_drawing_no', '=', drawing_no)]
        ).mapped('route_id').ids
        domain = [
            ('state', '=', 'confirmed'),
            ('active', '=', True),
        ]
        if bound_route_ids:
            domain.append(('id', 'in', bound_route_ids))
        else:
            # Legacy fallback: single drawing number on the route.
            domain.append(('x_drawing_no', '=', drawing_no))
        if company_id:
            domain.append(('company_id', '=', company_id))
        return self.search(domain, order='confirmed_date desc, id desc', limit=1)

    @api.onchange('x_workshop_id')
    def _onchange_x_workshop_id(self):
        for route in self:
            if route.x_workshop_id:
                route.company_id = route.x_workshop_id.company_id

    @api.constrains('company_id', 'x_workshop_id')
    def _check_scope(self):
        for route in self:
            if route.x_workshop_id.company_id != route.company_id:
                raise ValidationError(_('The workshop must belong to the same company as the process route.'))

    def _next_copy_code(self):
        """A fresh unused route code for duplicates: BASE-COPY, BASE-COPY2, ..."""
        self.ensure_one()
        base = (self.code or 'ROUTE').strip() or 'ROUTE'
        existing = set(
            self.with_context(active_test=False).search(
                [('company_id', '=', self.company_id.id)]
            ).mapped('code')
        )
        candidate = f'{base}-COPY'
        n = 2
        while candidate in existing:
            candidate = f'{base}-COPY{n}'
            n += 1
        return candidate

    def copy(self, default=None):
        """Duplicate as a brand-new draft route.

        The route code is unique per company, so the copy gets a fresh
        ``-COPY`` code; the confirmation lifecycle restarts from draft V0
        without the archived versions and without the drawing bindings (two
        routes bound to the same drawing number would make the resolver
        ambiguous).
        """
        default = dict(default or {})
        default.setdefault('code', self._next_copy_code())
        default.setdefault('state', 'draft')
        default.setdefault('version', 0)
        default['x_is_default'] = False
        default['confirmed_by'] = False
        default['confirmed_date'] = False
        self = self.with_context(sn_wsd_skip_flow_versioning=True)
        return super().copy(default)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        """Odoo 19 API (name_get is dead code here): show "code / name" so
        routes sharing a name stay distinguishable in m2o dropdowns."""
        for route in self:
            route.display_name = ' / '.join(filter(None, [route.code, route.name]))

    def _sync_linked_bom_operations(self):
        for route in self:
            route.bom_ids._sync_process_route_operations()

    def action_open_linked_bom(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Linked Bill of Material',
            'res_model': 'mrp.bom',
        }
        if len(self.bom_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': self.bom_ids.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('id', 'in', self.bom_ids.ids)],
            })
        return action

    # ------------------------------------------------------------------
    # standalone confirmation lifecycle
    # ------------------------------------------------------------------
    # Node keys ignored by the flow signature: layout coordinates, internal
    # ids and derived display data. Anything else (present or added later)
    # counts as a structural/attribute change.
    _FLOW_SIG_IGNORED_NODE_KEYS = {'x', 'y', 'uid', 'id', '_selected', 'predecessors'}

    @api.model
    def _flow_signature(self, graph=None):
        """Canonical structure-only signature of a flow graph.

        Node positions and derived keys are stripped, nodes and edges are
        sorted, so two graphs that differ only by layout produce the same
        signature and do NOT count as a flow change.
        """
        if graph is None:
            graph = self._flow_graph()

        def clean(node):
            return {k: v for k, v in node.items()
                    if k not in self._FLOW_SIG_IGNORED_NODE_KEYS}

        nodes = sorted(
            (clean(n) for n in graph.get('nodes') or []),
            key=lambda n: json.dumps(n, sort_keys=True, ensure_ascii=False),
        )
        edges = sorted(
            (str(e.get('source')), str(e.get('target')))
            for e in graph.get('edges') or []
        )
        return json.dumps({'nodes': nodes, 'edges': edges}, sort_keys=True, ensure_ascii=False)

    def _latest_version_snapshot(self):
        """Latest archived flow version (empty recordset if never confirmed)."""
        self.ensure_one()
        return self.x_version_ids.sorted(key=lambda v: v.version_no, reverse=True)[:1]

    def _flow_changed_since_archive(self):
        """True when the live flow differs structurally from the last archive."""
        self.ensure_one()
        latest = self._latest_version_snapshot()
        if not latest:
            return True
        try:
            archived = json.loads(latest.route_flow_json)
            if not isinstance(archived, dict):
                archived = {}
        except (ValueError, TypeError):
            archived = {}
        archived_sig = self._flow_signature({
            'nodes': archived.get('nodes') or [],
            'edges': archived.get('edges') or [],
        })
        return archived_sig != self._flow_signature()

    # ------------------------------------------------------------------
    # Directed graph editor (AntV X6) backend: read/save route as nodes+edges
    # ------------------------------------------------------------------
    def _flow_graph(self):
        """Return {'nodes': [...], 'edges': [...]} for this route.

        Source of truth is ``route_flow_json``; falls back to building from the
        legacy relational operations (pre-migration routes) when the JSON is
        empty/invalid.
        """
        if self.route_flow_json:
            try:
                data = json.loads(self.route_flow_json)
                if isinstance(data, dict):
                    return {
                        'nodes': data.get('nodes') or [],
                        'edges': data.get('edges') or [],
                    }
            except (ValueError, TypeError):
                pass
        return self._flow_graph_from_operations()

    def _flow_graph_from_operations(self):
        """Build {nodes, edges} from the legacy relational operations."""
        nodes, edges = [], []
        for op in self.route_operation_ids:
            nodes.append({
                'uid': op.id,
                'id': op.id,
                'operation_id': op.operation_id.id,
                'name': op.name,
                'step_code': op.x_step_code,
                'sequence': op.sequence,
                'x_station_type': op.x_station_type,
                'time_cycle_manual': op.time_cycle_manual,
                'x_allow_entry': op.x_allow_entry,
                'x_allow_exit': op.x_allow_exit,
                'x_allow_serial_creation': op.x_allow_serial_creation,
                'x_allow_reentry': op.x_allow_reentry,
                'x_allow_repair_return': op.x_allow_repair_return,
                'x_ng_retry_limit': op.x_ng_retry_limit,
                'predecessors': op.blocked_by_route_operation_ids.mapped('x_step_code'),
            })
        for op in self.route_operation_ids:
            for dep in op.blocked_by_route_operation_ids:
                edges.append({'source': dep.id, 'target': op.id})
        return {'nodes': nodes, 'edges': edges}

    def get_route_graph(self):
        """Return route data as {nodes, edges} for the graph editor (JSON-backed)."""
        self.ensure_one()
        return self._flow_graph()

    @api.model
    def get_route_operations_for_company(self, company_id=None):
        """Palette operations for a (possibly unsaved) route.

        The palette must render as soon as the form opens — including on a
        brand-new record that has no id yet — so this takes the company
        directly instead of the route record.
        """
        company = self.env['res.company'].browse(company_id).exists() if company_id else self.env.company
        domain = [
            ('company_id', 'in', [False, company.id]),
            ('active', '=', True),
        ]
        operations = self.env['sn.wsd.operation'].search(
            domain, order='x_process_section, code, name',
        )
        return [{
            'id': op.id,
            'code': op.code or '',
            'name': op.name or '',
            'x_station_type': op.x_station_type or '',
            'x_process_section': op.x_process_section or '',
            'used': False,
        } for op in operations]

    def get_route_operations(self):
        """Return all operations for the palette, with a 'used' flag."""
        self.ensure_one()
        used_op_ids = set(
            n.get('operation_id') for n in self._flow_graph()['nodes'] if n.get('operation_id')
        )
        operations = self.env['sn.wsd.operation'].browse(
            [op['id'] for op in self.get_route_operations_for_company(self.company_id.id)]
        )
        return [{
            'id': op.id,
            'code': op.code or '',
            'name': op.name or '',
            'x_station_type': op.x_station_type or '',
            'x_process_section': op.x_process_section or '',
            'used': op.id in used_op_ids,
        } for op in operations]

    def _apply_flow_versioning(self):
        """保存即版本 core — idempotent: archiving happens only when the
        stored flow structurally differs from the latest archive.

        Triggered from write()/create() whenever route_flow_json is persisted
        (form save), and directly from save_route_graph (fullscreen editor).
        """
        self.ensure_one()
        graph = self._flow_graph()
        nodes, edges = graph['nodes'], graph['edges']
        # Cycle check on the stored graph (by uid).
        adjacency = {}
        for edge in edges:
            src = edge.get('source')
            tgt = edge.get('target')
            if src and tgt and src != tgt:
                adjacency.setdefault(tgt, set()).add(src)
        self._check_route_graph_cycle(adjacency)
        # An empty canvas has nothing to publish — plain save only.
        flow_changed = bool(nodes) and self._flow_changed_since_archive()
        now = fields.Datetime.now()
        if flow_changed:
            self.env['sn.wsd.process.route.version'].create({
                'route_id': self.id,
                'version_no': self.version + 1,
                'route_flow_json': self.route_flow_json,
                'confirmed_by': self.env.user.id,
                'confirmed_date': now,
            })
            self.version = self.version + 1
            self.write({
                'state': 'confirmed',
                'active': True,
                'confirmed_by': self.env.user.id,
                'confirmed_date': now,
            })
            self.message_post(body=_('Flow saved as version V%s.') % self.version)
        elif self.state == 'draft' and nodes:
            # Unchanged structure but never went live (e.g. layout-only edit
            # before any save): go live without a new version.
            self.write({
                'state': 'confirmed',
                'confirmed_by': self.env.user.id,
                'confirmed_date': now,
            })
        return {'upgraded': flow_changed, 'version': self.version}

    def save_route_graph(self, graph):
        """Persist the flow graph {nodes, edges} as JSON — 保存即版本.

        The common route is a template stored as JSON; operations are
        materialised into work-order routes (daily_route.operation) at
        generation time. This does NOT write to sn.wsd.process.route.operation
        nor sync to BoM operations.
        """
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(_('A cancelled route is read-only. Reset it to draft first.'))
        self.route_flow_json = json.dumps({
            'nodes': graph.get('nodes', []) or [],
            'edges': graph.get('edges', []) or [],
        })
        return self._apply_flow_versioning()

    def write(self, vals):
        result = super().write(vals)
        if 'route_flow_json' in vals:
            # Form save: the canvas is part of the record now — the same
            # versioning pipeline runs on write. Idempotent: a json equal to
            # the latest archive bumps nothing.
            for route in self:
                if route.state != 'cancelled':
                    route._apply_flow_versioning()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        # A route created together with a flow graph (form save of a new
        # record with a drawn canvas) goes live as V1. Duplicates copy the
        # flow but must start from scratch — copy() sets the skip flag.
        skip = self.env.context.get('sn_wsd_skip_flow_versioning')
        routes = super().create(vals_list)
        if not skip:
            routes.filtered(lambda r: r.route_flow_json)._apply_flow_versioning()
        return routes

    def _check_route_graph_cycle(self, adjacency):
        """adjacency: {target_id: set(source_ids)}. Raise on cycle (DFS)."""
        all_nodes = set(adjacency)
        for srcs in adjacency.values():
            all_nodes |= srcs
        color = {n: 0 for n in all_nodes}  # 0 white, 1 gray, 2 black

        def dfs(node):
            if color.get(node) == 1:
                raise ValidationError(_('Cycle detected in route graph: A→B→A loops are not allowed.'))
            if color.get(node) == 2:
                return
            color[node] = 1
            for dep in adjacency.get(node, ()):
                if dep in color:
                    dfs(dep)
            color[node] = 2

        for n in all_nodes:
            if color[n] == 0:
                dfs(n)

    # ------------------------------------------------------------------
    # statistics settings (统计设置) validation
    # ------------------------------------------------------------------
    def _flow_operation_order_map(self):
        """Map operation id -> position in the flow graph node order.

        Used for ordering checks (e.g. 老化开始 before 老化结束). Parallel
        branches get a partial order at best; node order is a good enough
        approximation for configuration validation.
        """
        self.ensure_one()
        order = {}
        for idx, node in enumerate(self._flow_graph()['nodes']):
            op_id = node.get('operation_id')
            if op_id and op_id not in order:
                order[op_id] = idx
        return order

    @api.constrains('route_flow_json', 'route_operation_ids',
                    'x_daily_input_operation_id', 'x_daily_output_operation_id',
                    'x_workorder_input_operation_id')
    def _check_required_statistics_operations(self):
        """The three core statistics operations become required as soon as the
        route carries a flow graph (a route without a flow is still a plain
        draft and may stay unconfigured)."""
        for route in self:
            if not route._flow_graph()['nodes']:
                continue
            missing = any(not route[fname] for fname in (
                'x_daily_input_operation_id',
                'x_daily_output_operation_id',
                'x_workorder_input_operation_id',
            ))
            if missing:
                raise ValidationError(_(
                    'The daily input, daily output and work order input operations '
                    'are required once the route has a flow graph.'))

    @api.constrains(
        'route_flow_json', 'route_operation_ids',
        'x_daily_input_operation_id', 'x_daily_output_operation_id',
        'x_material_operation_id', 'x_workorder_input_operation_id',
        'x_aging_start_operation_id', 'x_aging_end_operation_id',
    )
    def _check_statistics_operations(self):
        stat_fields = (
            ('x_daily_input_operation_id', _('制令单投入工序')),
            ('x_daily_output_operation_id', _('制令单产出工序')),
            ('x_material_operation_id', _('物料关联工序')),
            ('x_workorder_input_operation_id', _('工单投入工序')),
            ('x_aging_start_operation_id', _('老化开始工序')),
            ('x_aging_end_operation_id', _('老化结束工序')),
        )
        for route in self:
            order_map = route._flow_operation_order_map()
            for fname, label in stat_fields:
                op = route[fname]
                if op and op.id not in order_map:
                    raise ValidationError(_(
                        '%(label)s "%(op)s" is not part of the route flow graph. '
                        'Only operations on the flow chart can be selected.',
                        label=label, op=op.display_name,
                    ))
            if (
                route.x_daily_input_operation_id
                and route.x_daily_input_operation_id == route.x_daily_output_operation_id
            ):
                raise ValidationError(_('The daily input operation and the daily output operation cannot be the same.'))
            aging_start, aging_end = route.x_aging_start_operation_id, route.x_aging_end_operation_id
            if aging_start and aging_end and aging_start != aging_end:
                if order_map.get(aging_start.id, 0) > order_map.get(aging_end.id, 0):
                    raise ValidationError(_('The aging start operation must come before the aging end operation in the flow.'))

    @api.constrains('x_section_stat_ids', 'route_flow_json', 'route_operation_ids')
    def _check_section_stats(self):
        for route in self:
            route.x_section_stat_ids._check_section_range()


class MeterProcessRouteOperation(models.Model):
    _name = 'sn.wsd.process.route.operation'
    _description = 'Meter Process Route Operation'
    _order = 'route_id, sequence, id'
    _check_company_auto = True

    route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='route_id.company_id',
        store=True,
        readonly=True,
    )
    route_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        string='Route Workshop',
        related='route_id.x_workshop_id',
        store=True,
        readonly=True,
    )
    available_operation_ids = fields.Many2many(
        'sn.wsd.operation',
        compute='_compute_available_ids',
    )
    available_workcenter_ids = fields.Many2many(
        'mrp.workcenter',
        compute='_compute_available_ids',
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='Operation',
        required=True,
        check_company=True,
        index=True,
        domain="[('id', 'in', available_operation_ids)]",
    )
    name = fields.Char(
        string='Operation Name',
        related='operation_id.name',
        store=True,
        readonly=True,
    )
    sequence = fields.Integer(string='Sequence', default=100)
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        check_company=True,
        index=True,
        domain="[('id', 'in', available_workcenter_ids)]",
    )
    x_step_code = fields.Char(
        string='Route Operation Code',
        related='operation_id.code',
        store=True,
        readonly=True,
        index=True,
    )
    x_station_type = fields.Selection(
        related='operation_id.x_station_type',
        string='Station Type',
        store=True,
        readonly=True,
        index=True,
    )
    time_mode = fields.Selection(
        [('manual', 'Fixed'), ('auto', 'Computed')],
        string='Duration Computation',
        default='manual',
    )
    time_mode_batch = fields.Integer(string='Computed On Last', default=10)
    time_cycle_manual = fields.Float(string='Manual Duration', default=60)
    cost_mode = fields.Selection(
        [('actual', 'Actual time'), ('estimated', 'Theorical time')],
        string='Cost Based On',
        default='actual',
    )
    blocked_by_route_operation_ids = fields.Many2many(
        'sn.wsd.process.route.operation',
        relation='sn_wsd_process_route_operation_rel',
        column1='operation_id',
        column2='blocked_by_id',
        string='Blocked By',
        domain="[('route_id', '=', route_id), ('id', '!=', id)]",
        copy=False,
    )
    x_allow_entry = fields.Boolean(
        string='Allow Entry',
        help='Allow serials without a previous route event to enter this operation.',
    )
    x_allow_exit = fields.Boolean(
        string='Allow Exit',
        help='Mark this operation as an end (exit) operation of the route.',
    )
    x_allow_serial_creation = fields.Boolean(
        string='Allow Serial Creation',
        help='Allow the API to create a production-stage serial at this entry operation.',
    )
    x_allow_reentry = fields.Boolean(
        string='Allow Reentry',
        help='Allow a serial to be processed again on the same operation.',
    )
    x_allow_repair_return = fields.Boolean(
        string='Allow Repair Return',
        help='Allow serials returning from a repair station to enter this operation.',
    )
    x_allow_skip_with_override = fields.Boolean(
        string='Allow Skip With Override',
        help='Allow this operation to be reached with an explicit route override.',
    )
    x_ng_retry_limit = fields.Integer(
        string='NG Retry Limit',
        default=0,
        help='Maximum NG scan-pass attempts allowed before the serial must enter repair. Set 0 for no automatic repair threshold.',
    )
    needed_by_route_operation_ids = fields.Many2many(
        'sn.wsd.process.route.operation',
        relation='sn_wsd_process_route_operation_rel',
        column1='blocked_by_id',
        column2='operation_id',
        string='Blocks',
        domain="[('route_id', '=', route_id), ('id', '!=', id)]",
        copy=False,
    )
    bom_operation_ids = fields.One2many(
        'mrp.routing.workcenter',
        'x_route_operation_id',
        string='Projected BoM Operations',
        readonly=True,
    )
    bom_operation_count = fields.Integer(
        string='Projected BoM Operation Count',
        compute='_compute_bom_operation_count',
    )

    _route_operation_code_uniq = models.Constraint(
        'unique(route_id, operation_id)',
        'The operation must be unique within one process route.',
    )

    @api.depends('bom_operation_ids')
    def _compute_bom_operation_count(self):
        for operation in self:
            operation.bom_operation_count = len(operation.bom_operation_ids)

    @api.depends(
        'route_id.x_workshop_id',
        'company_id',
        'operation_id',
        'operation_id.x_workcenter_ids',
    )
    def _compute_available_ids(self):
        operation_model = self.env['sn.wsd.operation']
        workcenter_model = self.env['mrp.workcenter']
        for route_operation in self:
            operation_domain = [('company_id', '=', route_operation.company_id.id)]
            workcenter_domain = [('company_id', '=', route_operation.company_id.id), ('active', '=', True)]
            if route_operation.route_workshop_id:
                workcenter_domain.append(('x_workshop_id', '=', route_operation.route_workshop_id.id))
            route_operation.available_operation_ids = operation_model.search(operation_domain)
            if route_operation.operation_id:
                workcenter_domain.append(('id', 'in', route_operation.operation_id.x_workcenter_ids.ids))
            route_operation.available_workcenter_ids = workcenter_model.search(workcenter_domain)

    def _prepare_bom_operation_values(self, bom):
        self.ensure_one()
        return {
            'name': self.name,
            'bom_id': bom.id,
            'workcenter_id': self.workcenter_id.id or self.operation_id.x_workcenter_ids[:1].id or self.env['mrp.workcenter'].search([('company_id', '=', self.company_id.id), ('active', '=', True)], limit=1).id,
            'sequence': self.sequence,
            'time_mode': self.time_mode,
            'time_mode_batch': self.time_mode_batch,
            'time_cycle_manual': self.time_cycle_manual,
            'cost_mode': self.cost_mode,
            'x_route_operation_id': self.id,
            'x_step_code': self.x_step_code,
            'x_station_type': self.x_station_type,
            'x_allow_entry': self.x_allow_entry,
            'x_allow_exit': self.x_allow_exit,
            'x_allow_serial_creation': self.x_allow_serial_creation,
            'x_allow_reentry': self.x_allow_reentry,
            'x_allow_repair_return': self.x_allow_repair_return,
            'x_allow_skip_with_override': self.x_allow_skip_with_override,
            'x_ng_retry_limit': self.x_ng_retry_limit,
        }

    @api.onchange('operation_id')
    def _onchange_operation_id_apply_defaults(self):
        for operation in self:
            template = operation.operation_id
            if not template:
                continue
            # Work center is chosen at execution time (by daily plan / station),
            # not fixed on the route template, so we do not auto-fill it here.
            operation.time_mode = template.time_mode
            operation.time_mode_batch = template.time_mode_batch
            operation.time_cycle_manual = template.time_cycle_manual
            operation.cost_mode = template.cost_mode

    @api.constrains('route_id', 'company_id', 'operation_id', 'workcenter_id')
    def _check_company_scope(self):
        for operation in self:
            if operation.operation_id.company_id != operation.company_id:
                raise ValidationError(_('The operation must belong to the same company as the process route.'))
            # Work center is optional on the route template (chosen at execution
            # time), so the work center checks only apply when one is set.
            if not operation.workcenter_id:
                continue
            if operation.workcenter_id.company_id != operation.company_id:
                raise ValidationError(_('The work center must belong to the same company as the process route.'))
            if operation.workcenter_id not in operation.operation_id.x_workcenter_ids:
                raise ValidationError(_('The work center must be linked to the selected operation.'))
            if operation.route_workshop_id:
                if operation.workcenter_id.x_workshop_id != operation.route_workshop_id:
                    raise ValidationError(_('The selected work center must belong to the current workshop.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.mapped('route_id')._sync_linked_bom_operations()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.mapped('route_id')._sync_linked_bom_operations()
        return result

    def unlink(self):
        routes = self.mapped('route_id')
        result = super().unlink()
        routes._sync_linked_bom_operations()
        return result


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    x_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        # Optional: the route is bound to the product via 图号 (drawing number),
        # not to the BOM. Kept only so a BOM may still (optionally) carry the
        # operations it is synchronised from; a materials-only BOM leaves it empty.
        check_company=True,
        index=True,
    )

    @api.constrains('x_process_route_id', 'company_id')
    def _check_process_route_scope(self):
        for bom in self:
            # The route is optional on the BOM (it lives on the product via 图号);
            # only validate the company scope when one is actually set.
            route = bom.x_process_route_id
            if route and route.company_id != bom.company_id:
                raise ValidationError(_('The process route must belong to the same company as the bill of material.'))

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)
        boms.filtered('x_process_route_id')._sync_process_route_operations()
        return boms

    def write(self, vals):
        result = super().write(vals)
        if {'x_process_route_id', 'company_id'}.intersection(vals):
            self._sync_process_route_operations()
        return result

    def _sync_process_route_operations(self):
        for bom in self:
            route = bom.x_process_route_id
            route_operations = route.route_operation_ids.sorted(lambda operation: (operation.sequence, operation.id)) \
                if route else self.env['sn.wsd.process.route.operation']

            # The process route is the single source of truth for BoM operations.
            # Rebuild the BoM operations from scratch so deleted or detached route
            # operations cannot remain as stale rows on the BoM or MO.
            if bom.operation_ids:
                bom.operation_ids.unlink()

            workorder_map = {}
            for route_operation in route_operations:
                bom_operation = self.env['mrp.routing.workcenter'].create(
                    route_operation._prepare_bom_operation_values(bom)
                )
                workorder_map[route_operation.id] = bom_operation

            for route_operation in route_operations:
                bom_operation = workorder_map.get(route_operation.id)
                if not bom_operation:
                    continue
                bom_operation.blocked_by_operation_ids = [
                    fields.Command.set([
                        workorder_map[dependency.id].id
                        for dependency in route_operation.blocked_by_route_operation_ids
                        if dependency.id in workorder_map
                    ])
                ]

            draft_productions = self.env['mrp.production'].search([
                ('bom_id', '=', bom.id),
                ('state', '=', 'draft'),
            ])
            for production in draft_productions:
                production._link_bom(bom)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        related='bom_id.x_process_route_id',
        store=True,
        readonly=True,
    )


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

    x_process_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        related='bom_id.x_process_route_id',
        store=True,
        readonly=True,
        index=True,
    )
    x_route_operation_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Route Operation Template',
        ondelete='set null',
        index=True,
        check_company=True,
        copy=False,
    )
    x_step_code = fields.Char(string='Route Operation Code', index=True)
    x_allow_entry = fields.Boolean(
        string='Allow Entry',
        help='Allow serials without a previous route event to enter this BoM operation.',
    )
    x_allow_exit = fields.Boolean(
        string='Allow Exit',
        help='Mark this BoM operation as an end (exit) operation.',
    )
    x_allow_serial_creation = fields.Boolean(
        string='Allow Serial Creation',
        help='Allow the API to create a production-stage serial at this BoM operation.',
    )
    x_allow_reentry = fields.Boolean(
        string='Allow Reentry',
        help='Allow a serial to be processed again on the same BoM operation.',
    )
    x_allow_repair_return = fields.Boolean(
        string='Allow Repair Return',
        help='Allow serials returning from a repair station to enter this BoM operation.',
    )
    x_allow_skip_with_override = fields.Boolean(
        string='Allow Skip With Override',
        help='Allow this BoM operation to be reached with an explicit route override.',
    )
    x_ng_retry_limit = fields.Integer(
        string='NG Retry Limit',
        default=0,
        help='Maximum NG scan-pass attempts allowed before the serial must enter repair. Set 0 for no automatic repair threshold.',
    )

    @api.constrains('x_route_operation_id', 'bom_id')
    def _check_route_projection(self):
        for operation in self.filtered('x_route_operation_id'):
            if operation.x_route_operation_id.route_id != operation.bom_id.x_process_route_id:
                raise ValidationError(_('The projected operation must belong to the process route selected on the bill of material.'))


class ProcessRouteDrawing(models.Model):
    """Binding between a common process route and a drawing number (物料编号/图号).

    A route binds multiple drawing numbers here; the drawing-number resolver
    ``_find_current_route_by_drawing_no`` matches work orders to routes via this
    table. Configured on a dedicated page, not inline on the route form.
    """
    _name = 'sn.wsd.process.route.drawing'
    _description = 'Process Route Drawing Number Binding'
    _order = 'route_id, x_drawing_no'
    _rec_name = 'x_drawing_no'

    route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        required=True,
        ondelete='cascade',
        index=True,
    )
    x_drawing_no = fields.Char(
        string='Drawing No.',
        required=True,
        index=True,
    )
    route_code = fields.Char(
        string='Route Code',
        related='route_id.code',
    )
    # 带出信息（只读展示，不落库，实时反映产品当前值）。
    # 路线信息由 route_id 选择列承载，物料标识由图号本身承载，不再重复带出。
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        compute='_compute_product_info',
    )
    product_name = fields.Char(
        string='Product Name',
        compute='_compute_product_info',
    )
    product_specification = fields.Char(
        string='Product Specification',
        compute='_compute_product_info',
    )
    company_id = fields.Many2one(
        'res.company',
        related='route_id.company_id',
        store=True,
    )
    active = fields.Boolean(default=True)

    # 同一路线不能重复绑同一图号；一个产品（图号）只能绑定一条工艺路线。
    # Odoo 19 约束消息经 ir.model.constraint.message（translate）翻译，po 条目
    # 引用 model:ir.model.constraint,message:<xmlid>。
    _route_drawing_uniq = models.Constraint(
        'unique(route_id, x_drawing_no)',
        'A route cannot bind the same drawing number twice.',
    )
    _drawing_single_route = models.Constraint(
        'unique(company_id, x_drawing_no)',
        'A drawing number can only be bound to one process route.',
    )

    @api.depends('x_drawing_no')
    def _compute_product_info(self):
        """按图号带出产品信息：产品名称/规格。

        图号是 Char 关联键（product.product.x_drawing_no），一个图号
        正常只对应一个产品；多个匹配时取第一条。
        """
        ProductProduct = self.env['product.product']
        for drawing in self:
            product = ProductProduct
            if drawing.x_drawing_no:
                product = ProductProduct.search(
                    [('x_drawing_no', '=', drawing.x_drawing_no)],
                    limit=1,
                )
            drawing.product_id = product
            drawing.product_name = product.product_tmpl_id.name or False
            drawing.product_specification = product.material_specification or False


class ProcessRouteVersion(models.Model):
    """Archived flow-graph snapshot of a process route.

    One record per confirmed flow version (V1, V2, ...). The live route keeps
    its current JSON; upgrading the flow archives the newly confirmed graph so
    any two versions can be compared side by side as flow charts.
    """
    _name = 'sn.wsd.process.route.version'
    _description = 'Process Route Flow Version'
    _order = 'route_id, version_no desc'
    _rec_name = 'display_label'
    _check_company_auto = True

    route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='route_id.company_id',
        store=True,
    )
    version_no = fields.Integer(string='Version', required=True)
    route_flow_json = fields.Text(string='Flow Graph JSON', required=True)
    confirmed_by = fields.Many2one(
        'res.users',
        string='Confirmed By',
        readonly=True,
    )
    confirmed_date = fields.Datetime(string='Confirmed On', readonly=True)
    change_note = fields.Char(string='Change Note')
    display_label = fields.Char(string='Label', compute='_compute_display_label')

    _route_version_uniq = models.Constraint(
        'unique(route_id, version_no)',
        'Flow versions must be unique per route.',
    )

    @api.depends('version_no')
    def _compute_display_label(self):
        for version in self:
            version.display_label = f'V{version.version_no}'

    @api.model
    def read_flow_graph(self, version_id):
        """Return the archived {nodes, edges} graph for viewer/compare widgets."""
        version = self.browse(version_id).exists()
        if not version or not version.route_flow_json:
            return {'nodes': [], 'edges': []}
        try:
            data = json.loads(version.route_flow_json)
        except (ValueError, TypeError):
            return {'nodes': [], 'edges': []}
        return {'nodes': data.get('nodes') or [], 'edges': data.get('edges') or []}


class RouteSectionStat(models.Model):
    """工段统计 setting line: aggregate production between a start and an end
    operation of a route's flow (统计段别 = process section)."""
    _name = 'sn.wsd.route.section.stat'
    _description = 'Route Section Statistics Setting'
    _order = 'route_id, id'
    _check_company_auto = True

    route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        required=True,
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='route_id.company_id',
        store=True,
    )
    x_process_section = fields.Selection(
        PROCESS_SECTION_SELECTION,
        string='统计段别',
        required=True,
    )
    start_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='开始工序',
        required=True,
        check_company=True,
        help='Statistics for this section start at this operation.',
    )
    end_operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='结束工序',
        required=True,
        check_company=True,
        help='Statistics for this section end at this operation.',
    )

    _route_section_uniq = models.Constraint(
        'unique(route_id, x_process_section)',
        'Each statistics section can only be configured once per route.',
    )

    @api.constrains('route_id', 'start_operation_id', 'end_operation_id')
    def _check_section_range(self):
        for stat in self:
            order_map = stat.route_id._flow_operation_order_map()
            for op in (stat.start_operation_id, stat.end_operation_id):
                if op and op.id not in order_map:
                    raise ValidationError(_(
                        'Operation "%(op)s" is not part of the route flow graph. '
                        'Only operations on the flow chart can be selected.',
                        op=op.display_name,
                    ))
            if stat.start_operation_id and stat.end_operation_id:
                if stat.start_operation_id == stat.end_operation_id:
                    raise ValidationError(_('The start operation and the end operation of a statistics section cannot be the same.'))
                if order_map.get(stat.start_operation_id.id, 0) > order_map.get(stat.end_operation_id.id, 0):
                    raise ValidationError(_('The start operation of a statistics section must come before the end operation in the flow.'))

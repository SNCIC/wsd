import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .constants import (
    BOARD_SIDE_SELECTION,
    PROCESS_SECTION_SELECTION,
    SIDE_SELECTION,
    STATION_TYPE_SELECTION,
)


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
    # 工艺类型：标识整条路线属于哪种工艺（SMT 上料/扣点域以此判定拆行与扣点触发）。
    x_process_type = fields.Selection(
        [
            ('smt', 'SMT'),
            ('dip', 'DIP'),
            ('machine', 'Complete Machine'),
        ],
        string='Process Type',
        tracking=True,
        help='Craft family of this route: SMT lines split the material table '
             'and deduct points on pass; DIP and complete-machine lines do not.',
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
        SIDE_SELECTION,
        string='Production Side',
        default='single',
        help='Board side this route produces. Scheduling a MES order resolves '
             'the live route by drawing number AND side.',
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

    @api.depends('route_flow_json', 'route_operation_ids')
    def _compute_route_counts(self):
        for route in self:
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
    def _find_current_route_by_drawing_no(self, drawing_no, company_id=None, side=None, workshop_id=None):
        """Return the current confirmed+active route bound to the given drawing number.

        The drawing <-> route link lives exclusively in
        sn.wsd.process.route.drawing (图号绑定表). Matching key is
        车间 + 图号 + 面别:
        - ``workshop_id`` filters by the route's workshop (workshops may each
          maintain their own route for the same drawing + side); when omitted,
          any workshop matches.
        - ``side`` (single/top/bottom) filters by the route's explicitly
          declared production side; a route without a side matches no side.
        """
        if not drawing_no:
            return self.env['sn.wsd.process.route']
        bound_route_ids = self.env['sn.wsd.process.route.drawing'].search(
            [('x_drawing_no', '=', drawing_no)]
        ).mapped('route_id').ids
        domain = [
            ('state', '=', 'confirmed'),
            ('active', '=', True),
            ('id', 'in', bound_route_ids or [False]),
        ]
        if side:
            domain.append(('x_production_side', '=', side))
        if workshop_id:
            domain.append(('x_workshop_id', '=', workshop_id))
        if company_id:
            domain.append(('company_id', '=', company_id))
        return self.search(domain, order='confirmed_date desc, id desc', limit=1)

    @api.model
    def _mes_side_route_map(self, drawings, company_id=None, workshop_id=None):
        """Batch route-check lookup: {drawing_no: {side_key: live_route}}.

        Mirrors ``_find_current_route_by_drawing_no`` for many drawing numbers
        at once: bindings only, explicitly declared sides only.
        ``workshop_id`` restricts to one workshop's routes; without it the
        first live route per (drawing, side) wins.
        """
        result = {drawing: {} for drawing in drawings}
        drawings = [d for d in drawings if d]
        if not drawings:
            return result
        Drawing = self.env['sn.wsd.process.route.drawing']
        bindings = Drawing.search([('x_drawing_no', 'in', drawings)])
        route_ids = {binding.route_id.id for binding in bindings}
        base = [
            ('state', '=', 'confirmed'),
            ('active', '=', True),
        ]
        if workshop_id:
            base.append(('x_workshop_id', '=', workshop_id))
        if company_id:
            base.append(('company_id', '=', company_id))
        live = {}
        if route_ids:
            live = self.search(
                base + [('id', 'in', list(route_ids))],
                order='confirmed_date desc, id desc')
        for binding in bindings:
            route = live.filtered(lambda r: r.id == binding.route_id.id)
            if route and route.x_production_side:
                result.setdefault(binding.x_drawing_no, {}).setdefault(
                    route.x_production_side, route)
        return result

    @api.model
    def _mes_open_route_create_action(self, drawing_no, side, workshop_id=None):
        """Act-window opening a NEW route form prefilled with workshop +
        drawing + side (the [Maintain Route] / per-side add buttons)."""
        context = {'default_x_production_side': side}
        if drawing_no:
            context['default_x_drawing_ids'] = [(0, 0, {'x_drawing_no': drawing_no})]
        if workshop_id:
            context['default_x_workshop_id'] = workshop_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Process Route'),
            'res_model': 'sn.wsd.process.route',
            'view_mode': 'form',
            'target': 'current',
            'context': context,
        }

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
            # Orders not yet online follow the common route automatically —
            # unless they were locally edited (customized): their edits are
            # preserved until a manual sync accepts the common version back.
            self.env['sn.wsd.mes.order'].search([
                ('x_mes_route_id.route_id', '=', self.id),
                ('x_online_date', '=', False),
                ('x_mes_route_id.is_customized', '=', False),
            ]).action_sync_route()
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

    def _check_flow_json_cycles(self, flow_json):
        """Cycle gate: ANY write of route_flow_json is checked against the
        value being written — cancelled routes and copy()'s skip context
        included. A cycle raises immediately; there is no fallback path."""
        try:
            data = json.loads(flow_json)
        except (ValueError, TypeError):
            return  # malformed json is not a cycle issue; handled downstream
        if not isinstance(data, dict):
            return
        adjacency = {}
        for edge in data.get('edges') or []:
            src = edge.get('source')
            tgt = edge.get('target')
            if src and tgt and src != tgt:
                adjacency.setdefault(tgt, set()).add(src)
        self._check_route_graph_cycle(adjacency)

    def write(self, vals):
        if 'route_flow_json' in vals and vals['route_flow_json']:
            self._check_flow_json_cycles(vals['route_flow_json'])
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
        # Cycle gate first — a cyclic graph never reaches the database, no
        # matter which context the create comes from (copy included).
        for vals in vals_list:
            if vals.get('route_flow_json'):
                self._check_flow_json_cycles(vals['route_flow_json'])
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
    x_allow_skip_with_override = fields.Boolean(
        string='Allow Skip With Override',
        help='Allow this operation to be reached with an explicit route override.',
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

    _route_operation_code_uniq = models.Constraint(
        'unique(route_id, operation_id)',
        'The operation must be unique within one process route.',
    )

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


class MrpRoutingWorkcenter(models.Model):
    _inherit = 'mrp.routing.workcenter'

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
    x_allow_skip_with_override = fields.Boolean(
        string='Allow Skip With Override',
        help='Allow this BoM operation to be reached with an explicit route override.',
    )
    # Legacy columns kept only so existing work orders (which relate to
    # x_route_operation_id through their BoM operation row) keep working until
    # the work-order side is migrated; no new data is written here.


class ProcessRouteDrawing(models.Model):
    """Binding between a common process route and a drawing number (物料编号/图号).

    A route binds multiple drawing numbers here; MES orders resolve their route
    through this table by 车间 + 图号 + 面别. A double-sided drawing carries one
    binding per production side (T/B) and each workshop may keep its own set,
    so uniqueness is (company, workshop, drawing, side). Configured on a
    dedicated page and inline on the route form.
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
    x_side = fields.Selection(
        related='route_id.x_production_side',
        string='Production Side',
        store=True,
        index=True,
        help='Production side of the bound route; kept in sync from the route.',
    )
    x_workshop_id = fields.Many2one(
        'sn.mrp.workshop',
        related='route_id.x_workshop_id',
        string='Workshop',
        store=True,
        index=True,
        help='Workshop of the bound route; kept in sync from the route.',
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
    # 面别列展示产品板面类型（单/双面），路线的 T/B 生产面由路线自身
    # （x_production_side）承载，不在绑定行重复显示。
    product_board_side = fields.Selection(
        BOARD_SIDE_SELECTION,
        string='Board Side Type',
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

    # 同一路线不能重复绑同一图号；一个产品（图号）在同一个车间每面只能
    # 绑定一条工艺路线（双面板 = T/B 各一条；不同车间可各绑各的）。
    # 历史约束 unique(company, drawing) 由 migrations/19.0.6.0.0 丢弃。
    # Odoo 19 约束消息经 ir.model.constraint.message（translate）翻译，po 条目
    # 引用 model:ir.model.constraint,message:<xmlid>。
    _route_drawing_uniq = models.Constraint(
        'unique(route_id, x_drawing_no)',
        'A route cannot bind the same drawing number twice.',
    )
    _drawing_side_route_uniq = models.Constraint(
        'unique(company_id, x_workshop_id, x_drawing_no, x_side)',
        'A drawing number can only be bound to one process route per workshop '
        'and production side.',
    )

    @api.depends('x_drawing_no')
    def _compute_product_info(self):
        """按图号带出产品信息：产品名称/面别/规格。

        图号是 Char 关联键（product.product.default_code，界面上即"图号"
        字段），一个图号正常只对应一个产品；多个匹配时取第一条。
        """
        ProductProduct = self.env['product.product']
        for drawing in self:
            product = ProductProduct
            if drawing.x_drawing_no:
                product = ProductProduct.search(
                    [('default_code', '=', drawing.x_drawing_no)],
                    limit=1,
                )
            drawing.product_id = product
            drawing.product_name = product.product_tmpl_id.name or False
            drawing.product_board_side = product.x_board_side or False
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

/** @odoo-module **/
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { buildRouteCardHtml } from "./route_flow_widget.js";

/**
 * MES-order private route editor — the order's own copy of the common flow.
 *
 * Same canvas interactions as the common editor (palette / drag / connect /
 * delete) with order-specific rules:
 * - nodes with execution records (frozen_ids) are locked (no edit/delete);
 * - node colors reflect execution progress (station: wip/done/ng;
 *   report: done/partial);
 * - saving calls the order's action_save_route_graph (private tables only,
 *   the common route is never touched) and marks the order customized.
 */
const COLOR_GRAY = "#C2C8D5";
const COLOR_BLUE = "#5F95FF";
const COLOR_GREEN = "#52C41A";
const COLOR_ORANGE = "#fa8c16";
const COLOR_RED = "#ff4d4f";
const COLOR_LOCK = "#8c8c8c";
const PORT_DOT_RADIUS = 4;
const PORT_HIT_RADIUS = 10;
const CARD_W = 200;
const CARD_H = 56;

let mesEdgeRegistered = false;
let mesCardRegistered = false;

function nodeStroke(state, frozen) {
    if (frozen) return COLOR_LOCK;
    if (state === 'done') return COLOR_GREEN;
    if (state === 'wip') return COLOR_BLUE;
    if (state === 'ng') return COLOR_RED;
    if (state && state.startsWith('partial')) return COLOR_ORANGE;
    return COLOR_BLUE;
}

export class MesOrderRouteEditor extends Component {
    static template = "sn_wsd_route_graph.MesOrderRouteEditor";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.containerRef = useRef("container");
        this.routeId = null;
        this.graph = null;
        this.allOperations = [];
        this.frozenIds = [];
        this.states = {};
        this.state = useState({
            selected: null,
            usedOpIds: [],
            paletteVersion: 0,
            editable: false,
            saving: false,
            dirty: false,
        });
        this._loading = false;
        this._injectStyles();
        onMounted(() => this._build());
    }

    get paletteGroups() {
        void this.state.paletteVersion;
        const usedSet = new Set(this.state.usedOpIds);
        const groups = {};
        for (const op of this.allOperations) {
            const s = op.x_process_section || "other";
            (groups[s] = groups[s] || []).push(Object.assign({}, op, { used: usedSet.has(op.id) }));
        }
        const order = ["smt", "dip", "board_test", "assembly", "testing", "inspection", "packaging"];
        const labels = { smt: "SMT", dip: "DIP", board_test: "单板调试", assembly: "装配", testing: "调试", inspection: "检验", packaging: "包装" };
        return order.filter(s => groups[s]).map(s => ({ key: s, label: labels[s] || s, ops: groups[s] }))
            .concat(groups.other ? [{ key: "other", label: "其他", ops: groups.other }] : []);
    }

    get paletteAvailableCount() {
        const usedSet = new Set(this.state.usedOpIds);
        return this.allOperations.filter(o => !usedSet.has(o.id)).length;
    }

    _injectStyles() {
        if (document.getElementById("o-mes-order-route-css")) return;
        const style = document.createElement("style");
        style.id = "o-mes-order-route-css";
        style.textContent = [
            ".o_mes_route_root { border: 1px solid #dfe3e8; background: #fff; }",
            ".o_mes_route_toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-bottom: 1px solid #dfe3e8; background: #fff; }",
            ".o_mes_route_hint { margin-left: auto; font-size: 12px; color: #8c8c8c; }",
            ".o_mes_route_shell { position: relative; display: flex; height: 520px; }",
            ".o_mes_route_palette { width: 150px; flex-shrink: 0; border-right: 1px solid #dfe3e8; background: #fff; display: flex; flex-direction: column; }",
            ".o_mes_route_palette_header { padding: 10px 12px; font-size: 13px; font-weight: 600; border-bottom: 1px solid #dfe3e8; }",
            ".o_mes_route_palette_body { flex: 1; overflow-y: auto; padding: 10px; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-content: start; }",
            ".o_mes_route_palette .o_palette_group_title { grid-column: 1 / -1; margin: 4px 0 6px; font-size: 11px; font-weight: 600; color: #8c8c8c; text-transform: uppercase; }",
            ".o_mes_route_canvas { flex: 1; min-width: 0; }",
            ".o_route_flow_panel { position: absolute; top: 10px; right: 10px; bottom: 10px; width: 248px; background: #fff; border: 1px solid rgba(0,0,0,0.06); border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.16); padding: 14px; overflow-y: auto; box-sizing: border-box; z-index: 5; }",
            ".o_prop_head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; border-bottom: 1px solid #dfe3e8; }",
            ".o_prop_close { background: none; border: 0; color: #bfbfbf; font-size: 18px; line-height: 1; cursor: pointer; }",
            ".o_prop_sub { margin: 10px 0 16px; font-size: 13px; font-weight: 600; color: #141414; }",
            ".o_prop_label { display: block; margin-bottom: 4px; font-size: 12px; font-weight: 600; color: #8c8c8c; }",
            ".o_prop_tags { display: flex; gap: 8px; margin-top: 8px; }",
            ".o_prop_tag { padding: 4px 14px; font-size: 12px; font-weight: 600; border: 1px solid #d9d9d9; border-radius: 14px; background: #fff; color: #595959; }",
            ".o_prop_tag_on { color: #fff !important; }",
            ".o_prop_tag_start { background: #52c41a; border-color: #52c41a; }",
            ".o_route_node_card.o_selected { background: #f0f7ff; }",
            ".o_mes_route_canvas .x6-port-body { cursor: crosshair; }",
            ".o_mes_route_canvas .x6-edge:hover .x6-edge-path:last-child { stroke: #ff4d4f !important; }",
            ".o_route_node_card.frozen { opacity: 0.75; }",
            ".o_route_node_card.frozen::after { content: '🔒'; position: absolute; top: 4px; right: 6px; font-size: 12px; }",
            ".o_route_node_card.frozen .o_node_actions { display: none !important; }",
            /* self-sufficient copies of the palette/card styles (the common
               editor/viewer may not be mounted on this page) */
            ".o_palette_group_title { grid-column: 1 / -1; margin: 4px 0 6px; font-size: 11px; font-weight: 600; color: #8c8c8c; text-transform: uppercase; letter-spacing: 0.02em; }",
            ".o_palette_card { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; width: 100%; height: 56px; margin: 0; padding: 6px 4px; border: 1px solid #5f95ff; border-radius: 8px; background: #fff; box-sizing: border-box; cursor: pointer; user-select: none; }",
            ".o_palette_card.o_used { opacity: 0.48; cursor: not-allowed; }",
            ".o_palette_card .o_palette_name { width: 100%; font-size: 12px; font-weight: 600; color: #141414; line-height: 14px; text-align: center; word-break: break-word; overflow: hidden; }",
            ".o_route_node_card { position: relative; display: flex; flex-direction: column; justify-content: center; width: 100%; height: 100%; box-sizing: border-box; padding: 8px; background: #fff; gap: 6px; }",
            ".o_node_badges { position: absolute; top: 0; left: 0; display: flex; flex-direction: column; gap: 2px; z-index: 2; pointer-events: none; }",
            ".o_node_badge { font-size: 10px; font-weight: 600; line-height: 14px; padding: 1px 6px; color: #fff; white-space: nowrap; border-radius: 0 0 6px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.12); }",
            ".o_node_badge_start { background: #52c41a; }",
            ".o_node_badge_end { background: #ff4d4f; border-radius: 0; }",
            ".o_route_node_card .o_node_header { display: flex; align-items: center; gap: 8px; }",
            ".o_route_node_card .o_node_icon { flex: 0 0 auto; width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; background: #f0f5ff; color: #1d39c4; }",
            ".o_route_node_card .o_node_title { flex: 1; min-width: 0; font-size: 14px; color: #141414; font-weight: 600; line-height: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }",
            ".o_route_node_card .o_node_actions { margin-left: auto; display: flex; align-items: center; }",
            ".o_route_node_card .o_node_actions .o_node_op { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 5px; font-size: 15px; line-height: 1; color: #8c8c8c; cursor: pointer; }",
            ".o_route_node_card .o_node_actions .o_node_op:hover { color: #ff4d4f; background: rgba(255,77,79,0.12); }",
            ".o_mes_route_canvas .x6-node foreignObject body { margin: 0; padding: 0; }",
        ].join("\n");
        document.head.appendChild(style);
    }

    async _build() {
        if (!window.X6) {
            this.notification.add("X6 library not loaded", { type: "danger" });
            return;
        }
        const rec = this.props.record;
        const orderId = rec && (rec.resId ?? rec.res_id ?? (rec.data && rec.data.id));
        if (!orderId) return;
        this._loading = true;
        try {
            const [canvas, ops] = await Promise.all([
                this.orm.call("sn.wsd.mes.order", "get_route_canvas", [orderId]),
                this.orm.call("sn.wsd.process.route", "get_route_operations_for_company", []),
            ]);
            this.allOperations = ops;
            this.frozenIds = canvas.frozen_ids || [];
            this.states = canvas.states || {};
            this.state.editable = !!canvas.editable;
            this.state.usedOpIds = canvas.graph.nodes.map(n => n.operation_id).filter(Boolean);
            this.state.paletteVersion++;

            const X6 = window.X6;
            if (!mesEdgeRegistered) {
                try {
                    X6.Graph.registerEdge("route-agent-edge", {
                        inherit: "edge",
                        attrs: { line: { stroke: COLOR_BLUE, strokeWidth: 2, targetMarker: "block" } },
                    }, true);
                    mesEdgeRegistered = true;
                } catch (e) { /* already registered */ }
            }
            if (!mesCardRegistered) {
                try {
                    X6.Shape.HTML.register({
                        shape: "route-op-card",
                        width: CARD_W,
                        height: CARD_H,
                        effect: ["data"],
                        html: (cell) => this._cardHtml(cell),
                    });
                    mesCardRegistered = true;
                } catch (e) { /* already registered */ }
            }

            if (this.graph) {
                try { this.graph.dispose(); } catch (e) { /* UMD may ignore */ }
                this.graph = null;
            }
            const graph = new X6.Graph({
                container: this.containerRef.el,
                grid: true,
                panning: { enabled: true },
                mousewheel: { enabled: true, minScale: 0.5, maxScale: 3 },
                connecting: {
                    connector: { name: "normal" },
                    connectionPoint: "anchor",
                    allowBlank: false,
                    allowLoop: false,
                    allowMulti: false,
                    snap: { radius: 40 },
                    highlight: true,
                    createEdge() { return graph.createEdge({ shape: "route-agent-edge" }); },
                    validateConnection({ targetMagnet }) { return !!targetMagnet; },
                },
                interacting: this.state.editable ? {
                    nodeMovable: { validateNode: (node) => this._isEditableNode(node) },
                    edgeMovable: false,
                    magnetConnectable: this.state.editable,
                } : false,
            });
            this.graph = graph;

            graph.on("node:click", (args) => {
                const native = args.e || args;
                const target = native && native.target;
                if (target && target.closest && target.closest("[data-route-node-delete]")) {
                    if (this._isEditableNode(args.node)) graph.removeCells([args.node]);
                    return;
                }
                this._selectNode(this.state.editable ? args.node : null);
            });
            graph.on("blank:click", () => this._selectNode(null));
            graph.on("edge:mouseenter", ({ edge }) => {
                try { edge.addTools(this._edgeRemoveTool()); } catch (e) { /* UMD */ }
            });
            graph.on("edge:mouseleave", ({ edge }) => {
                try { edge.removeTools(); } catch (e) { /* UMD */ }
            });

            const markDirty = () => {
                if (this._loading || !this.state.editable) return;
                this.state.dirty = true;
            };
            graph.on("cell:added", markDirty);
            graph.on("cell:removed", (args) => {
                if (args.cell.isNode && args.cell.isNode()) {
                    const d = args.cell.getData();
                    if (d && d.operation_id) {
                        this.state.usedOpIds = this.state.usedOpIds.filter(id => id !== d.operation_id);
                        this.state.paletteVersion++;
                    }
                }
                markDirty();
            });

            canvas.graph.nodes.forEach((n, i) => this._addNode(graph, n, 30, 30 + i * 90));
            canvas.graph.edges.forEach(e => this._addEdge(graph, e));
            this._applyPortMagnets();
            this._loading = false;
            this.state.dirty = false;
            this._fitView();
            setTimeout(() => this._fitView(), 300);
        } catch (err) {
            this._loading = false;
            this.notification.add("加载制令单工艺路线失败: " + String(err.message || err), { type: "danger" });
        }
    }

    _cardHtml(cell) {
        const d = cell.getData() || {};
        const frozen = d._frozen;
        const state = d._state;
        let html = buildRouteCardHtml(cell);
        if (frozen) {
            html = html.replace('o_route_node_card', 'o_route_node_card frozen');
        }
        if (frozen || state) {
            const badge = frozen ? `<div class="o_node_badge" style="background:${COLOR_LOCK};border-radius:0 0 6px 0;">已执行</div>`
                : (state === 'done' ? `<div class="o_node_badge o_node_badge_start">完成</div>`
                : (state === 'wip' ? `<div class="o_node_badge" style="background:${COLOR_BLUE};border-radius:0 0 6px 0;">在制</div>`
                : (state === 'ng' ? `<div class="o_node_badge o_node_badge_end">不良</div>`
                : (state && state.startsWith('partial') ? `<div class="o_node_badge" style="background:${COLOR_ORANGE};border-radius:0 0 6px 0;">${state.split(':')[1]}</div>` : ""))));
            html = html.replace('<div class="o_node_header">', (badge ? `<div class="o_node_badges">${badge}</div>` : "") + '<div class="o_node_header">');
        }
        return html;
    }

    _isEditableNode(node) {
        const d = node.getData() || {};
        return this.state.editable && !this.frozenIds.includes(d.uid);
    }

    _addNode(graph, data, x, y) {
        const frozen = this.frozenIds.includes(data.uid);
        const stroke = nodeStroke(this.states[data.uid], frozen);
        return graph.addNode({
            id: String(data.uid),
            x, y, width: CARD_W, height: CARD_H,
            shape: "route-op-card",
            attrs: {
                body: { fill: "#fff", stroke, strokeWidth: frozen ? 2 : 1, rx: 8, ry: 8, magnet: true, cursor: "crosshair" },
            },
            ports: {
                groups: {
                    top: { position: "top", attrs: { body: { r: PORT_DOT_RADIUS, stroke: COLOR_GRAY, fill: COLOR_GRAY, style: { visibility: "hidden" } } } },
                    bottom: { position: "bottom", attrs: { body: { r: PORT_DOT_RADIUS, stroke: COLOR_GRAY, fill: COLOR_GRAY, style: { visibility: "hidden" } } } },
                },
                items: [
                    { id: "top", group: "top" },
                    { id: "bottom", group: "bottom" },
                ],
            },
            data: Object.assign({}, data, { _frozen: frozen, _state: this.states[data.uid] }),
        });
    }

    _addEdge(graph, e) {
        const sNode = graph.getCellById(String(e.source));
        const tNode = graph.getCellById(String(e.target));
        if (!sNode || !tNode) return;
        const sp = sNode.getPosition(), tp = tNode.getPosition();
        const out = sp.y <= tp.y ? "bottom" : "top";
        const inp = sp.y <= tp.y ? "top" : "bottom";
        graph.addEdge({
            shape: "route-agent-edge",
            source: { cell: String(e.source), port: out },
            target: { cell: String(e.target), port: inp },
        });
    }

    _selectNode(node) {
        const previous = this._selectedCell;
        if (previous && previous !== node) {
            previous.attr("body/strokeWidth", 1);
            previous.setData({ _selected: false });
        }
        this._selectedCell = node || null;
        if (node) {
            node.attr("body/strokeWidth", 2);
            if (previous !== node) node.setData({ _selected: true });
            this.state.selected = Object.assign({}, node.getData());
        } else {
            this.state.selected = null;
        }
    }

    _applyPortMagnets() {
        if (!this.containerRef?.el) return;
        const apply = () => {
            this.containerRef.el.querySelectorAll(".x6-port circle").forEach(c => {
                c.setAttribute("magnet", "true");
                c.setAttribute("cursor", "crosshair");
            });
            this.containerRef.el.querySelectorAll(".x6-node rect:first-of-type").forEach(r => {
                r.setAttribute("magnet", "true");
                r.setAttribute("cursor", "crosshair");
            });
        };
        apply();
        setTimeout(apply, 200);
        setTimeout(apply, 1000);
    }

    onPaletteClick(ev) {
        if (!this.graph || !this.state.editable) return;
        const opId = parseInt(ev.currentTarget.getAttribute("data-op-id"), 10);
        if (!opId || this.state.usedOpIds.includes(opId)) return;
        const op = this.allOperations.find(o => o.id === opId);
        if (!op) return;
        const existing = this.graph.getNodes();
        const y = existing.length ? Math.max(...existing.map(n => n.getPosition().y)) + 90 : 30;
        this._addNode(this.graph, {
            uid: "new_" + Date.now(), id: null, operation_id: op.id, name: op.name,
            step_code: op.code, sequence: (existing.length + 1) * 10,
            x_station_type: op.x_station_type, time_cycle_manual: 60,
            x_allow_entry: existing.length === 0, x_allow_exit: false,
        }, 30, y);
        this.state.usedOpIds = [...this.state.usedOpIds, opId];
        this.state.paletteVersion++;
        this.state.dirty = true;
        this._applyPortMagnets();
    }

    _fitView() {
        if (!this.graph) return;
        try { this.graph.zoomToFit({ padding: 24, maxScale: 1 }); } catch (e) { /* empty */ }
    }

    onFitScreen() { this._fitView(); }

    onClosePanel() { this._selectNode(null); }

    onToggleStart() {
        this._toggleFlag('x_allow_entry');
    }

    onToggleEnd() {
        this._toggleFlag('x_allow_exit');
    }

    _toggleFlag(flag) {
        if (!this.state.selected || !this._selectedCell) return;
        if (this.frozenIds.includes(this.state.selected.uid)) return;
        const value = !this.state.selected[flag];
        this.state.selected[flag] = value;
        const d = Object.assign({}, this._selectedCell.getData() || {});
        d[flag] = value;
        if (flag === 'x_allow_entry') d.is_input = value;
        this._selectedCell.setData(d);   // effect:["data"] re-renders the card badges
        this.state.dirty = true;
    }

    onSequenceChange(ev) {
        if (!this.state.selected || !this._selectedCell) return;
        const value = parseInt(ev.target.value, 10) || 100;
        this.state.selected.sequence = value;
        const d = Object.assign({}, this._selectedCell.getData() || {}, { sequence: value });
        this._selectedCell.setData(d);
        this.state.dirty = true;
    }

    _edgeRemoveTool() {
        return {
            name: "button-remove",
            args: {
                distance: 0.5,
                offset: 0,
                markup: [
                    { tagName: "circle", selector: "button", attrs: { r: 12, fill: "#FF1D00", stroke: "#ffffff", "stroke-width": 1.5, cursor: "pointer" } },
                    { tagName: "path", selector: "icon", attrs: { d: "M -5 -5 5 5 M -5 5 5 -5", fill: "none", stroke: "#FFFFFF", "stroke-width": 2.5, "pointer-events": "none" } },
                ],
            },
        };
    }

    _serializeGraph() {
        if (!this.graph) return { nodes: [], edges: [] };
        const nodes = this.graph.getNodes().map(n => {
            const d = Object.assign({}, n.getData() || {});
            delete d._selected; delete d._frozen; delete d._state;
            const pos = n.getPosition();
            const nid = parseInt(n.id, 10);
            return Object.assign(d, {
                uid: n.id,
                id: Number.isFinite(nid) ? nid : null,
                x: Math.round(pos.x), y: Math.round(pos.y),
            });
        });
        const edges = this.graph.getEdges().map(e => {
            const s = e.getSourceNode(), t = e.getTargetNode();
            return { source: s && s.id, target: t && t.id };
        }).filter(e => e.source && e.target);
        return { nodes, edges };
    }

    async onClickSave() {
        const rec = this.props.record;
        const orderId = rec && (rec.resId ?? rec.res_id);
        if (!orderId || !this.graph || this.state.saving || !this.state.dirty) return;
        this.state.saving = true;
        try {
            await this.orm.call("sn.wsd.mes.order", "action_save_route_graph", [orderId], {
                graph: this._serializeGraph(),
            });
            this.notification.add("制令单工艺已保存（不影响公共工艺路线）", { type: "success" });
            this.state.dirty = false;
            await this._build();
        } catch (err) {
            this.notification.add("保存失败: " + String((err && (err.data?.message || err.message)) || err), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("view_widgets").add("mes_order_route_editor", { component: MesOrderRouteEditor });

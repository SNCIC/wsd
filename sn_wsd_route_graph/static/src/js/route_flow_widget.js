/** @odoo-module **/
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRecordObserver } from "@web/model/relational_model/utils";

/**
 * Process route flow editor — adapted from AntV X6 agentFlow showcase.
 * Layout: [operation palette | graph canvas | detail panel]
 * Ports are hidden with SVG visibility, shown on node hover. Connected ports stay blue.
 * Edges use a straight blue connector (top/bottom ports only).
 */

const COLOR_GRAY = "#C2C8D5";
const COLOR_BLUE = "#5F95FF";
const PORT_DOT_RADIUS = 4;
const PORT_HIT_RADIUS = 10;
const CARD_W = 200;
const CARD_H = 56;

const STATION_LABELS = {
    assembly: "组装", programming: "烧录", calibration: "校准", aging: "老化",
    inspection: "检验", final_test: "终测", packaging: "包装", repair: "返修",
};

const SECTION_ORDER = ["smt", "dip", "board_test", "assembly", "testing", "inspection", "packaging"];
const SECTION_LABELS = {
    smt: "SMT", dip: "DIP", board_test: "单板调试", assembly: "装配",
    testing: "调试", inspection: "检验", packaging: "包装",
};

let routeAgentEdgeRegistered = false;
let routeAgentCardRegistered = false;

// The agentFlow showcase only ships four icon themes; map station types onto them.
function nodeThemeClass(stationType) {
    if (stationType === "programming" || stationType === "final_test") return "o_node_theme_green";
    if (stationType === "calibration" || stationType === "aging") return "o_node_theme_orange";
    if (stationType === "repair") return "o_node_theme_red";
    return "o_node_theme_blue";
}

function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
}

/**
 * Render the node card HTML, mirroring the X6 agentFlow `agent-card` header:
 * icon / title / ✖️ delete.
 */
export function buildRouteCardHtml(cell) {
    const d = cell.getData() || {};
    const code = d.step_code || d.name || String(d.uid || d.id || "");
    const title = d.name || code;
    const selected = d._selected ? " o_selected" : "";
    const startBadge = d.x_allow_entry ? `<div class="o_node_badge o_node_badge_start">开始工序</div>` : "";
    const endBadge = d.x_allow_exit ? `<div class="o_node_badge o_node_badge_end">结束工序</div>` : "";
    const badges = (startBadge || endBadge)
        ? `<div class="o_node_badges">${startBadge}${endBadge}</div>` : "";
    return [
        `<div class="o_route_node_card ${nodeThemeClass(d.x_station_type)}${selected}" data-route-node-id="${escapeHtml(cell.id)}">`,
        badges,
        `<div class="o_node_header">`,
        `<div class="o_node_icon">${escapeHtml(String(code).substring(0, 4))}</div>`,
        `<div class="o_node_title">${escapeHtml(title)}</div>`,
        `<div class="o_node_actions"><span class="o_node_op" title="删除节点" data-route-node-delete="1">✖️</span></div>`,
        `</div>`,
        `</div>`,
    ].join("");
}

export class RouteFlowEditor extends Component {
    static template = "sn_wsd_route_graph.RouteFlowEditor";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.containerRef = useRef("container");
        const actionCtx = (this.props.action && this.props.action.context) || {};
        this.routeId = (this.props.record && this.props.record.resId) ||
            this.props.routeId ||
            actionCtx.active_id ||
            (actionCtx.active_ids && actionCtx.active_ids[0]) ||
            null;
        this.isFullscreenAction = Boolean(this.props.action);
        this.graph = null;
        this.selectedNode = null;
        this.allOperations = [];
        this._loading = false; // suppress dirty tracking while (re)loading the graph
        // Canvas ↔ record bridge state: _lastPushedJson is the json we pushed
        // into the record (canvas edits); _recordJson/_recordVersion mirror the
        // last observed record values (server truth after save/discard).
        this._lastPushedJson = null;
        this._recordJson = "";
        this._recordVersion = 0;
        this._observedOnce = false;
        this.state = useState({
            selected: null,
            usedOpIds: [],
            paletteVersion: 0,
        });
        this._injectStyles();
        onMounted(() => this._build());
        // The canvas is part of the form record: every edit is pushed into
        // record.route_flow_json and persisted/versioned by the standard form
        // save (保存). This reactive observer catches everything the canvas
        // cannot see: the record id appearing (first save of a new record),
        // version bumps after save, and the native 取消 (Discard) reverting
        // the flow json — the canvas then redraws from the record.
        useRecordObserver((record) => this._onRecordObserved(record));
    }

    _onRecordObserved(record) {
        const data = (record && record.data) || {};
        const json = data.route_flow_json || "";
        const version = data.version || 0;
        const routeId = (record && (record.resId ?? record.res_id)) || data.id || null;
        // First observation (setup, before the canvas exists): baseline only.
        if (!this._observedOnce) {
            this._observedOnce = true;
            this._recordJson = json;
            this._recordVersion = version;
            return;
        }
        const jsonChangedExternally = json !== this._recordJson && json !== this._lastPushedJson;
        const versionUpgraded = version > (this._recordVersion || 0);
        this._recordJson = json;
        this._recordVersion = version;
        if (versionUpgraded && version > 0) {
            this.notification.add(`流程已升级至 V${version}`, { type: "success" });
        }
        // First save of a brand-new record: the id appeared — rebuild so the
        // canvas binds to the persisted route (palette + server positions).
        if (routeId && String(routeId) !== String(this.routeId)) {
            this.routeId = routeId;
            this._build();
            return;
        }
        // The record's flow json changed without coming from the canvas
        // (native 取消 discarding edits, a restore from the version history,
        // another tab...). Redraw from it unless it matches what's on screen.
        if (jsonChangedExternally && this.graph && !this._loading) {
            try {
                const parsed = JSON.parse(json || '{"nodes": [],"edges": []}');
                if (!this._graphMatches(parsed)) {
                    this._fullRebuild(parsed);
                }
            } catch (e) { /* malformed json: keep the canvas as is */ }
        }
    }

    // Canonical comparison of a {nodes, edges} graph against the canvas:
    // key-sorted, node/edge-sorted — immune to json formatting differences
    // between JSON.stringify (pushed) and the server's json.dumps (reloaded).
    _graphMatches(parsed) {
        const canon = (value) => {
            if (Array.isArray(value)) return value.map(canon);
            if (value && typeof value === "object") {
                const out = {};
                for (const k of Object.keys(value).sort()) out[k] = canon(value[k]);
                return out;
            }
            return value === undefined ? null : value;
        };
        const graphKey = (g) => {
            const nodes = ((g && g.nodes) || []).slice()
                .sort((a, b) => String(a.uid).localeCompare(String(b.uid)));
            const edges = ((g && g.edges) || []).slice()
                .sort((a, b) => `${a.source}>${a.target}`.localeCompare(`${b.source}>${b.target}`));
            return JSON.stringify(canon({ nodes, edges }));
        };
        return graphKey(parsed) === graphKey(this._serializeGraph());
    }

    // The record id may appear after the first save; always read it fresh.
    get currentRouteId() {
        const rec = this.props.record;
        if (rec) {
            if (rec.resId) return rec.resId;
            if (rec.res_id) return rec.res_id;
            if (rec.data && rec.data.id) return rec.data.id;
        }
        return this.routeId || null;
    }

    _injectStyles() {
        if (document.getElementById("o-route-flow-css")) return;
        const style = document.createElement("style");
        style.id = "o-route-flow-css";
        style.textContent = [
            /* Outer shell matches the X6 agentFlow showcase: clean white panels, #DFE3E8 borders. */
            ".o_route_flow_shell { position: relative; display: flex; gap: 0; height: 640px; border: 1px solid #dfe3e8; background: #fff; overflow: hidden; }",
            ".o_route_flow_palette { width: 160px; flex-shrink: 0; border-right: 1px solid #dfe3e8; background: #fff; display: flex; flex-direction: column; height: 100%; }",
            ".o_route_flow_palette_header { padding: 10px 14px; font-size: 13px; font-weight: 600; color: #141414; border-bottom: 1px solid #dfe3e8; background: #fff; }",
            ".o_route_flow_palette_body { flex: 1; overflow-y: auto; padding: 10px 12px; background: #fff; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-content: start; }",
            ".o_palette_group_title { grid-column: 1 / -1; margin: 4px 0 6px; font-size: 11px; font-weight: 600; color: #8c8c8c; text-transform: uppercase; letter-spacing: 0.02em; }",
            ".o_palette_card { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; width: 100%; height: 56px; margin: 0; padding: 6px 4px; border: 1px solid #5f95ff; border-radius: 8px; background: #fff; box-sizing: border-box; cursor: pointer; user-select: none; }",
            ".o_palette_card.o_used { opacity: 0.48; cursor: not-allowed; }",
            ".o_palette_card .o_palette_icon { flex: 0 0 auto; width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; }",
            ".o_palette_card .o_palette_name { width: 100%; font-size: 12px; font-weight: 600; color: #141414; line-height: 14px; text-align: center; word-break: break-word; overflow: hidden; }",
            ".o_palette_theme_blue .o_palette_icon { background: #f0f5ff; color: #1d39c4; }",
            ".o_palette_theme_green .o_palette_icon { background: #e6fffb; color: #08979c; }",
            ".o_palette_theme_orange .o_palette_icon { background: #fff7e6; color: #fa8c16; }",
            ".o_palette_theme_red .o_palette_icon { background: #fff1f0; color: #cf1322; }",
            ".o_palette_theme_gray .o_palette_icon { background: #f5f5f5; color: #595959; }",
            ".o_route_flow_canvas { flex: 1; min-width: 0; height: 100%; background: #fff; }",
            ".o_route_flow_panel { position: absolute; top: 10px; right: 10px; bottom: 10px; width: 248px; background: #fff; border: 1px solid rgba(0,0,0,0.06); border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.16); padding: 14px; overflow-y: auto; box-sizing: border-box; z-index: 5; animation: o_panel_slide 0.18s ease; }",
            "@keyframes o_panel_slide { from { transform: translateX(16px); opacity: 0; } to { transform: none; opacity: 1; } }",
            ".o_route_flow_panel_empty { width: 240px; flex-shrink: 0; border-left: 1px solid #dfe3e8; background: #fff; display: flex; align-items: center; justify-content: center; height: 100%; }",
            /* Property panel (属性面板) */
            ".o_prop_head { display: flex; justify-content: space-between; align-items: center; padding-bottom: 8px; border-bottom: 1px solid #dfe3e8; }",
            ".o_prop_head strong { font-size: 14px; color: #141414; }",
            ".o_prop_close { background: none; border: 0; color: #bfbfbf; font-size: 18px; line-height: 1; cursor: pointer; padding: 0 2px; }",
            ".o_prop_close:hover { color: #8c8c8c; }",
            ".o_prop_sub { margin: 10px 0 16px; font-size: 13px; font-weight: 600; color: #141414; }",
            ".o_prop_label { display: block; margin-bottom: 4px; font-size: 12px; font-weight: 600; color: #8c8c8c; }",
            ".o_prop_tags { display: flex; gap: 8px; }",
            ".o_prop_tag { padding: 4px 14px; font-size: 12px; font-weight: 600; border: 1px solid #d9d9d9; border-radius: 14px; background: #fff; color: #595959; cursor: pointer; }",
            ".o_prop_tag:hover { border-color: #5f95ff; color: #5f95ff; }",
            ".o_prop_tag_on { color: #fff !important; }",
            ".o_prop_tag_start { background: #52c41a; border-color: #52c41a; }",
            ".o_prop_tag_end { background: #ff4d4f; border-color: #ff4d4f; }",
            ".o_route_flow_toolbar { min-height: 42px; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid #dfe3e8; border-bottom: 0; background: #fff; }",
            ".o_route_flow_hint { margin-left: auto; font-size: 12px; color: #8c8c8c; }",
            ".o_route_flow_x6 .x6-port-body { cursor: crosshair; }",
            ".o_route_flow_x6 .x6-edge-path[stroke='transparent'] { stroke-width: 20; }",
            ".o_route_flow_x6 .x6-edge:hover .x6-edge-path:last-child { stroke: #ff4d4f !important; }",
            /* Node card — same look as the X6 agentFlow `agent-card` (border drawn by the SVG body rect). */
            ".o_route_node_card { position: relative; display: flex; flex-direction: column; justify-content: center; width: 100%; height: 100%; box-sizing: border-box; padding: 8px; background: #fff; gap: 6px; }",
            /* Start/end corner badges */
            ".o_node_badges { position: absolute; top: 0; left: 0; display: flex; flex-direction: column; gap: 2px; z-index: 2; pointer-events: none; }",
            ".o_node_badge { font-size: 10px; font-weight: 600; line-height: 14px; padding: 1px 6px; color: #fff; white-space: nowrap; border-radius: 0 0 6px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.12); }",
            ".o_node_badge_start { background: #52c41a; }",
            ".o_node_badge_end { background: #ff4d4f; border-radius: 0; }",
            ".o_route_node_card.o_selected { background: #f0f7ff; }",
            ".o_route_node_card .o_node_header { display: flex; align-items: center; gap: 8px; }",
            ".o_route_node_card .o_node_icon { flex: 0 0 auto; width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; background: #f0f5ff; color: #1d39c4; }",
            ".o_route_node_card.o_node_theme_green .o_node_icon { background: #e6fffb; color: #08979c; }",
            ".o_route_node_card.o_node_theme_orange .o_node_icon { background: #fff7e6; color: #fa8c16; }",
            ".o_route_node_card.o_node_theme_red .o_node_icon { background: #fff1f0; color: #cf1322; }",
            ".o_route_node_card .o_node_title { flex: 1; min-width: 0; font-size: 14px; color: #141414; font-weight: 600; line-height: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }",
            ".o_route_node_card .o_node_actions { margin-left: auto; display: flex; align-items: center; }",
            ".o_route_node_card .o_node_actions .o_node_op { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 5px; font-size: 15px; line-height: 1; color: #8c8c8c; cursor: pointer; }",
            ".o_route_node_card .o_node_actions .o_node_op:hover { color: #ff4d4f; background: rgba(255,77,79,0.12); }",
            ".o_route_flow_x6 .x6-node foreignObject body { margin: 0; padding: 0; }",
        ].join("\n");
        document.head.appendChild(style);
    }

    get paletteGroups() {
        void this.state.paletteVersion;
        const usedSet = new Set(this.state.usedOpIds);
        const groups = {};
        for (const op of this.allOperations) {
            const s = op.x_process_section || "other";
            (groups[s] = groups[s] || []).push(Object.assign({}, op, { used: usedSet.has(op.id) }));
        }
        return SECTION_ORDER.filter(s => groups[s]).map(s => ({ key: s, label: SECTION_LABELS[s] || s, ops: groups[s] }))
            .concat(groups.other ? [{ key: "other", label: "其他", ops: groups.other }] : []);
    }

    get paletteAvailableCount() {
        const usedSet = new Set(this.state.usedOpIds);
        return this.allOperations.filter(o => !usedSet.has(o.id)).length;
    }

    get stationTypeLabel() {
        if (!this.state.selected?.x_station_type) return "-";
        return STATION_LABELS[this.state.selected.x_station_type] || this.state.selected.x_station_type;
    }

    paletteIcon(op) {
        return (op.code || op.name || "OP").substring(0, 4);
    }

    paletteDesc(op) {
        return STATION_LABELS[op.x_station_type] || op.x_process_section || op.code || "";
    }

    paletteThemeClass(op) {
        const type = op.x_station_type || "";
        if (type === "programming" || type === "final_test") return "o_palette_theme_green";
        if (type === "calibration" || type === "aging") return "o_palette_theme_orange";
        if (type === "repair") return "o_palette_theme_red";
        if (type === "assembly" || type === "inspection" || type === "packaging") return "o_palette_theme_blue";
        return "o_palette_theme_gray";
    }

    _createPortGroup(position) {
        return {
            position,
            attrs: {
                // Large transparent magnet — always active, so connections are easy to
                // grab/drop even before the small visible dot appears on hover.
                hit: {
                    r: PORT_HIT_RADIUS,
                    magnet: true,
                    fill: "transparent",
                    stroke: "transparent",
                    cursor: "crosshair",
                    style: { pointerEvents: "all" },
                },
                body: {
                    r: PORT_DOT_RADIUS,
                    magnet: true,
                    stroke: COLOR_GRAY,
                    strokeWidth: 1,
                    fill: COLOR_GRAY,
                    style: { visibility: "hidden" },
                },
            },
        };
    }

    async _build() {
        if (!window.X6) {
            this.notification.add("X6 library not loaded", { type: "danger" });
            return;
        }
        // Rebuild case (record id appeared after save): drop the previous canvas.
        if (this.graph) {
            try { this.graph.dispose(); } catch (e) { /* UMD may ignore */ }
            this.graph = null;
            this.selectedNode = null;
            this.state.selected = null;
        }
        try {
            const routeId = this.currentRouteId;
            let graphData = { nodes: [], edges: [] };
            let operations = [];
            if (routeId) {
                // Saved record: flow graph + palette.
                const [gd, ops] = await Promise.all([
                    this.orm.call("sn.wsd.process.route", "get_route_graph", [routeId]),
                    this.orm.call("sn.wsd.process.route", "get_route_operations", [routeId]),
                ]);
                graphData = gd;
                operations = ops;
            } else {
                // Unsaved record: empty canvas, but the palette still loads the
                // company's operations so nodes can be placed right away.
                operations = await this.orm.call(
                    "sn.wsd.process.route", "get_route_operations_for_company", []);
            }
            this.allOperations = operations;
            this.state.usedOpIds = graphData.nodes.map(n => n.operation_id).filter(Boolean);
            this.state.paletteVersion++;
            this._loading = true;

            const X6 = window.X6;

            if (!routeAgentEdgeRegistered) {
                try {
                    X6.Graph.registerEdge(
                        "route-agent-edge",
                        {
                            inherit: "edge",
                            attrs: {
                                line: {
                                    stroke: COLOR_BLUE,
                                    strokeWidth: 2,
                                    targetMarker: "block",
                                },
                            },
                        },
                        true,
                    );
                    routeAgentEdgeRegistered = true;
                } catch (e) {
                    // Another widget instance may already have registered this shape.
                }
            }

            if (!routeAgentCardRegistered) {
                try {
                    // HTML shape renders the card through a foreignObject, exactly like
                    // the X6 agentFlow react-shape does.
                    X6.Shape.HTML.register({
                        shape: "route-op-card",
                        width: CARD_W,
                        height: CARD_H,
                        effect: ["data"],
                        html: (cell) => buildRouteCardHtml(cell),
                    });
                    routeAgentCardRegistered = true;
                } catch (e) {
                    // Another widget instance may already have registered this shape.
                }
            }

            let graph;
            graph = new X6.Graph({
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
                    createEdge() {
                        return graph.createEdge({ shape: "route-agent-edge" });
                    },
                    validateConnection({ targetMagnet }) {
                        return !!targetMagnet;
                    },
                },
                highlighting: {
                    magnetAdsorbed: {
                        name: "stroke",
                        args: { attrs: { fill: COLOR_BLUE, stroke: COLOR_BLUE } },
                    },
                },
                interacting: { nodeMovable: true, edgeMovable: true, magnetConnectable: true },
            });

            // --- Node card delete (✖️) is handled inside graph.on("node:click")
            //     above: it receives the native DOM event, works after graph
            //     rebuilds, and avoids stale closures over an old graph. ---

            // --- Port visibility + coloring (adapted from example) ---
            const isPortConnected = (node, portId) => {
                return graph.getConnectedEdges(node).some(e =>
                    (e.getSourceCellId() === node.id && e.getSourcePortId() === portId) ||
                    (e.getTargetCellId() === node.id && e.getTargetPortId() === portId));
            };
            const setPortVisible = (node, portId, visible) => {
                try {
                    node.setPortProp(portId, "attrs/body/style/visibility", visible ? "visible" : "hidden");
                } catch (e) { /* UMD may ignore */ }
            };
            const setPortColor = (node, portId, color) => {
                try {
                    node.setPortProp(portId, "attrs/body/fill", color);
                    node.setPortProp(portId, "attrs/body/stroke", color);
                } catch (e) { /* UMD may ignore */ }
            };
            const setPortDot = (node, portId, visible, color) => {
                setPortVisible(node, portId, visible);
                if (color) setPortColor(node, portId, color);
            };
            graph.on("node:mouseenter", ({ node }) => {
                node.getPorts().forEach(p => {
                    setPortVisible(node, p.id, true);
                });
            });
            graph.on("node:mouseleave", ({ node }) => {
                node.getPorts().forEach(p => {
                    const connected = isPortConnected(node, p.id);
                    setPortVisible(node, p.id, connected);
                    setPortColor(node, p.id, connected ? COLOR_BLUE : COLOR_GRAY);
                });
            });

            // --- Edge tools: enlarged button-remove on hover ---
            graph.on("edge:mouseenter", ({ edge }) => {
                try { edge.addTools(this._edgeRemoveTool()); } catch (e) {}
            });
            graph.on("edge:mouseleave", ({ edge }) => {
                try { edge.removeTools(); } catch (e) {}
            });

            // --- Edge lifecycle: color ports on connect/disconnect ---
            graph.on("edge:connected", ({ currentCell, currentPort }) => {
                if (currentCell && currentPort) setPortDot(currentCell, currentPort, true, COLOR_BLUE);
            });
            graph.on("edge:added", ({ edge }) => {
                [[edge.getSourceCellId(), edge.getSourcePortId()], [edge.getTargetCellId(), edge.getTargetPortId()]].forEach(([cid, pid]) => {
                    const c = cid && graph.getCellById(cid);
                    if (c && c.isNode && c.isNode() && pid) setPortDot(c, pid, true, COLOR_BLUE);
                });
            });
            graph.on("edge:removed", ({ edge }) => {
                [[edge.getSourceCellId(), edge.getSourcePortId()], [edge.getTargetCellId(), edge.getTargetPortId()]].forEach(([cid, pid]) => {
                    const c = cid && graph.getCellById(cid);
                    if (c && c.isNode && c.isNode() && pid && !isPortConnected(c, pid)) setPortDot(c, pid, false, COLOR_GRAY);
                });
            });

            // --- Node click → detail panel (✖️ on the card deletes instead) ---
            graph.on("node:click", (args) => {
                const native = args.e || args;
                const target = native && native.target;
                if (target && target.closest && target.closest("[data-route-node-delete]")) {
                    graph.removeCells([args.node]);
                    return;
                }
                this._selectNode(args.node);
            });
            graph.on("blank:click", () => this._selectNode(null));

            // --- Keyboard delete ---
            graph.on("node:delete", ({ node }) => {
                graph.removeCells([node]);
            });

            // --- Node removed → return op to palette ---
            graph.on("cell:removed", ({ cell }) => {
                if (cell.isNode && cell.isNode()) {
                    const d = cell.getData();
                    if (d && d.operation_id) {
                        this.state.usedOpIds = this.state.usedOpIds.filter(id => id !== d.operation_id);
                        this.state.paletteVersion++;
                    }
                    if (this.selectedNode === cell) this._selectNode(null);
                }
            });

            // --- Render nodes (use saved positions so dragged layout is remembered) ---
            graphData.nodes.forEach((n, i) => {
                const p = this._nodeXY(n, i);
                this._addNode(graph, n, p.x, p.y);
            });
            this._addDataEdges(graph, graphData.edges);

            // --- Apply magnet as fallback (UMD may ignore markup attrs) ---
            this._applyPortMagnets();
            this._refreshPortStates();

            this.graph = graph;
            this.state.paletteVersion++;

            // --- Every structural/data edit after load is pushed into the
            //     form record (route_flow_json): the standard form 保存
            //     persists and versions it server-side (保存即版本) ---
            const markDirty = () => {
                if (this._loading) return;
                this._pushToRecord();
            };
            graph.on("cell:added", markDirty);
            graph.on("cell:removed", markDirty);
            graph.on("cell:change:data", markDirty);
            // dragging only changes layout: push ONCE when the drag ends
            // (node:moved), never per-frame -- mid-drag pushes make the
            // record observer rebuild the canvas under the pointer
            graph.on("node:moved", markDirty);

            this._loading = false;
            // Fit the whole flow into view (re-fit once the card markup has settled).
            this._fitView();
            setTimeout(() => this._fitView(), 300);
        } catch (err) {
            this._loading = false;
            this.notification.add("加载流程图失败: " + String(err.message || err), { type: "danger" });
        }
    }

    // Resolve a node's position: use the saved x/y from the JSON graph so that
    // user-dragged layout is remembered; fall back to a vertical column otherwise.
    _nodeXY(data, i) {
        const dx = Number.parseFloat(data && data.x);
        const dy = Number.parseFloat(data && data.y);
        return {
            x: Number.isFinite(dx) ? dx : 30,
            y: Number.isFinite(dy) ? dy : (30 + i * 80),
        };
    }

    _addNode(graph, data, x, y) {
        const mkPort = (id, group) => ({
            id, group,
            markup: [
                { tagName: "circle", selector: "hit", attrs: { r: PORT_HIT_RADIUS, magnet: true, fill: "transparent", stroke: "transparent", cursor: "crosshair", style: { pointerEvents: "all" } } },
                { tagName: "circle", selector: "body", attrs: { r: PORT_DOT_RADIUS, magnet: true, stroke: COLOR_GRAY, strokeWidth: 1, fill: COLOR_GRAY } },
            ],
        });
        const node = graph.addNode({
            id: data.uid != null ? String(data.uid) : undefined,
            x, y, width: CARD_W, height: CARD_H,
            shape: "route-op-card",
            attrs: {
                body: { fill: "#fff", stroke: COLOR_BLUE, strokeWidth: 1, rx: 8, ry: 8, magnet: true, cursor: "crosshair" },
            },
            ports: {
                // Only top/bottom ports — connections must run vertically.
                groups: {
                    top: this._createPortGroup("top"),
                    bottom: this._createPortGroup("bottom"),
                },
                items: [
                    mkPort("top", "top"),
                    mkPort("bottom", "bottom"),
                ],
            },
            data,
        });
        return node;
    }

    _applyPortMagnets() {
        const apply = () => {
            if (!this.containerRef?.el) return;
            // Port magnets: reinforce on every port circle (the UMD build may ignore
            // the magnet attr set via markup). Both the transparent hit area and the
            // visible dot act as connection magnets.
            this.containerRef.el.querySelectorAll(".x6-port circle").forEach(c => {
                c.setAttribute("magnet", "true");
                c.setAttribute("cursor", "crosshair");
            });
            // Body magnets: drag from card background to connect
            this.containerRef.el.querySelectorAll(".x6-node rect:first-of-type").forEach(r => {
                r.setAttribute("magnet", "true");
                r.setAttribute("cursor", "crosshair");
            });
        };
        apply();
        setTimeout(apply, 200);
        setTimeout(apply, 1000);
    }

    _refreshPortStates() {
        if (!this.graph) return;
        for (const node of this.graph.getNodes()) {
            node.getPorts().forEach(p => {
                const connected = this.graph.getConnectedEdges(node).some(e =>
                    (e.getSourceCellId() === node.id && e.getSourcePortId() === p.id) ||
                    (e.getTargetCellId() === node.id && e.getTargetPortId() === p.id));
                try {
                    node.setPortProp(p.id, "attrs/body/style/visibility", connected ? "visible" : "hidden");
                    node.setPortProp(p.id, "attrs/body/fill", connected ? COLOR_BLUE : COLOR_GRAY);
                    node.setPortProp(p.id, "attrs/body/stroke", connected ? COLOR_BLUE : COLOR_GRAY);
                } catch (e) { /* UMD may ignore */ }
            });
        }
    }

    // -- Palette --
    onPaletteClick(ev) {
        if (!this.graph) return;
        const opId = parseInt(ev.currentTarget.getAttribute("data-op-id"), 10);
        if (!opId || this.state.usedOpIds.includes(opId)) return;
        const op = this.allOperations.find(o => o.id === opId);
        if (!op) return;
        const existing = this.graph.getNodes();
        // Stack new nodes below the lowest one so they follow the vertical flow.
        const y = existing.length ? Math.max(...existing.map(n => n.getPosition().y)) + 80 : 30;
        this._addNode(this.graph, {
            uid: "new_" + Date.now(), id: null, operation_id: op.id, name: op.name,
            step_code: op.code, sequence: (existing.length + 1) * 10, x_station_type: op.x_station_type,
            time_cycle_manual: 60, x_allow_entry: existing.length === 0, x_allow_exit: false,
            x_allow_serial_creation: false,
        }, 30, y);
        this.state.usedOpIds = [...this.state.usedOpIds, opId];
        this.state.paletteVersion++;
        this._applyPortMagnets();
        this._refreshPortStates();
    }

    // -- Selection --
    _selectNode(node) {
        const previous = this.selectedNode;
        // Deselect previous: restore normal style
        if (previous && previous !== node) {
            previous.attr("body/strokeWidth", 1);
            previous.setData({ _selected: false });
        }
        this.selectedNode = node;
        if (node) {
            // Selected: thicker border + tinted card background
            node.attr("body/strokeWidth", 2);
            if (previous !== node) node.setData({ _selected: true });
            const d = node.getData() || {};
            this.state.selected = {
                uid: node.id, step_code: d.step_code || "", name: d.name || "",
                x_station_type: d.x_station_type || "", time_cycle_manual: d.time_cycle_manual || 0,
                sequence: d.sequence || 100, x_allow_entry: d.x_allow_entry || false,
                x_allow_exit: d.x_allow_exit || false,
                x_allow_serial_creation: d.x_allow_serial_creation || false,
                predecessors: d.predecessors || [],
            };
        } else {
            this.state.selected = null;
        }
    }

    onClosePanel() { this._selectNode(null); }


    onClickBack() {
        if (this.actionService) {
            this.actionService.restore();
        }
    }

    // Scale + translate so every node is visible. Called on load and from the toolbar.
    _fitView() {
        if (!this.graph) return;
        try { this.graph.zoomToFit({ padding: 24, maxScale: 1 }); } catch (e) { /* empty graph */ }
    }

    onFitScreen() {
        this._fitView();
    }

    // -- Field change handlers --
    onSequenceChange(ev) { if (this.state.selected) { this.state.selected.sequence = parseInt(ev.target.value, 10) || 100; this._syncToNode(); } }
    onToggleStart() { if (!this.state.selected) return; this.state.selected.x_allow_entry = !this.state.selected.x_allow_entry; this._syncToNode(); }
    onToggleEnd() { if (!this.state.selected) return; this.state.selected.x_allow_exit = !this.state.selected.x_allow_exit; this._syncToNode(); }

    _syncToNode() {
        if (!this.selectedNode || !this.state.selected) return;
        const s = this.state.selected;
        this.selectedNode.setData({
            step_code: s.step_code, name: s.name, x_station_type: s.x_station_type,
            time_cycle_manual: s.time_cycle_manual, sequence: s.sequence,
            x_allow_entry: s.x_allow_entry, x_allow_exit: s.x_allow_exit, x_allow_serial_creation: s.x_allow_serial_creation,
        });
    }

    // -- Canvas → form record bridge --
    // The canvas has no save button of its own: every edit is pushed into
    // record.route_flow_json, and the standard form save (top bar / Ctrl+S)
    // persists AND versions it server-side (保存即版本).
    _serializeGraph() {
        if (!this.graph) return { nodes: [], edges: [] };
        const nodes = this.graph.getNodes().map(n => {
            const d = Object.assign({}, n.getData() || {});
            delete d._selected; // UI-only flag, keep it out of the payload
            const pos = n.getPosition();
            const nid = parseInt(n.id, 10);
            return Object.assign(d, {
                uid: n.id,
                id: Number.isFinite(nid) ? nid : null,
                x: Math.round(pos.x),
                y: Math.round(pos.y),
            });
        });
        const edges = this.graph.getEdges().map(e => {
            const s = e.getSourceNode(), t = e.getTargetNode();
            return { source: s && s.id, target: t && t.id };
        }).filter(e => e.source && e.target);
        return { nodes, edges };
    }

    _pushToRecord() {
        const record = this.props.record;
        if (!record || !record.update) return;
        this._lastPushedJson = JSON.stringify(this._serializeGraph());
        try {
            record.update({ route_flow_json: this._lastPushedJson });
        } catch (e) {
            this.notification.add("画布写入表单失败: " + String(e.message || e), { type: "danger" });
        }
    }

    _fullRebuild(graphData) {
        this._loading = true;
        const g = this.graph;
        g.clearCells();
        this.selectedNode = null;
        this.state.selected = null;
        graphData.nodes.forEach((n, i) => { const p = this._nodeXY(n, i); this._addNode(g, n, p.x, p.y); });
        this._addDataEdges(g, graphData.edges);
        this._applyPortMagnets();
        this._refreshPortStates();
        this.state.usedOpIds = graphData.nodes.map(n => n.operation_id).filter(Boolean);
        this.state.paletteVersion++;
        this._fitView();
        this._loading = false;
    }

    // Connect loaded edges to the ports on the sides that face each other, so the
    // line attaches on the node borders (outside) instead of diving into the center.
    _addDataEdges(graph, edges) {
        edges.forEach(e => {
            const sNode = graph.getCellById(String(e.source));
            const tNode = graph.getCellById(String(e.target));
            if (!sNode || !tNode) return;
            const { out: srcPort, in: tgtPort } = this._facingPorts(sNode, tNode);
            graph.addEdge({
                shape: "route-agent-edge",
                source: { cell: String(e.source), port: srcPort },
                target: { cell: String(e.target), port: tgtPort },
            });
        });
    }

    _facingPorts(sNode, tNode) {
        const s = sNode.getPosition();
        const t = tNode.getPosition();
        // Only vertical (top/bottom) connections are allowed.
        return s.y <= t.y ? { out: "bottom", in: "top" } : { out: "top", in: "bottom" };
    }

    // Enlarged edge delete button (default X6 button-remove is only r=7 — too small).
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
}

registry.category("view_widgets").add("route_flow_editor", { component: RouteFlowEditor });

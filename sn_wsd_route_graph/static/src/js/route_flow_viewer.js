/** @odoo-module **/
import { Component, onWillUnmount, onMounted, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { buildRouteCardHtml } from "./route_flow_widget.js";

/**
 * Read-only renderer for archived route flow graphs (版本对比/版本查看).
 * Reuses the editor's node card + straight edges, without any editing affordance.
 */

const COLOR_GRAY = "#C2C8D5";
const COLOR_BLUE = "#5F95FF";
const PORT_DOT_RADIUS = 4;
const CARD_W = 200;
const CARD_H = 56;

let viewerCardRegistered = false;
let viewerEdgeRegistered = false;

export class RouteFlowViewer extends Component {
    static template = "sn_wsd_route_graph.RouteFlowViewer";
    static props = {
        graphData: { type: Object, optional: true },
        height: { type: String, optional: true },
        emptyLabel: { type: String, optional: true },
    };

    setup() {
        this.containerRef = useRef("viewer");
        this.graph = null;
        this._injectStyles();
        onMounted(() => this._render());
        onWillUnmount(() => this._dispose());
    }

    _injectStyles() {
        if (document.getElementById("o-route-flow-viewer-css")) return;
        const style = document.createElement("style");
        style.id = "o-route-flow-viewer-css";
        style.textContent = [
            ".o_flow_viewer { position: relative; border: 1px solid #dfe3e8; background: #fff; }",
            ".o_flow_viewer .o_flow_viewer_empty { display: flex; align-items: center; justify-content: center; height: 320px; color: #8c8c8c; font-size: 13px; }",
            /* Hide the editor's delete affordance inside read-only cards */
            ".o_flow_viewer .o_route_node_card .o_node_actions { display: none; }",
            ".o_flow_viewer .x6-node foreignObject body { margin: 0; padding: 0; }",
            /* Card visuals — subset mirrored from the editor */
            ".o_route_node_card { position: relative; display: flex; flex-direction: column; justify-content: center; width: 100%; height: 100%; box-sizing: border-box; padding: 8px; background: #fff; gap: 6px; }",
            ".o_node_badges { position: absolute; top: 0; left: 0; display: flex; flex-direction: column; gap: 2px; z-index: 2; pointer-events: none; }",
            ".o_node_badge { font-size: 10px; font-weight: 600; line-height: 14px; padding: 1px 6px; color: #fff; white-space: nowrap; border-radius: 0 0 6px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.12); }",
            ".o_node_badge_start { background: #52c41a; }",
            ".o_node_badge_end { background: #ff4d4f; border-radius: 0; }",
            ".o_route_node_card .o_node_header { display: flex; align-items: center; gap: 8px; }",
            ".o_route_node_card .o_node_icon { flex: 0 0 auto; width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; background: #f0f5ff; color: #1d39c4; }",
            ".o_route_node_card.o_node_theme_green .o_node_icon { background: #e6fffb; color: #08979c; }",
            ".o_route_node_card.o_node_theme_orange .o_node_icon { background: #fff7e6; color: #fa8c16; }",
            ".o_route_node_card.o_node_theme_red .o_node_icon { background: #fff1f0; color: #cf1322; }",
            ".o_route_node_card .o_node_title { flex: 1; min-width: 0; font-size: 14px; color: #141414; font-weight: 600; line-height: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }",
            /* Compare layout */
            ".o_route_compare_toolbar { display: flex; align-items: center; gap: 12px; padding: 10px 12px; background: #fff; border-bottom: 1px solid #dfe3e8; }",
            ".o_route_compare_panes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 12px; background: #f5f5f5; min-height: 70vh; }",
            ".o_route_compare_pane { display: flex; flex-direction: column; background: #fff; border: 1px solid #dfe3e8; border-radius: 8px; overflow: hidden; }",
            ".o_route_compare_pane_header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; font-size: 13px; font-weight: 600; color: #141414; border-bottom: 1px solid #dfe3e8; }",
            ".o_route_compare_pane_canvas { height: 560px; }",
            ".o_route_compare_pane_canvas .o_flow_viewer { height: 100%; border: 0; }",
        ].join("\n");
        document.head.appendChild(style);
    }

    _dispose() {
        if (this.graph) {
            try { this.graph.dispose(); } catch (e) { /* UMD may ignore */ }
            this.graph = null;
        }
    }

    _nodeXY(data, i) {
        const dx = Number.parseFloat(data && data.x);
        const dy = Number.parseFloat(data && data.y);
        return {
            x: Number.isFinite(dx) ? dx : 30,
            y: Number.isFinite(dy) ? dy : (30 + i * 80),
        };
    }

    _render() {
        this._dispose();
        const el = this.containerRef.el;
        const data = this.props.graphData;
        if (!el || !data || !window.X6) return;

        const X6 = window.X6;

        if (!viewerEdgeRegistered) {
            try {
                X6.Graph.registerEdge("route-agent-edge", {
                    inherit: "edge",
                    attrs: { line: { stroke: COLOR_BLUE, strokeWidth: 2, targetMarker: "block" } },
                }, true);
                viewerEdgeRegistered = true;
            } catch (e) { /* already registered by the editor */ }
        }
        if (!viewerCardRegistered) {
            try {
                X6.Shape.HTML.register({
                    shape: "route-op-card",
                    width: CARD_W,
                    height: CARD_H,
                    effect: ["data"],
                    html: (cell) => buildRouteCardHtml(cell),
                });
                viewerCardRegistered = true;
            } catch (e) { /* already registered by the editor */ }
        }

        const graph = new X6.Graph({
            container: el,
            grid: true,
            panning: { enabled: true },
            mousewheel: { enabled: true, minScale: 0.5, maxScale: 3 },
            interacting: false,
        });
        this.graph = graph;

        const portGroup = (position) => ({
            position,
            attrs: {
                body: {
                    r: PORT_DOT_RADIUS,
                    stroke: COLOR_GRAY,
                    strokeWidth: 1,
                    fill: COLOR_GRAY,
                    style: { visibility: "hidden" },
                },
            },
        });
        const mkPort = (id, group) => ({
            id, group,
            markup: [
                { tagName: "circle", selector: "body", attrs: { r: PORT_DOT_RADIUS, stroke: COLOR_GRAY, strokeWidth: 1, fill: COLOR_GRAY } },
            ],
        });

        const nodes = (data.nodes || []).map((n, i) => {
            const p = this._nodeXY(n, i);
            return graph.addNode({
                id: n.uid != null ? String(n.uid) : `v${i}`,
                x: p.x, y: p.y, width: CARD_W, height: CARD_H,
                shape: "route-op-card",
                attrs: { body: { fill: "#fff", stroke: COLOR_BLUE, strokeWidth: 1, rx: 8, ry: 8 } },
                ports: {
                    groups: { top: portGroup("top"), bottom: portGroup("bottom") },
                    items: [mkPort("top", "top"), mkPort("bottom", "bottom")],
                },
                data: n,
            });
        });

        const byUid = {};
        nodes.forEach((node, i) => {
            const n = data.nodes[i];
            if (n && n.uid != null) byUid[String(n.uid)] = node;
            else byUid[String(n.id)] = node;
        });
        (data.edges || []).forEach((e) => {
            const s = byUid[String(e.source)];
            const t = byUid[String(e.target)];
            if (!s || !t) return;
            const sp = s.getPosition(), tp = t.getPosition();
            const out = sp.y <= tp.y ? "bottom" : "top";
            const inp = sp.y <= tp.y ? "top" : "bottom";
            graph.addEdge({
                shape: "route-agent-edge",
                source: { cell: s.id, port: out },
                target: { cell: t.id, port: inp },
            });
        });

        try { graph.zoomToFit({ padding: 24, maxScale: 1 }); } catch (e) { /* empty graph */ }
    }
}

/**
 * Form widget bound to a sn.wsd.process.route.version record: renders the
 * archived flow graph read-only via read_flow_graph().
 */
export class RouteFlowViewerWidget extends Component {
    static template = "sn_wsd_route_graph.RouteFlowViewerWidget";
    static components = { RouteFlowViewer };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ graphData: null });
        const record = this.props.record;
        const versionId = record && record.resId;
        if (versionId) {
            this.orm.call("sn.wsd.process.route.version", "read_flow_graph", [versionId])
                .then((graphData) => { this.state.graphData = graphData; });
        }
    }
}

registry.category("view_widgets").add("route_flow_viewer", { component: RouteFlowViewerWidget });

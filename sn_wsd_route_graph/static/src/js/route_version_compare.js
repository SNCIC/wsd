/** @odoo-module **/
import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { RouteFlowViewer } from "./route_flow_viewer.js";

/**
 * 版本对比 client action: pick two flow versions of a route (including the
 * live "current" one) and view both flow charts side by side, read-only.
 */
export class RouteVersionCompare extends Component {
    static template = "sn_wsd_route_graph.RouteVersionCompare";
    static components = { RouteFlowViewer };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        const ctx = (this.props.action && this.props.action.context) || {};
        this.routeId = ctx.active_id || ctx.default_route_id || null;
        this.routeName = "";
        this.state = useState({
            options: [],
            selA: null,
            selB: null,
            graphA: null,
            graphB: null,
        });
        onMounted(() => this._load());
    }

    async _load() {
        if (!this.routeId) return;
        const versions = await this.orm.searchRead(
            "sn.wsd.process.route.version",
            [["route_id", "=", this.routeId]],
            ["version_no", "confirmed_date", "change_note"],
            { order: "version_no desc" },
        );
        const [route] = await this.orm.read("sn.wsd.process.route", [this.routeId], ["version", "name"]);
        this.routeName = route ? route.name : "";
        const options = versions.map(v => ({
            key: `v${v.id}`,
            versionId: v.id,
            label: `V${v.version_no}`,
            note: v.change_note || "",
        }));
        // Live flow of the route record — always selectable as the newest state.
        options.unshift({ key: "current", versionId: null, label: `当前版 V${route ? route.version : 0}`, note: "" });
        this.state.options = options;
        // Default: newest archived vs current (or the two newest archives).
        this.state.selB = "current";
        this.state.selA = options.length > 1 ? options[1].key : null;
        await this._loadGraphs();
    }

    optionLabel(key) {
        const opt = this.state.options.find(o => o.key === key);
        return opt ? opt.label : "";
    }

    async _loadGraphs() {
        this.state.graphA = null;
        this.state.graphB = null;
        const load = async (key) => {
            if (!key) return null;
            if (key === "current") {
                return this.orm.call("sn.wsd.process.route", "get_route_graph", [this.routeId]);
            }
            const versionId = parseInt(key.slice(1), 10);
            return this.orm.call("sn.wsd.process.route.version", "read_flow_graph", [versionId]);
        };
        const [a, b] = await Promise.all([load(this.state.selA), load(this.state.selB)]);
        this.state.graphA = a;
        this.state.graphB = b;
    }

    async onChangeA(ev) {
        this.state.selA = ev.target.value;
        await this._loadGraphs();
    }

    async onChangeB(ev) {
        this.state.selB = ev.target.value;
        await this._loadGraphs();
    }

    onClickBack() {
        if (this.actionService) this.actionService.restore();
    }
}

registry.category("actions").add("route_version_compare", RouteVersionCompare);

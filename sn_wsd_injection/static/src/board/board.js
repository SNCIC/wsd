/** @odoo-module */
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class SnInjBoard extends Component {
    static template = "sn_wsd_injection.InjBoard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null });
        onWillStart(() => this.load());
        onMounted(() => {
            this.timer = setInterval(() => this.load(), 60000);
        });
        onWillUnmount(() => clearInterval(this.timer));
    }
    async load() {
        this.state.data = await this.orm.call("sn.inj.board.service", "get_board_data", []);
    }
    get d() {
        return this.state.data || { machines: [], summary: {}, states: [], defects: [], alerts: [] };
    }
    stateClass(m) {
        return "o_inj_st_" + m.state;
    }
    devClass(m) {
        const v = Math.abs(m.cycle_dev);
        return v >= 5 ? "o_inj_bad" : v >= 2 ? "o_inj_warn" : "o_inj_good";
    }
    oeeClass(v) {
        return v >= 75 ? "o_inj_good" : v >= 60 ? "o_inj_warn" : "o_inj_bad";
    }
    defectWidth(q) {
        const max = Math.max(...this.d.defects.map((x) => x.qty), 1);
        return `width:${Math.round((q / max) * 100)}%`;
    }
    dur(mins) {
        if (!mins) { return ""; }
        if (mins < 120) { return `${mins}′`; }
        if (mins < 2880) { return `${Math.round(mins / 60)}h`; }
        return `${Math.round(mins / 1440)}天`;
    }
    spark(m) {
        const v = m.spark || [];
        if (v.length < 2) { return { line: "", std: 0, dots: [] }; }
        const lo = Math.min(...v, m.std_cycle) * 0.985, hi = Math.max(...v, m.std_cycle) * 1.015;
        const W = 260, H = 38;
        const y = (x) => (H - ((x - lo) / (hi - lo || 1)) * H).toFixed(1);
        const pts = v.map((x, i) => `${((i / (v.length - 1)) * W).toFixed(1)},${y(x)}`);
        const dots = v.map((x, i) => ({ x: ((i / (v.length - 1)) * W).toFixed(1), y: y(x), out: (m.spark_out || [])[i] }))
            .filter((d) => d.out);
        return { line: pts.join(" "), std: y(m.std_cycle), dots };
    }
    fmt(n) {
        return (n || 0).toLocaleString("zh-CN");
    }
    openMachine(m) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "sn.inj.machine", res_id: m.id, views: [[false, "form"]] });
    }
}
registry.category("actions").add("sn_inj_board", SnInjBoard);

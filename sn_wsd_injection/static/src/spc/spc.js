/** @odoo-module */
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class SnInjSpc extends Component {
    static template = "sn_wsd_injection.InjSpc";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.xRef = useRef("xchart");
        this.rRef = useRef("rchart");
        this.state = useState({ options: { machines: [], params: [] }, machine: null, param: "cycle_time", n: 5, data: null });
        this.charts = [];
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            this.state.options = await this.orm.call("sn.inj.shot", "spc_options", []);
            const ctx = this.props.action?.context || {};
            this.state.machine = ctx.default_machine_id || this.state.options.machines[0]?.id;
            if (ctx.default_param) { this.state.param = ctx.default_param; }
            await this.fetch();
        });
        onMounted(() => this.render());
        onWillUnmount(() => this.destroy());
    }
    async fetch() {
        this.state.data = await this.orm.call("sn.inj.shot", "spc_data", [this.state.machine, this.state.param, this.state.n]);
    }
    async onChange(ev, key) {
        this.state[key] = key === "param" ? ev.target.value : parseInt(ev.target.value);
        await this.fetch();
        this.render();
    }
    destroy() {
        this.charts.forEach((c) => c.destroy());
        this.charts = [];
    }
    flat(v, n) {
        return Array(n).fill(v);
    }
    render() {
        this.destroy();
        const d = this.state.data;
        if (!d || !d.means || !d.means.length) { return; }
        const n = d.means.length;
        const pointColors = d.means.map((m, i) => (d.ooc || []).includes(i) ? "#e5484d" : "#1f6feb");
        const xs = [
            { label: "子组均值 X̄", data: d.means, borderColor: "#1f6feb", backgroundColor: pointColors, pointBackgroundColor: pointColors, pointRadius: 3, borderWidth: 2, tension: 0 },
            { label: "CL", data: this.flat(d.cl, n), borderColor: "#2da44e", borderWidth: 1.5, pointRadius: 0 },
            { label: "UCL", data: this.flat(d.ucl, n), borderColor: "#e5484d", borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 },
            { label: "LCL", data: this.flat(d.lcl, n), borderColor: "#e5484d", borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 },
        ];
        if (d.usl !== null && d.usl !== undefined) {
            xs.push({ label: "USL 工艺上限", data: this.flat(d.usl, n), borderColor: "#f59e0b", borderWidth: 1.5, pointRadius: 0 });
            xs.push({ label: "LSL 工艺下限", data: this.flat(d.lsl, n), borderColor: "#f59e0b", borderWidth: 1.5, pointRadius: 0 });
        }
        const opts = (title) => ({
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { position: "right", labels: { boxWidth: 14, font: { size: 11 } } }, title: { display: true, text: title, font: { size: 13 } } },
            scales: { x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 9, font: { size: 10 } } } },
        });
        this.charts.push(new window.Chart(this.xRef.el, { type: "line", data: { labels: d.labels, datasets: xs }, options: opts(`X̄ 控制图 — ${d.param}（${d.unit}）`) }));
        this.charts.push(new window.Chart(this.rRef.el, {
            type: "line",
            data: { labels: d.labels, datasets: [
                { label: "极差 R", data: d.ranges, borderColor: "#6e40c9", pointRadius: 2, borderWidth: 2, tension: 0 },
                { label: "R̄", data: this.flat(d.rbar, n), borderColor: "#2da44e", borderWidth: 1.5, pointRadius: 0 },
                { label: "UCL_R", data: this.flat(d.r_ucl, n), borderColor: "#e5484d", borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0 },
            ] },
            options: opts("R 控制图（子组极差）"),
        }));
    }
    capClass(v) {
        if (v === undefined || v === null) { return ""; }
        return v >= 1.33 ? "text-success" : v >= 1.0 ? "text-warning" : "text-danger";
    }
}
registry.category("actions").add("sn_inj_spc", SnInjSpc);

/** @odoo-module */
import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const COLORS = ["#1f6feb", "#2da44e", "#f59e0b", "#e5484d", "#6e40c9", "#0ea5e9"];
const POINTS = ["circle", "rect", "triangle", "rectRot", "star", "crossRot"];

export class SnOutKpiBoard extends Component {
    static template = "sn_wsd_outsource.KpiBoard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.barRef = useRef("bar");
        this.lineRef = useRef("line");
        this.exRef = useRef("excess");
        this.state = useState({ data: null });
        this.charts = [];
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            this.state.data = await this.orm.call("sn.out.kpi.board", "board_data", []);
        });
        onMounted(() => this.renderCharts());
        onWillUnmount(() => this.charts.forEach((c) => c.destroy()));
    }
    ratingClass(r) {
        return { A: "text-bg-success", B: "text-bg-info", C: "text-bg-warning", D: "text-bg-danger" }[r] || "text-bg-secondary";
    }
    stateClass(s) {
        return { qualified: "text-bg-success", trial: "text-bg-warning", suspended: "text-bg-danger" }[s] || "text-bg-secondary";
    }
    fmt(v, d = 1) {
        return v === null || v === undefined ? "—" : Number(v).toFixed(d);
    }
    openFactory(id) {
        this.action.doAction({ type: "ir.actions.act_window", res_model: "sn.out.factory", res_id: id, views: [[false, "form"]] });
    }
    renderCharts() {
        const d = this.state.data;
        if (!d) { return; }
        const names = d.rows.map((r) => r.name);
        const base = (title) => ({
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { position: "top", labels: { boxWidth: 14, font: { size: 12 } } },
                       title: { display: true, text: title, font: { size: 14 } } },
        });
        this.charts.push(new window.Chart(this.barRef.el, {
            type: "bar",
            data: { labels: names, datasets: [
                { label: "准交率(%)", data: d.rows.map((r) => r.ontime_rate), backgroundColor: "#1f6feb" },
                { label: "批次合格率(%)", data: d.rows.map((r) => r.pass_rate), backgroundColor: "#2da44e" },
                { label: "最新综合得分", data: d.rows.map((r) => r.score), backgroundColor: "#f59e0b" },
            ] },
            options: { ...base("累计准交率 / 批次合格率 / 最新综合得分"), scales: { y: { min: 0, max: 100 } } },
        }));
        this.charts.push(new window.Chart(this.lineRef.el, {
            type: "line",
            data: { labels: d.periods, datasets: d.trend.map((t, i) => ({
                label: t.name, data: t.scores, borderColor: COLORS[i % COLORS.length], backgroundColor: COLORS[i % COLORS.length],
                spanGaps: true, borderWidth: 2.5, pointRadius: 8 - i, pointStyle: POINTS[i % POINTS.length], tension: 0 })) },
            options: { ...base("月度综合得分趋势（A≥90 / B≥80 / C≥70 / D<70）"), scales: { y: { min: 30, max: 100 } } },
        }));
        this.charts.push(new window.Chart(this.exRef.el, {
            type: "bar",
            data: { labels: names, datasets: [
                { label: "超耗率(%)", data: d.rows.map((r) => r.excess_rate), backgroundColor: "#e5484d", yAxisID: "y" },
                { label: "超耗扣款(元)", data: d.rows.map((r) => r.deduct), backgroundColor: "#6e40c9", yAxisID: "y1" },
            ] },
            options: { ...base("来料加工超耗率与扣款"), scales: { y: { position: "left", min: 0 }, y1: { position: "right", min: 0, grid: { drawOnChartArea: false } } } },
        }));
    }
}
registry.category("actions").add("sn_out_kpi_board", SnOutKpiBoard);

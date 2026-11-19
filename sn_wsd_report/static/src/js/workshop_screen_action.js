/** @odoo-module */

import { Component, onMounted, onWillDestroy, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_INTERVAL_SEC = 60;
const BODY_FULLSCREEN_CLASS = "o_sn_wsd_workshop_screen_fullscreen";
// 复用 MES 大屏的样式作用域，保证两屏视觉完全一致
const BODY_MES_CLASS = "o_sn_wsd_mes_big_screen_fullscreen";
const CHART_COLORS = {
    blue: "#00e5ff",
    green: "#4d9fff",
    amber: "#ffb020",
    red: "#ff4d6d",
    cyan: "#00e5ff",
};
// TOP5 不良饼图配色：以红橙为主，青蓝作次要色
const DEFECT_PALETTE = ["#ff4d6d", "#ff7a45", "#ffb020", "#b46bff", "#4d9fff"];

export class SnWsdWorkshopScreenAction extends Component {
    static template = "sn_wsd_report.WorkshopScreenAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.trendCanvasRef = useRef("trendCanvas");
        this.rateCanvasRef = useRef("rateCanvas");
        this.defectCanvasRef = useRef("defectCanvas");
        this.qualityCanvasRef = useRef("qualityCanvas");
        this.state = useState({
            loading: true,
            data: null,
            workshopId: null,
            autoRefresh: false,
            countdown: REFRESH_INTERVAL_SEC,
            refreshing: false,
        });
        this._refreshTimer = null;
        this._countdownTimer = null;
        this._charts = { trend: null, rate: null, defect: null, quality: null };
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            this.configureChartDefaults();
            await this.loadData();
        });
        onMounted(() => {
            document.body.classList.add(BODY_FULLSCREEN_CLASS);
            document.body.classList.add(BODY_MES_CLASS);
            this.requestBrowserFullscreen();
            this.renderCharts();
        });
        onWillDestroy(() => {
            document.body.classList.remove(BODY_FULLSCREEN_CLASS);
            document.body.classList.remove(BODY_MES_CLASS);
            this.stopAutoRefresh();
            this.destroyChart();
        });
    }

    get summary() {
        return this.state.data?.summary || {};
    }

    get workshop() {
        return this.state.data?.workshop || {};
    }

    get workshops() {
        return this.state.data?.workshops || [];
    }

    get stations() {
        return this.state.data?.station_flow || [];
    }

    get orders() {
        return this.state.data?.orders || [];
    }

    get rankRows() {
        return this.state.data?.rank || [];
    }

    get traces() {
        return (this.state.data?.traces || []).slice(0, 9);
    }

    get alerts() {
        return this.state.data?.alerts || [];
    }

    get salesProgress() {
        return this.state.data?.sales_progress || [];
    }

    get check() {
        return this.state.data?.check_summary || {
            total: 0,
            completed: 0,
            pending: 0,
            overdue: 0,
            failed: 0,
            rate: 0,
            today_total: 0,
            today_completed: 0,
            equipment_count: 0,
        };
    }

    get defectTop() {
        return this.state.data?.defect_top || [];
    }

    get defectTotal() {
        return this.defectTop.reduce((total, item) => total + (item.qty || 0), 0);
    }

    get checkEquipment() {
        return this.state.data?.check_equipment || [];
    }

    get qualityDaily() {
        return this.state.data?.quality_daily || [];
    }

    get trendPassRate() {
        const items = this.state.data?.trend || [];
        let ok = 0;
        let total = 0;
        items.forEach((item) => {
            ok += item.ok || 0;
            total += (item.ok || 0) + (item.ng || 0);
        });
        return total ? (ok / total) * 100 : 0;
    }

    get trendTotal() {
        return (this.state.data?.trend || []).reduce(
            (sum, item) => sum + (item.ok || 0) + (item.ng || 0), 0);
    }

    get quality() {
        return this.state.data?.quality_summary || {
            inspections: 0,
            sample_qty: 0,
            defect_qty: 0,
            pass_rate: 0,
            types: [],
        };
    }

    get wipCounters() {
        return this.stations
            .filter((item) => item.wip > 0)
            .sort((a, b) => b.wip - a.wip)
            .slice(0, 4);
    }

    get outputCounters() {
        return [...this.stations]
            .sort((a, b) => b.ok - a.ok)
            .filter((item) => item.ok > 0)
            .slice(0, 4);
    }

    get passRate() {
        const summary = this.summary;
        const total = summary.day_total || 0;
        if (!total) {
            return 0;
        }
        return Math.round(((summary.day_output || 0) / total) * 100);
    }

    get completedDigits() {
        const value = Math.round(this.summary.day_output || 0);
        return String(value).padStart(6, "0").split("");
    }

    get gaugeStyle() {
        const rate = Math.max(0, Math.min(this.passRate || 0, 100));
        return `--o-gauge-rate: ${rate};`;
    }

    get multiWorkshop() {
        return this.workshops.length > 1;
    }

    async loadData() {
        this.state.refreshing = true;
        try {
            this.state.data = await this.orm.call(
                "sn.wsd.workshop.screen.service",
                "get_screen_data",
                [this.state.workshopId || false]
            );
            this.state.workshopId = this.workshop.id || null;
            this.state.countdown = REFRESH_INTERVAL_SEC;
            this.renderCharts();
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    async onWorkshopChange(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.workshopId = Number.isNaN(value) ? null : value;
        await this.loadData();
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        if (!this.state.autoRefresh) {
            return;
        }
        this._countdownTimer = setInterval(() => {
            this.state.countdown =
                this.state.countdown > 0 ? this.state.countdown - 1 : REFRESH_INTERVAL_SEC;
        }, 1000);
        this._refreshTimer = setInterval(async () => {
            await this.loadData();
        }, REFRESH_INTERVAL_SEC * 1000);
    }

    stopAutoRefresh() {
        if (this._refreshTimer) {
            clearInterval(this._refreshTimer);
            this._refreshTimer = null;
        }
        if (this._countdownTimer) {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        }
    }

    toggleAutoRefresh() {
        this.state.autoRefresh = !this.state.autoRefresh;
        this.state.countdown = REFRESH_INTERVAL_SEC;
        this.startAutoRefresh();
    }

    async manualRefresh() {
        await this.loadData();
        if (this.state.autoRefresh) {
            this.startAutoRefresh();
        }
    }

    requestBrowserFullscreen() {
        const element = document.documentElement;
        if (!element || document.fullscreenElement || !element.requestFullscreen) {
            return;
        }
        element.requestFullscreen().catch(() => {});
    }

    destroyChart() {
        Object.keys(this._charts).forEach((key) => {
            const chart = this._charts[key];
            if (chart) {
                chart.destroy();
                this._charts[key] = null;
            }
        });
    }

    configureChartDefaults() {
        Chart.defaults.color = "#9defff";
        Chart.defaults.borderColor = "rgba(0, 174, 255, 0.14)";
        Chart.defaults.font.family =
            "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    }

    renderCharts() {
        this.renderRateChart();
        this.renderTrendChart();
        this.renderDefectChart();
        this.renderQualityChart();
    }

    upsertChart(key, canvas, config) {
        if (!canvas) {
            return;
        }
        const chart = this._charts[key];
        if (chart) {
            chart.data = config.data;
            chart.options = config.options;
            chart.update("none");
            return;
        }
        this._charts[key] = new Chart(canvas, config);
    }

    get tooltipStyle() {
        return {
            backgroundColor: "rgba(2, 9, 54, 0.94)",
            titleColor: "#ffffff",
            bodyColor: "#c9f7ff",
            borderColor: "rgba(0, 218, 255, 0.55)",
            borderWidth: 1,
            padding: 10,
        };
    }

    renderRateChart() {
        const items = this.state.data?.trend || [];
        const totals = items.map((item) => (item.ok || 0) + (item.ng || 0));
        const canvas = this.rateCanvasRef.el;
        let fill = "rgba(255, 176, 32, 0.18)";
        if (canvas) {
            const gradient = canvas.getContext("2d").createLinearGradient(0, 0, 0, 140);
            gradient.addColorStop(0, "rgba(255, 176, 32, 0.42)");
            gradient.addColorStop(1, "rgba(255, 176, 32, 0.02)");
            fill = gradient;
        }
        const config = {
            type: "line",
            data: {
                labels: items.map((item) => item.label),
                datasets: [{
                    label: "日产出总量",
                    data: totals,
                    borderColor: "#ffb020",
                    backgroundColor: fill,
                    borderWidth: 1.8,
                    fill: true,
                    tension: 0.35,
                    spanGaps: true,
                    pointRadius: 2.6,
                    pointHoverRadius: 4,
                    pointBackgroundColor: "#021530",
                    pointBorderColor: "#ffb020",
                    pointBorderWidth: 1.4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                layout: { padding: { top: 6, right: 8, bottom: 0, left: 4 } },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        ...this.tooltipStyle,
                        callbacks: {
                            label: (context) => ` 日产出总量：${this.formatNumber(context.parsed.y)} 件`,
                        },
                    },
                },
                scales: {
                    x: {
                        display: true,
                        ticks: { display: false },
                        grid: { display: false },
                        border: { display: false },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            color: "rgba(130, 223, 255, 0.75)",
                            font: { size: 8.5 },
                            maxTicksLimit: 3,
                        },
                        grid: { color: "rgba(0, 174, 255, 0.09)" },
                        border: { display: false },
                    },
                },
            },
        };
        this.upsertChart("rate", canvas, config);
    }

    renderTrendChart() {
        const items = this.state.data?.trend || [];
        const config = {
            type: "bar",
            data: {
                labels: items.map((item) => item.label),
                datasets: [
                    {
                        label: "通过",
                        data: items.map((item) => item.ok),
                        backgroundColor: CHART_COLORS.blue,
                        borderRadius: 3,
                        maxBarThickness: 30,
                    },
                    {
                        label: "不良",
                        data: items.map((item) => item.ng),
                        backgroundColor: CHART_COLORS.red,
                        borderRadius: 3,
                        maxBarThickness: 30,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                layout: { padding: { top: 8, right: 8, bottom: 0, left: 4 } },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            color: "#9defff",
                            boxWidth: 10,
                            boxHeight: 10,
                            usePointStyle: true,
                            font: { size: 10 },
                        },
                    },
                    tooltip: this.tooltipStyle,
                },
                scales: {
                    x: {
                        ticks: { color: "#82dfff", font: { size: 10 } },
                        grid: { color: "rgba(0, 174, 255, 0.10)" },
                        border: { color: "rgba(0, 218, 255, 0.24)" },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { color: "#82dfff", font: { size: 10 } },
                        grid: { color: "rgba(0, 174, 255, 0.10)" },
                        border: { color: "rgba(0, 218, 255, 0.24)" },
                    },
                },
            },
        };
        this.upsertChart("trend", this.trendCanvasRef.el, config);
    }

    renderDefectChart() {
        const items = this.defectTop;
        const config = {
            type: "doughnut",
            data: {
                labels: items.map((item) => item.name),
                datasets: [{
                    data: items.map((item) => item.qty),
                    backgroundColor: items.map(
                        (item, index) => DEFECT_PALETTE[index % DEFECT_PALETTE.length]
                    ),
                    borderColor: "rgba(2, 21, 48, 0.9)",
                    borderWidth: 2,
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                cutout: "52%",
                layout: { padding: { top: 2, right: 2, bottom: 2, left: 2 } },
                plugins: {
                    legend: {
                        position: "right",
                        align: "center",
                        labels: {
                            color: "#c9f7ff",
                            boxWidth: 9,
                            boxHeight: 9,
                            usePointStyle: true,
                            font: { size: 10.5 },
                            padding: 9,
                        },
                    },
                    tooltip: {
                        ...this.tooltipStyle,
                        callbacks: {
                            label: (context) => {
                                const row = items[context.dataIndex] || {};
                                return ` ${context.label}：${context.parsed} 件（${this.formatNumber(row.share, 1)}%）`;
                            },
                        },
                    },
                },
            },
        };
        this.upsertChart("defect", this.defectCanvasRef.el, config);
    }

    renderQualityChart() {
        const items = this.qualityDaily;
        const axisStyle = {
            ticks: { color: "#82dfff", font: { size: 10 } },
            grid: { color: "rgba(0, 174, 255, 0.10)" },
            border: { color: "rgba(0, 218, 255, 0.24)" },
        };
        const config = {
            type: "bar",
            data: {
                labels: items.map((item) => item.label),
                datasets: [
                    {
                        label: "合格件",
                        data: items.map((item) => item.pass_qty),
                        backgroundColor: "rgba(0, 229, 255, 0.85)",
                        borderRadius: 2,
                        maxBarThickness: 14,
                        stack: "qty",
                    },
                    {
                        label: "不良件",
                        data: items.map((item) => item.defect_qty),
                        backgroundColor: CHART_COLORS.red,
                        borderRadius: 2,
                        maxBarThickness: 14,
                        stack: "qty",
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                layout: { padding: { top: 2, right: 8, bottom: 0, left: 0 } },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            color: "#9defff",
                            boxWidth: 10,
                            boxHeight: 10,
                            usePointStyle: true,
                            font: { size: 10 },
                        },
                    },
                    tooltip: {
                        ...this.tooltipStyle,
                        callbacks: {
                            label: (context) => ` ${context.dataset.label}：${context.parsed.x} 件`,
                            footer: (contexts) => {
                                const row = items[contexts[0].dataIndex] || {};
                                return `合格率 ${this.formatNumber(row.pass_rate, 1)}%`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        ...axisStyle,
                        stacked: true,
                        beginAtZero: true,
                        ticks: { color: "#82dfff", font: { size: 9 } },
                    },
                    y: {
                        ...axisStyle,
                        stacked: true,
                        grid: { display: false },
                        ticks: { color: "#82dfff", font: { size: 10 } },
                    },
                },
            },
        };
        this.upsertChart("quality", this.qualityCanvasRef.el, config);
    }

    // ------------------------------------------------------------- helpers
    stationRowClass(status) {
        if (status === "warning") {
            return "o_is_danger";
        }
        if (status === "running") {
            return "o_is_warning";
        }
        if (status === "normal") {
            return "o_is_normal";
        }
        return "o_is_idle";
    }

    stationStatusLabel(status) {
        return {
            running: "在制",
            warning: "异常",
            normal: "已过站",
            idle: "未过站",
        }[status] || "-";
    }

    orderStateClass(state) {
        if (state === "in_progress") {
            return "o_is_running";
        }
        if (state === "done") {
            return "o_is_done";
        }
        return "o_is_pending";
    }

    checkStatusClass(status) {
        // 绿＝完成，红＝未完成（含不合格、逾期），黄＝待执行
        return {
            pass: "o_ws_chk_ok",
            fail: "o_ws_chk_bad",
            overdue: "o_ws_chk_bad",
            pending: "o_ws_chk_wait",
        }[status] || "";
    }

    traceRowClass(status) {
        return status === "danger" ? "o_is_danger" : "o_is_normal";
    }

    formatNumber(value, digits = 0) {
        const number = Number(value || 0);
        return number.toLocaleString(undefined, {
            maximumFractionDigits: digits,
            minimumFractionDigits: 0,
        });
    }

    progressBarStyle(value, baseValue = 0) {
        const base = Number(baseValue || 0);
        const current = Number(value || 0);
        const percent = base ? Math.min(100, Math.max(2, (current / base) * 100)) : Math.min(100, current);
        return `width: ${percent}%;`;
    }
}

registry.category("actions").add(
    "sn_wsd_workshop_screen_action",
    SnWsdWorkshopScreenAction
);

/** @odoo-module */

import { Component, onMounted, onWillDestroy, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_INTERVAL_SEC = 60;
const BODY_FULLSCREEN_CLASS = "o_sn_wsd_mes_big_screen_fullscreen";
const CHART_COLORS = {
    blue: "#168bff",
    green: "#10f5c6",
    amber: "#ffd166",
    red: "#ef4444",
    cyan: "#00d5ff",
    purple: "#7c5cff",
    slate: "#6ea8ff",
};

export class SnWsdMesBigScreenAction extends Component {
    static template = "sn_wsd_report.MesBigScreenAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.progressCanvasRef = useRef("progressCanvas");
        this.yieldCanvasRef = useRef("yieldCanvas");
        this.testCanvasRef = useRef("testCanvas");
        this.agingCanvasRef = useRef("agingCanvas");
        this.efficiencyCanvasRef = useRef("efficiencyCanvas");
        this.congestionCanvasRef = useRef("congestionCanvas");
        this.repairCanvasRef = useRef("repairCanvas");
        this.traceCanvasRef = useRef("traceCanvas");
        this.state = useState({
            loading: true,
            data: null,
            autoRefresh: false,
            countdown: REFRESH_INTERVAL_SEC,
            refreshing: false,
        });
        this._refreshTimer = null;
        this._countdownTimer = null;
        this._charts = {};
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            this.configureChartDefaults();
            await this.loadData();
        });
        onMounted(() => {
            document.body.classList.add(BODY_FULLSCREEN_CLASS);
            this.requestBrowserFullscreen();
            this.renderAllCharts();
        });
        onWillDestroy(() => {
            document.body.classList.remove(BODY_FULLSCREEN_CLASS);
            this.stopAutoRefresh();
            this.destroyCharts();
        });
    }

    get summary() {
        return this.state.data?.summary || {};
    }

    get alertStations() {
        return this.state.data?.station_congestion || [];
    }

    get abnormalTop() {
        return this.state.data?.top_abnormal_stations || [];
    }

    get compactTraces() {
        return (this.state.data?.serial_trace || []).slice(0, 7);
    }

    get progressCards() {
        return (this.state.data?.production_progress || []).slice(0, 4);
    }

    get operationCards() {
        return (this.state.data?.operation_daily || []).slice(0, 4);
    }

    get outputBars() {
        return (this.state.data?.operation_daily || []).slice(0, 7);
    }

    get centerProgressRate() {
        const items = this.state.data?.production_progress || [];
        if (!items.length) {
            return 0;
        }
        const total = items.reduce((sum, item) => sum + (item.progress_rate || 0), 0);
        return Math.round(total / items.length);
    }

    get completedDigits() {
        const value = Math.round(this.summary.today_output_total || 0);
        return String(value).padStart(6, "0").split("");
    }

    get passRate() {
        const output = this.summary.today_output_total || 0;
        if (!output) {
            return 0;
        }
        return Math.round(((this.summary.today_pass_total || 0) / output) * 100);
    }

    get gaugeStyle() {
        const rate = Math.max(0, Math.min(this.centerProgressRate, 100));
        return `--o-gauge-rate: ${rate};`;
    }

    async loadData() {
        this.state.refreshing = true;
        try {
            this.state.data = await this.orm.call("sn.wsd.mes.dashboard.service", "get_big_screen_data", []);
            this.state.countdown = REFRESH_INTERVAL_SEC;
            this.renderAllCharts();
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        if (!this.state.autoRefresh) {
            return;
        }
        this._countdownTimer = setInterval(() => {
            this.state.countdown = this.state.countdown > 0 ? this.state.countdown - 1 : REFRESH_INTERVAL_SEC;
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

    destroyCharts() {
        for (const chart of Object.values(this._charts)) {
            chart.destroy();
        }
        this._charts = {};
    }

    configureChartDefaults() {
        Chart.defaults.color = "#9defff";
        Chart.defaults.borderColor = "rgba(0, 174, 255, 0.14)";
        Chart.defaults.font.family = "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    }

    ensureChart(name, canvas, config) {
        if (!canvas) {
            return;
        }
        if (this._charts[name]) {
            this._charts[name].data = config.data;
            this._charts[name].options = config.options;
            this._charts[name].update("none");
            return;
        }
        this._charts[name] = new Chart(canvas, config);
    }

    renderAllCharts() {
        if (!this.state.data || this.state.loading) {
            return;
        }
        this.renderProgressChart();
        this.renderYieldChart();
        this.renderTestChart();
        this.renderAgingChart();
        this.renderEfficiencyChart();
        this.renderCongestionChart();
        this.renderRepairChart();
        this.renderTraceChart();
    }

    renderProgressChart() {
        const items = this.state.data.production_progress || [];
        this.ensureChart("progress", this.progressCanvasRef.el, {
            type: "bar",
            data: {
                labels: items.map((item) => item.production_name),
                datasets: [
                    {
                        label: "\u7d2f\u8ba1\u51fa\u7ad9",
                        data: items.map((item) => item.qty_output_total),
                        backgroundColor: CHART_COLORS.blue,
                    },
                    {
                        label: "\u826f\u54c1",
                        data: items.map((item) => item.qty_pass),
                        backgroundColor: CHART_COLORS.green,
                    },
                    {
                        type: "line",
                        label: "\u8fdb\u5ea6%",
                        data: items.map((item) => item.progress_rate),
                        borderColor: CHART_COLORS.amber,
                        yAxisID: "y1",
                        tension: 0.25,
                    },
                ],
            },
            options: this.commonCartesianOptions({
                y1: this.percentAxis("right"),
            }),
        });
    }

    renderYieldChart() {
        const items = this.state.data.operation_daily || [];
        this.ensureChart("yield", this.yieldCanvasRef.el, {
            type: "bar",
            data: {
                labels: items.map((item) => item.station_code || "-"),
                datasets: [
                    {
                        label: "\u826f\u54c1",
                        data: items.map((item) => item.qty_ok),
                        backgroundColor: CHART_COLORS.green,
                    },
                    {
                        label: "\u4e0d\u826f",
                        data: items.map((item) => item.qty_ng),
                        backgroundColor: CHART_COLORS.amber,
                    },
                    {
                        label: "\u62a5\u5e9f",
                        data: items.map((item) => item.qty_scrap),
                        backgroundColor: CHART_COLORS.red,
                    },
                ],
            },
            options: this.commonCartesianOptions(),
        });
    }

    renderTestChart() {
        const items = this.state.data.test_pass_rates || [];
        this.ensureChart("test", this.testCanvasRef.el, {
            type: "line",
            data: {
                labels: items.map((item) => `${item.test_type || "-"}-${item.station_code || "-"}`),
                datasets: [
                    {
                        label: "\u901a\u8fc7\u7387%",
                        data: items.map((item) => item.pass_rate),
                        borderColor: CHART_COLORS.cyan,
                        backgroundColor: "rgba(6, 182, 212, 0.10)",
                        fill: true,
                        tension: 0.25,
                        yAxisID: "y",
                    },
                    {
                        label: "\u5931\u8d25\u6570",
                        data: items.map((item) => item.fail_count),
                        borderColor: CHART_COLORS.red,
                        backgroundColor: "rgba(239, 68, 68, 0.08)",
                        tension: 0.2,
                        yAxisID: "y1",
                    },
                ],
            },
            options: this.commonCartesianOptions({
                y: this.percentAxis("left"),
                y1: this.valueAxis("right", false),
            }),
        });
    }

    renderAgingChart() {
        const items = this.state.data.aging_losses || [];
        this.ensureChart("aging", this.agingCanvasRef.el, {
            type: "bar",
            data: {
                labels: items.map((item) => item.batch_name || "-"),
                datasets: [
                    {
                        label: "\u88c5\u8f7d\u6570",
                        data: items.map((item) => item.load_qty),
                        backgroundColor: CHART_COLORS.blue,
                    },
                    {
                        label: "\u635f\u5931\u6570",
                        data: items.map((item) => item.loss_qty),
                        backgroundColor: CHART_COLORS.red,
                    },
                    {
                        type: "line",
                        label: "\u635f\u5931\u7387%",
                        data: items.map((item) => item.loss_rate),
                        borderColor: CHART_COLORS.amber,
                        yAxisID: "y1",
                        tension: 0.25,
                    },
                ],
            },
            options: this.commonCartesianOptions({
                y1: this.percentAxis("right"),
            }),
        });
    }

    renderEfficiencyChart() {
        const items = this.state.data.station_efficiency || [];
        this.ensureChart("efficiency", this.efficiencyCanvasRef.el, {
            type: "line",
            data: {
                labels: items.map((item) => item.station_code || "-"),
                datasets: [
                    {
                        label: "\u6548\u7387%",
                        data: items.map((item) => item.efficiency_rate),
                        borderColor: CHART_COLORS.purple,
                        backgroundColor: "rgba(139, 92, 246, 0.08)",
                        fill: true,
                        tension: 0.25,
                        yAxisID: "y",
                    },
                    {
                        label: "\u5e73\u5747\u8282\u62cd(s)",
                        data: items.map((item) => item.avg_cycle_time_sec),
                        borderColor: CHART_COLORS.slate,
                        tension: 0.2,
                        yAxisID: "y1",
                    },
                ],
            },
            options: this.commonCartesianOptions({
                y: this.percentAxis("left"),
                y1: this.valueAxis("right", false),
            }),
        });
    }

    renderCongestionChart() {
        const items = this.state.data.station_congestion || [];
        this.ensureChart("congestion", this.congestionCanvasRef.el, {
            type: "bar",
            data: {
                labels: items.map((item) => item.station_code || "-"),
                datasets: [
                    {
                        label: "\u79ef\u538b\u6570",
                        data: items.map((item) => item.backlog_qty),
                        backgroundColor: items.map((item) =>
                            item.alert_level === "danger"
                                ? CHART_COLORS.red
                                : item.alert_level === "warning"
                                  ? CHART_COLORS.amber
                                  : CHART_COLORS.green
                        ),
                    },
                    {
                        type: "line",
                        label: "\u6548\u7387%",
                        data: items.map((item) => item.efficiency_rate),
                        borderColor: CHART_COLORS.cyan,
                        yAxisID: "y1",
                        tension: 0.25,
                    },
                ],
            },
            options: this.commonCartesianOptions({
                y1: this.percentAxis("right"),
            }),
        });
    }

    renderRepairChart() {
        const items = this.state.data.repair_closures || [];
        this.ensureChart("repair", this.repairCanvasRef.el, {
            type: "bar",
            data: {
                labels: items.map((item) => `${item.report_date || ""}-${item.repair_mode || ""}`),
                datasets: [
                    {
                        label: "\u62a5\u4fee",
                        data: items.map((item) => item.reported_count),
                        backgroundColor: CHART_COLORS.blue,
                    },
                    {
                        label: "\u95ed\u73af",
                        data: items.map((item) => item.closed_ok_count),
                        backgroundColor: CHART_COLORS.green,
                    },
                    {
                        label: "\u672a\u95ed\u73af",
                        data: items.map((item) => item.open_count),
                        backgroundColor: CHART_COLORS.red,
                    },
                ],
            },
            options: this.commonCartesianOptions(),
        });
    }

    renderTraceChart() {
        const items = this.state.data.test_history || [];
        this.ensureChart("trace", this.traceCanvasRef.el, {
            type: "bar",
            data: {
                labels: items.map((item) => item.serial_no || "-"),
                datasets: [
                    {
                        label: "\u6d4b\u8bd5\u8282\u62cd(s)",
                        data: items.map((item) => item.cycle_time_sec || 0),
                        backgroundColor: items.map((item) =>
                            item.result === "fail"
                                ? CHART_COLORS.red
                                : item.result === "hold"
                                  ? CHART_COLORS.amber
                                  : CHART_COLORS.blue
                        ),
                    },
                ],
            },
            options: this.commonCartesianOptions(),
        });
    }

    commonCartesianOptions(extraScales = {}) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            layout: {
                padding: {
                    top: 8,
                    right: 8,
                    bottom: 0,
                    left: 4,
                },
            },
            interaction: {
                mode: "index",
                intersect: false,
            },
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        color: "#9defff",
                        boxWidth: 10,
                        boxHeight: 10,
                        usePointStyle: true,
                        font: {
                            size: 10,
                        },
                    },
                },
                tooltip: {
                    enabled: true,
                    backgroundColor: "rgba(2, 9, 54, 0.94)",
                    titleColor: "#ffffff",
                    bodyColor: "#c9f7ff",
                    borderColor: "rgba(0, 218, 255, 0.55)",
                    borderWidth: 1,
                    displayColors: true,
                    padding: 10,
                    callbacks: {
                        label: (context) => {
                            const label = context.dataset.label || "";
                            const value = Number(context.parsed.y ?? context.parsed.x ?? 0);
                            return `${label}: ${this.formatNumber(value, 2)}`;
                        },
                    },
                },
            },
            onHover: (event, items) => {
                event.native.target.style.cursor = items.length ? "pointer" : "";
            },
            scales: {
                x: {
                    ticks: {
                        color: "#82dfff",
                        maxRotation: 0,
                        minRotation: 0,
                        autoSkip: true,
                        font: {
                            size: 9,
                        },
                    },
                    grid: {
                        color: "rgba(0, 174, 255, 0.10)",
                    },
                    border: {
                        color: "rgba(0, 218, 255, 0.24)",
                    },
                },
                y: this.valueAxis("left"),
                ...extraScales,
            },
        };
    }

    percentAxis(position) {
        return {
            position,
            beginAtZero: true,
            max: 100,
            ticks: {
                color: "#82dfff",
                font: {
                    size: 9,
                },
            },
            grid: {
                drawOnChartArea: position === "left",
                color: "rgba(0, 174, 255, 0.10)",
            },
            border: {
                color: "rgba(0, 218, 255, 0.24)",
            },
        };
    }

    valueAxis(position, drawOnChartArea = true) {
        return {
            position,
            beginAtZero: true,
            ticks: {
                color: "#82dfff",
                font: {
                    size: 9,
                },
            },
            grid: {
                drawOnChartArea,
                color: "rgba(0, 174, 255, 0.10)",
            },
            border: {
                color: "rgba(0, 218, 255, 0.24)",
            },
        };
    }

    metricTileClass(value, warningThreshold = null, dangerThreshold = null) {
        if (dangerThreshold !== null && value >= dangerThreshold) {
            return "o_status_danger";
        }
        if (warningThreshold !== null && value >= warningThreshold) {
            return "o_status_warning";
        }
        return "o_status_normal";
    }

    stationRowClass(level) {
        if (level === "danger") {
            return "o_is_danger";
        }
        if (level === "warning") {
            return "o_is_warning";
        }
        return "o_is_normal";
    }

    traceRowClass(status) {
        if (status === "danger") {
            return "o_is_danger";
        }
        if (status === "warning") {
            return "o_is_warning";
        }
        return "o_is_normal";
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
        const percent = base ? Math.min(100, Math.max(4, (current / base) * 100)) : Math.min(100, current);
        return `width: ${percent}%;`;
    }
}

registry.category("actions").add("sn_wsd_mes_big_screen_action", SnWsdMesBigScreenAction);


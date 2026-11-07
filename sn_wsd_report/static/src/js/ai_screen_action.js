/** @odoo-module */

import { Component, onMounted, onWillDestroy, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_INTERVAL_SEC = 60;
const BODY_FULLSCREEN_CLASS = "o_sn_wsd_ai_screen_fullscreen";
const STAGE_W = 1920;
const STAGE_H = 1080;
const DIMENSIONS = [
    { key: "workorder", label: "工单维度" },
    { key: "team", label: "班组维度" },
    { key: "equipment", label: "设备维度" },
];
const COLORS = {
    cyan: "#00e5ff",
    blue: "#4d9fff",
    purple: "#7c5cff",
    amber: "#ffb020",
    red: "#ff4d6d",
    green: "#00e5a0",
    gridLine: "rgba(0, 200, 255, 0.10)",
    tick: "#7fb8d9",
};

export class SnWsdAiScreenAction extends Component {
    static template = "sn_wsd_report.AiScreenAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.trendCanvasRef = useRef("trendCanvas");
        this.capacityCanvasRef = useRef("capacityCanvas");
        this.qualityCanvasRef = useRef("qualityCanvas");
        this.dimensions = DIMENSIONS;
        this.state = useState({
            loading: true,
            data: null,
            dimension: "workorder",
            scale: 1,
            autoRefresh: false,
            countdown: REFRESH_INTERVAL_SEC,
            refreshing: false,
            kpiValues: [],
        });
        this._refreshTimer = null;
        this._countdownTimer = null;
        this._resizeHandler = null;
        this._charts = {};
        this._animFrames = [];
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            Chart.defaults.color = COLORS.tick;
            Chart.defaults.borderColor = COLORS.gridLine;
            Chart.defaults.font.family =
                "Inter, system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif";
            await this.loadData();
        });
        onMounted(() => {
            document.body.classList.add(BODY_FULLSCREEN_CLASS);
            this._fitScale();
            this._resizeHandler = () => this._fitScale();
            window.addEventListener("resize", this._resizeHandler);
            this.renderAllCharts();
        });
        onWillDestroy(() => {
            document.body.classList.remove(BODY_FULLSCREEN_CLASS);
            this.stopAutoRefresh();
            this._resizeHandler && window.removeEventListener("resize", this._resizeHandler);
            this._animFrames.forEach((id) => cancelAnimationFrame(id));
            this.destroyCharts();
        });
    }

    get summary() {
        return this.state.data?.summary || {};
    }

    get kpiCards() {
        return this.state.data?.kpi || [];
    }

    get dimensionLabel() {
        return this.state.data?.dimension_label || "工单";
    }

    get comparison() {
        return this.state.data?.comparison || { labels: [], planned: [], actual: [] };
    }

    get detail() {
        return this.state.data?.detail || { columns: [], rows: [] };
    }

    get worktimeDist() {
        return this.state.data?.worktime_dist || { labels: [], values: [] };
    }

    get hourlyTrend() {
        return this.state.data?.hourly_trend || { labels: [], output: [], pass_rate: [] };
    }

    get liveActivities() {
        return this.state.data?.live_activities || [];
    }

    get achieveRate() {
        return this.summary.achieve_rate || 0;
    }

    get stageStyle() {
        return `transform: translate(-50%, -50%) scale(${this.state.scale});`;
    }

    get coreGaugeStyle() {
        return `--o-achieve: ${this.achieveRate};`;
    }

    get coreDigits() {
        const value = Math.round(this.summary.today_output || 0);
        return String(value).padStart(6, "0").split("");
    }

    isDimension(key) {
        return this.state.dimension === key;
    }

    async switchDimension(key) {
        if (this.state.dimension === key) {
            return;
        }
        this.state.dimension = key;
        await this.loadData();
    }

    _fitScale() {
        const sx = window.innerWidth / STAGE_W;
        const sy = window.innerHeight / STAGE_H;
        this.state.scale = Math.min(sx, sy);
    }

    async loadData() {
        this.state.refreshing = true;
        try {
            const data = await this.orm.call(
                "sn.wsd.ai.dashboard.service",
                "get_ai_screen_data",
                [this.state.dimension]
            );
            this.state.data = data;
            this.state.countdown = REFRESH_INTERVAL_SEC;
            this._animateKpisTo(data.kpi || []);
            this.renderAllCharts();
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    _animateKpisTo(cards) {
        const targets = cards.map((c) => Number(c.value || 0));
        if (!this.state.kpiValues.length) {
            this.state.kpiValues = targets.map(() => 0);
        } else if (this.state.kpiValues.length !== targets.length) {
            this.state.kpiValues = targets.map((_, i) => this.state.kpiValues[i] || 0);
        }
        const duration = 900;
        const startTime = performance.now();
        const startValues = [...this.state.kpiValues];
        const step = (now) => {
            const t = Math.min((now - startTime) / duration, 1);
            const eased = 1 - Math.pow(1 - t, 3);
            for (let i = 0; i < targets.length; i++) {
                this.state.kpiValues[i] = startValues[i] + (targets[i] - startValues[i]) * eased;
            }
            if (t < 1) {
                this._animFrames.push(requestAnimationFrame(step));
            } else {
                this.state.kpiValues = [...targets];
            }
        };
        this._animFrames.push(requestAnimationFrame(step));
    }

    formatCardValue(card, index) {
        const value = this.state.kpiValues[index] ?? card.value ?? 0;
        return this.formatNumber(value, card.digits || 0) + (card.suffix || "");
    }

    formatNumber(value, digits = 0) {
        return Number(value || 0).toLocaleString(undefined, {
            maximumFractionDigits: digits,
            minimumFractionDigits: 0,
        });
    }

    detailRowClass(level) {
        return `o_row_${level || "normal"}`;
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

    _ensureChart(name, canvas, config) {
        if (!canvas) {
            return;
        }
        if (this._charts[name]) {
            this._charts[name].data = config.data;
            if (config.options) {
                this._charts[name].options = config.options;
            }
            this._charts[name].update();
            return;
        }
        this._charts[name] = new Chart(canvas, config);
    }

    destroyCharts() {
        Object.values(this._charts).forEach((c) => c.destroy());
        this._charts = {};
    }

    _baseChartOptions(y1 = null) {
        const scales = {
            x: {
                ticks: { color: COLORS.tick, font: { size: 10 }, maxRotation: 0 },
                grid: { color: COLORS.gridLine },
            },
            y: {
                beginAtZero: true,
                ticks: { color: COLORS.tick, font: { size: 10 } },
                grid: { color: COLORS.gridLine },
            },
        };
        if (y1) {
            scales.y1 = y1;
        }
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 800, easing: "easeOutQuart" },
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        color: COLORS.tick,
                        boxWidth: 10,
                        boxHeight: 10,
                        usePointStyle: true,
                        font: { size: 11 },
                    },
                },
                tooltip: {
                    backgroundColor: "rgba(2, 9, 54, 0.94)",
                    borderColor: "rgba(0, 200, 255, 0.55)",
                    borderWidth: 1,
                },
            },
            scales,
        };
    }

    renderAllCharts() {
        if (!this.state.data) {
            return;
        }
        this.renderTrendChart();
        this.renderCapacityChart();
        this.renderQualityChart();
    }

    renderTrendChart() {
        const t = this.hourlyTrend;
        this._ensureChart("trend", this.trendCanvasRef.el, {
            type: "bar",
            data: {
                labels: t.labels,
                datasets: [
                    {
                        type: "bar",
                        label: "产量",
                        data: t.output,
                        backgroundColor: COLORS.cyan,
                        borderRadius: 3,
                        maxBarThickness: 24,
                    },
                    {
                        type: "line",
                        label: "良率%",
                        data: t.pass_rate,
                        borderColor: COLORS.amber,
                        backgroundColor: COLORS.amber,
                        yAxisID: "y1",
                        tension: 0.35,
                        pointRadius: 3,
                        pointBackgroundColor: "#ffffff",
                        pointBorderColor: COLORS.amber,
                        pointBorderWidth: 1.5,
                    },
                ],
            },
            options: this._baseChartOptions({
                position: "right",
                beginAtZero: true,
                max: 100,
                ticks: { color: COLORS.tick, font: { size: 10 } },
                grid: { drawOnChartArea: false },
            }),
        });
    }

    renderCapacityChart() {
        const c = this.comparison;
        this._ensureChart("capacity", this.capacityCanvasRef.el, {
            type: "bar",
            data: {
                labels: c.labels,
                datasets: [
                    {
                        label: "计划",
                        data: c.planned,
                        backgroundColor: COLORS.blue,
                        borderRadius: 3,
                        maxBarThickness: 22,
                    },
                    {
                        label: "实际",
                        data: c.actual,
                        backgroundColor: COLORS.cyan,
                        borderRadius: 3,
                        maxBarThickness: 22,
                    },
                ],
            },
            options: this._baseChartOptions(),
        });
    }

    renderQualityChart() {
        const q = this.worktimeDist;
        const total = q.values.reduce((a, b) => a + b, 0) || 1;
        this._ensureChart("quality", this.qualityCanvasRef.el, {
            type: "doughnut",
            data: {
                labels: q.labels,
                datasets: [
                    {
                        data: q.values,
                        backgroundColor: [COLORS.cyan, COLORS.blue, COLORS.green, COLORS.purple, COLORS.amber, COLORS.red],
                        borderColor: "rgba(2, 10, 26, 0.9)",
                        borderWidth: 2,
                        hoverOffset: 8,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                animation: { duration: 900, easing: "easeOutQuart" },
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            color: COLORS.tick,
                            boxWidth: 10,
                            boxHeight: 10,
                            usePointStyle: true,
                            font: { size: 11 },
                        },
                    },
                    tooltip: {
                        backgroundColor: "rgba(2, 9, 54, 0.94)",
                        borderColor: "rgba(0, 200, 255, 0.55)",
                        borderWidth: 1,
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.parsed;
                                const p = ((v / total) * 100).toFixed(1);
                                return ` ${ctx.label}: ${v} h (${p}%)`;
                            },
                        },
                    },
                },
            },
        });
    }
}

registry.category("actions").add("sn_wsd_ai_screen_action", SnWsdAiScreenAction);

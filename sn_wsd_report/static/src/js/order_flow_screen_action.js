/** @odoo-module */

import { Component, onMounted, onWillDestroy, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_INTERVAL_SEC = 60;
const BODY_FULLSCREEN_CLASS = "o_sn_wsd_order_flow_fullscreen";

export class SnWsdOrderFlowScreenAction extends Component {
    static template = "sn_wsd_report.OrderFlowScreenAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.gaugeCanvasRef = useRef("gaugeCanvas");
        this.stationCanvasRef = useRef("stationCanvas");
        this.state = useState({
            loading: true,
            data: null,
            autoRefresh: false,
            countdown: REFRESH_INTERVAL_SEC,
            refreshing: false,
            currentOrderId: null,
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

    get orderInfo() {
        return this.state.data?.order_info || {};
    }

    get nodes() {
        return this.state.data?.nodes || [];
    }

    get stations() {
        return this.state.data?.stations || [];
    }

    get tests() {
        return this.state.data?.tests || [];
    }

    get traces() {
        return this.state.data?.traces || [];
    }

    get orderOptions() {
        return this.state.data?.order_options || [];
    }

    get currentTime() {
        return (this.summary.refresh_time || "").slice(11);
    }

    // 时间轴节点之间的连接线状态：前一个 done 则线亮
    lineDone(index) {
        const nodes = this.nodes;
        return index > 0 && nodes[index - 1]?.status === "done";
    }

    nodeClass(status) {
        return "o_node_" + (status || "pending");
    }

    stationStatusClass(status) {
        return "o_st_" + (status || "pending");
    }

    rowClass(status) {
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

    progressWidth(value, base) {
        const b = Number(base || 0);
        const v = Number(value || 0);
        if (!b) return v > 0 ? "100%" : "0%";
        return Math.min(100, (v / b) * 100) + "%";
    }

    async loadData(orderId = null) {
        this.state.refreshing = true;
        try {
            const target = orderId === null ? this.state.currentOrderId : orderId;
            this.state.data = await this.orm.call(
                "sn.wsd.order.flow.dashboard.service",
                "get_order_flow_data",
                target ? [target] : [],
            );
            this.state.currentOrderId = this.state.data?.current_order_id || null;
            this.state.countdown = REFRESH_INTERVAL_SEC;
            this.renderAllCharts();
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    async switchOrder(ev) {
        const orderId = Number(ev.target.value);
        if (orderId) {
            await this.loadData(orderId);
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        if (!this.state.autoRefresh) {
            return;
        }
        this._countdownTimer = setInterval(() => {
            this.state.countdown = this.state.countdown > 0
                ? this.state.countdown - 1 : REFRESH_INTERVAL_SEC;
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

    configureChartDefaults() {
        Chart.defaults.color = "#9defff";
        Chart.defaults.borderColor = "rgba(0, 174, 255, 0.14)";
        Chart.defaults.font.family = "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    }

    destroyCharts() {
        for (const chart of Object.values(this._charts)) {
            chart.destroy();
        }
        this._charts = {};
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
        this.renderGauge();
        this.renderStationChart();
    }

    // 直通率环形仪表
    renderGauge() {
        const tests = this.tests;
        const total = tests.length
            ? this.state.data.tests.length : 0;
        // 用全量测试统计（后端只回传了最近 10 条，直通率用节点数据）
        const testNode = (this.nodes || []).find((n) => n.key === "test");
        let rate = 0;
        if (testNode && testNode.title) {
            const m = String(testNode.title).match(/([\d.]+)%/);
            rate = m ? Number(m[1]) : 0;
        }
        this.ensureChart("gauge", this.gaugeCanvasRef.el, {
            type: "doughnut",
            data: {
                datasets: [{
                    data: [rate, 100 - rate],
                    backgroundColor: ["#00e5ff", "rgba(20, 60, 110, 0.6)"],
                    borderWidth: 0,
                    circumference: 220,
                    rotation: 250,
                }],
            },
            options: {
                cutout: "72%",
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
            },
        });
    }

    // 工序横向条形图
    renderStationChart() {
        const stations = this.stations;
        this.ensureChart("station", this.stationCanvasRef.el, {
            type: "bar",
            data: {
                labels: stations.map((s) => s.step_code + " " + s.name),
                datasets: [
                    {
                        label: "已过站",
                        data: stations.map((s) => s.passed),
                        backgroundColor: "#00e5ff",
                        borderRadius: 3,
                        maxBarThickness: 18,
                        stack: "s",
                    },
                    {
                        label: "在制",
                        data: stations.map((s) => s.wip),
                        backgroundColor: "#ffb020",
                        borderRadius: 3,
                        maxBarThickness: 18,
                        stack: "s",
                    },
                    {
                        label: "待投产",
                        data: stations.map(
                            (s) => Math.max(0, s.qty_total - s.passed - s.wip)),
                        backgroundColor: "rgba(40, 90, 150, 0.35)",
                        borderRadius: 3,
                        maxBarThickness: 18,
                        stack: "s",
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { boxWidth: 10, boxHeight: 10, padding: 14 },
                    },
                },
                scales: {
                    x: { stacked: true, grid: { color: "rgba(0,174,255,0.08)" } },
                    y: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 } } },
                },
            },
        });
    }
}

registry.category("actions").add("sn_wsd_order_flow_screen_action", SnWsdOrderFlowScreenAction);

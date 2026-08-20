/** @odoo-module */

import {
    Component,
    onMounted,
    onWillDestroy,
    onWillStart,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";

const WORLD_CLASS = 85;
const LEVELS = [
    { key: "excellent", min: 85, color: "#1F9D6B", badge: "success" },
    { key: "good", min: 70, color: "#2F80ED", badge: "info" },
    { key: "average", min: 55, color: "#E8A33D", badge: "warning" },
    { key: "poor", min: 0, color: "#D7544C", badge: "danger" },
];

export class OeeReportAction extends Component {
    static template = "sn_wsd_device.OeeReportAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.trendCanvasRef = useRef("trendCanvas");
        this.comparisonCanvasRef = useRef("comparisonCanvas");
        this.distributionCanvasRef = useRef("distributionCanvas");
        this.radarCanvasRef = useRef("radarCanvas");
        this.state = useState({
            loading: true,
            rangeDays: 30,
            equipmentId: 0,
            equipments: [],
            data: null,
        });
        this._charts = {};
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
        });
        onMounted(async () => {
            await this.loadEquipments();
            await this.loadData();
        });
        onWillDestroy(() => this.destroyCharts());
    }

    get labels() {
        return {
            title: _t("OEE Report"),
            allEquipments: _t("All Equipments"),
            refresh: _t("Refresh"),
            avgOee: _t("Average OEE"),
            worldClass: _t("World Class"),
            availability: _t("Availability"),
            performance: _t("Performance"),
            quality: _t("Quality"),
            bestEquipment: _t("Best Equipment"),
            attentionEquipment: _t("Needs Attention"),
            records: _t("Computed Records"),
            equipmentCount: _t("Equipment With Data"),
            trend: _t("OEE Trend"),
            comparison: _t("Equipment OEE Comparison"),
            distribution: _t("OEE Level Distribution"),
            radar: _t("Top Equipment Radar"),
            ranking: _t("Equipment Ranking"),
            rank: _t("Rank"),
            equipment: _t("Equipment"),
            model: _t("Model"),
            oee: _t("OEE"),
            recordsCol: _t("Records"),
            output: _t("Output (pcs)"),
            downtime: _t("Downtime (h)"),
            levelExcellent: _t("Excellent"),
            levelGood: _t("Good"),
            levelAverage: _t("Average"),
            levelPoor: _t("Poor"),
            empty: _t("No computed OEE record in the selected period."),
            noData: _t("No data"),
        };
    }

    get ranges() {
        return [
            { days: 7, label: _t("Last 7 Days") },
            { days: 30, label: _t("Last 30 Days") },
            { days: 90, label: _t("Last 90 Days") },
        ];
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }

    get perEquipment() {
        return this.state.data?.per_equipment || [];
    }

    get isEmpty() {
        return !this.state.loading && !this.kpis.record_count;
    }

    get distributionData() {
        const distribution = this.state.data?.distribution || {};
        return [
            { label: this.labels.levelExcellent, value: distribution.excellent || 0, color: this.levelColor(100) },
            { label: this.labels.levelGood, value: distribution.good || 0, color: this.levelColor(75) },
            { label: this.labels.levelAverage, value: distribution.average || 0, color: this.levelColor(60) },
            { label: this.labels.levelPoor, value: distribution.poor || 0, color: this.levelColor(30) },
        ];
    }

    get radarEquipments() {
        return this.perEquipment.slice(0, 8);
    }

    levelOf(oee) {
        return LEVELS.find((level) => oee >= level.min) || LEVELS[LEVELS.length - 1];
    }

    levelColor(oee) {
        return this.levelOf(oee).color;
    }

    levelBadgeClass(oee) {
        return `text-bg-${this.levelOf(oee).badge}`;
    }

    levelLabel(oee) {
        const labels = this.labels;
        return {
            excellent: labels.levelExcellent,
            good: labels.levelGood,
            average: labels.levelAverage,
            poor: labels.levelPoor,
        }[this.levelOf(oee).key];
    }

    pct(value) {
        return Number(value || 0).toFixed(1);
    }

    number(value) {
        return Number(value || 0).toLocaleString();
    }

    formatDate(date) {
        const month = `${date.getMonth() + 1}`.padStart(2, "0");
        const day = `${date.getDate()}`.padStart(2, "0");
        return `${date.getFullYear()}-${month}-${day}`;
    }

    async loadEquipments() {
        this.state.equipments = await this.orm.call(
            "sn.wsd.device.equipment",
            "search_read",
            [[]],
            { fields: ["code", "name"], order: "code asc" }
        );
    }

    async loadData() {
        this.state.loading = true;
        try {
            const today = new Date();
            const from = new Date();
            from.setDate(from.getDate() - this.state.rangeDays + 1);
            const equipmentIds = this.state.equipmentId
                ? [this.state.equipmentId]
                : [];
            this.state.data = await this.orm.call(
                "sn.wsd.device.oee.record",
                "get_report_data",
                [this.formatDate(from), this.formatDate(today), equipmentIds]
            );
            this.renderCharts();
        } finally {
            this.state.loading = false;
        }
    }

    setRange(days) {
        if (this.state.rangeDays === days) {
            return;
        }
        this.state.rangeDays = days;
        this.loadData();
    }

    onEquipmentChange(event) {
        this.state.equipmentId = Number(event.target.value) || 0;
        this.loadData();
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
            if (this._charts[name].canvas !== canvas) {
                this._charts[name].destroy();
                delete this._charts[name];
            } else {
                this._charts[name].data = config.data;
                this._charts[name].options = config.options;
                this._charts[name].update();
                return;
            }
        }
        this._charts[name] = new Chart(canvas, config);
    }

    renderCharts() {
        this.renderTrendChart();
        this.renderComparisonChart();
        this.renderDistributionChart();
        this.renderRadarChart();
    }

    renderTrendChart() {
        const trend = this.state.data?.trend || [];
        const gradient = (context) => {
            const chartArea = context.chart.chartArea;
            if (!chartArea) {
                return "rgba(113, 75, 103, 0.12)";
            }
            const { ctx } = context.chart;
            const gradientFill = ctx.createLinearGradient(
                0, chartArea.top, 0, chartArea.bottom
            );
            gradientFill.addColorStop(0, "rgba(113, 75, 103, 0.28)");
            gradientFill.addColorStop(1, "rgba(113, 75, 103, 0.02)");
            return gradientFill;
        };
        this.ensureChart("trend", this.trendCanvasRef.el, {
            type: "line",
            data: {
                labels: trend.map((point) => point.date.slice(5)),
                datasets: [
                    {
                        label: this.labels.avgOee,
                        data: trend.map((point) => point.oee),
                        borderColor: "#714B67",
                        backgroundColor: gradient,
                        borderWidth: 2.5,
                        pointRadius: trend.length > 20 ? 0 : 3,
                        tension: 0.35,
                        fill: true,
                    },
                    {
                        label: `${this.labels.worldClass} (85%)`,
                        data: trend.map(() => WORLD_CLASS),
                        borderColor: "rgba(31, 157, 107, 0.7)",
                        borderWidth: 1.5,
                        borderDash: [6, 4],
                        pointRadius: 0,
                        fill: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { position: "bottom" },
                    tooltip: {
                        callbacks: {
                            label: (context) =>
                                `${context.dataset.label}: ${Number(
                                    context.parsed.y
                                ).toFixed(1)}%`,
                        },
                    },
                },
                scales: {
                    y: {
                        suggestedMin: 0,
                        suggestedMax: 100,
                        ticks: { callback: (value) => `${value}%` },
                    },
                },
            },
        });
    }

    renderComparisonChart() {
        // Sort ascending so the best equipment ends up on top of the
        // horizontal bars.
        const items = [...this.perEquipment].sort((a, b) => a.oee - b.oee);
        this.ensureChart("comparison", this.comparisonCanvasRef.el, {
            type: "bar",
            data: {
                labels: items.map((item) => item.equipment_code || item.equipment_name),
                datasets: [
                    {
                        label: this.labels.oee,
                        data: items.map((item) => item.oee),
                        backgroundColor: items.map((item) => this.levelColor(item.oee)),
                        borderRadius: 4,
                        maxBarThickness: 26,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${this.pct(context.parsed.x)}%`,
                        },
                    },
                },
                scales: {
                    x: {
                        suggestedMin: 0,
                        suggestedMax: 100,
                        ticks: { callback: (value) => `${value}%` },
                    },
                },
            },
        });
    }

    renderDistributionChart() {
        const items = this.distributionData;
        this.ensureChart("distribution", this.distributionCanvasRef.el, {
            type: "doughnut",
            data: {
                labels: items.map((item) => item.label),
                datasets: [
                    {
                        data: items.map((item) => item.value),
                        backgroundColor: items.map((item) => item.color),
                        borderWidth: 2,
                        borderColor: "#ffffff",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                plugins: {
                    legend: { position: "bottom" },
                },
            },
        });
    }

    renderRadarChart() {
        const items = this.radarEquipments;
        this.ensureChart("radar", this.radarCanvasRef.el, {
            type: "radar",
            data: {
                labels: items.map((item) => item.equipment_code || item.equipment_name),
                datasets: [
                    {
                        label: this.labels.oee,
                        data: items.map((item) => item.oee),
                        borderColor: "#2F80ED",
                        backgroundColor: "rgba(47, 128, 237, 0.18)",
                        borderWidth: 2,
                        pointBackgroundColor: items.map((item) => this.levelColor(item.oee)),
                        pointRadius: 3.5,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${this.pct(context.parsed.r)}%`,
                        },
                    },
                },
                scales: {
                    r: {
                        suggestedMin: 0,
                        suggestedMax: 100,
                        ticks: {
                            stepSize: 25,
                            callback: (value) => `${value}%`,
                        },
                        pointLabels: { font: { size: 10 } },
                    },
                },
            },
        });
    }
}

registry
    .category("actions")
    .add("sn_wsd_device_oee_report", OeeReportAction);

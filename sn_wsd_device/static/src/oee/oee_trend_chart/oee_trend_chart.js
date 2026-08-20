/** @odoo-module */

import {
    Component,
    onWillDestroy,
    onWillStart,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { loadBundle } from "@web/core/assets";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

const DATASET_STYLES = {
    oee: { color: "#714B67", width: 3 },
    availability: { color: "#2F80ED", width: 1.5 },
    performance: { color: "#1F9D6B", width: 1.5 },
    quality: { color: "#E8A33D", width: 1.5 },
};

export class OeeTrendChartField extends Component {
    static template = "sn_wsd_device.OeeTrendChartField";
    static props = { ...standardFieldProps };

    setup() {
        this.canvasRef = useRef("canvas");
        this.state = useState({ range: 30 });
        this.chart = null;
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
        });
        useEffect(
            () => {
                this.renderChart();
            },
            () => [
                JSON.stringify(
                    this.props.record.data[this.props.name] ?? null),
                this.state.range,
            ]
        );
        onWillDestroy(() => this.destroyChart());
    }

    get labels() {
        return {
            title: _t("OEE Trend"),
            days7: _t("7 Days"),
            days30: _t("30 Days"),
            oee: _t("OEE"),
            availability: _t("Availability"),
            performance: _t("Performance"),
            quality: _t("Quality"),
            empty: _t(
                "No computed OEE record for this equipment in the last 30 days."
            ),
        };
    }

    get points() {
        const value = this.props.record.data[this.props.name];
        const data = Array.isArray(value) ? value : [];
        return data.slice(-this.state.range);
    }

    get isEmpty() {
        return this.points.length === 0;
    }

    destroyChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    renderChart() {
        const canvas = this.canvasRef.el;
        if (!canvas) {
            this.destroyChart();
            return;
        }
        if (typeof Chart === "undefined") {
            return;
        }
        const points = this.points;
        const labels = this.labels;
        const style = (key) => DATASET_STYLES[key];
        const series = [
            { key: "oee", label: labels.oee },
            { key: "availability", label: labels.availability },
            { key: "performance", label: labels.performance },
            { key: "quality", label: labels.quality },
        ];
        const config = {
            type: "line",
            data: {
                labels: points.map((point) => point.date.slice(5)),
                datasets: series.map((item) => ({
                    label: item.label,
                    data: points.map((point) => point[item.key]),
                    borderColor: style(item.key).color,
                    backgroundColor: style(item.key).color,
                    borderWidth: style(item.key).width,
                    pointRadius: points.length > 15 ? 0 : 3,
                    pointHoverRadius: 4,
                    tension: 0.3,
                    fill: item.key === "oee",
                    ...(item.key === "oee"
                        ? { backgroundColor: "rgba(113, 75, 103, 0.08)" }
                        : {}),
                })),
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
        };
        if (this.chart && this.chart.canvas !== canvas) {
            this.destroyChart();
        }
        if (this.chart) {
            this.chart.data = config.data;
            this.chart.options = config.options;
            this.chart.update();
        } else {
            this.chart = new Chart(canvas, config);
        }
    }

    setRange(range) {
        this.state.range = range;
    }
}

registry.category("fields").add("sn_wsd_oee_trend_chart", {
    component: OeeTrendChartField,
    displayName: _t("OEE Trend Chart"),
    supportedTypes: ["json"],
});

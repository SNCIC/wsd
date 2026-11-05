/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useState } from "@odoo/owl";

const LABELS = {
    category: _t("Category"),
    count: _t("Count"),
    cumulative: _t("Cumulative (%)"),
    dimension: _t("Dimension"),
    distribution: _t("Distribution"),
    from: _t("From"),
    level: _t("Level"),
    line: _t("Production Line"),
    noData: _t("No exception in this range."),
    rank: _t("Rank"),
    share: _t("Share (%)"),
    subcategory: _t("Subcategory"),
    title: _t("MES Exception Pareto Report"),
    to: _t("To"),
    total: _t("Total"),
    view: _t("View"),
};

export class SnWsdParetoDashboard extends Component {
    static template = "sn_wsd_exception.ParetoDashboard";
    static props = standardActionServiceProps;

    setup() {
        this.orm = useService("orm");
        this.labels = LABELS;
        const today = new Date();
        const first = new Date(today.getFullYear(), today.getMonth(), 1);
        const fmt = (d) => {
            const m = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            return `${d.getFullYear()}-${m}-${day}`;
        };
        this.state = useState({
            dimension: "subcategory",
            date_from: fmt(first),
            date_to: fmt(today),
            rows: [],
            total: 0,
            loading: false,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            const data = await this.orm.silent.call(
                "sn.wsd.exception.service", "pareto_data", [], {
                    dimension: this.state.dimension,
                    date_from: this.state.date_from,
                    date_to: this.state.date_to,
                });
            this.state.rows = data.rows || [];
            this.state.total = data.total || 0;
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("actions").add("sn_wsd_pareto", SnWsdParetoDashboard);

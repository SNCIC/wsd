/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PAGE_SIZE = 80;

const VERDICT_LABELS = {
    ok: _t("OK"),
    ng: _t("NG"),
    scrap: _t("Scrap"),
    retested: _t("Retested OK"),
    concession: _t("Concession"),
};

const DISPOSITION_LABELS = {
    pending: _t("Awaiting Disposition"),
    reworking: _t("Reworking"),
    awaiting_reinspection: _t("Awaiting Re-inspection"),
    retest_passed: _t("Retest Passed"),
    scrapped: _t("Scrapped"),
    concession: _t("Concession Accepted"),
};

/**
 * Inspected List (oqc-full-lot-form / oqc-disposition-closure task 7.3):
 * paginated ledger of the boards that passed this inspection's OQC
 * operation. The whole page (rows, total and per-verdict counts) comes
 * from the server method oqc_ledger_page: the final verdict per SN is
 * derived server-side from the latest pass + disposition state, so the
 * browser never loads the full cell set or event list, huge lots stay
 * fast and the filter matches what is displayed. Read-only.
 */
export class OqcInspectedList extends Component {
    static template = "sn_wsd_quality.OqcInspectedList";
    static props = { record: Object };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        // all UI strings translated once here; the template reads this.labels
        this.labels = {
            searchPlaceholder: _t("Search SN... (Enter)"),
            all: _t("All"),
            ok: _t("OK"),
            ng: _t("NG"),
            scrap: _t("Scrap"),
            loading: _t("Loading..."),
            empty: _t("No inspected boards yet."),
            sn: _t("SN"),
            result: _t("Result"),
            disposition: _t("Disposition"),
            inspectedAt: _t("Inspected At"),
            operator: _t("Operator"),
            defectCode: _t("Defect Code"),
            passes: _t("Passes"),
        };
        this.state = useState({
            loading: true,
            rows: [],
            total: 0,
            counts: { ok: 0, ng: 0, scrap: 0 },
            page: 1,
            pageCount: 1,
            search: "",
            verdict: "all",
        });
        onWillStart(() => this.load());
        onWillUpdateProps(() => this.load());
    }

    get totalLabel() {
        return _t("%s record(s)", this.state.total);
    }

    get countsLabel() {
        const counts = this.state.counts || {};
        return _t("OK %(ok)s / NG %(ng)s / Scrap %(scrap)s", {
            ok: counts.ok || 0,
            ng: counts.ng || 0,
            scrap: counts.scrap || 0,
        });
    }

    async load() {
        // read the doc ourselves: hidden form fields carry no value in the
        // record (invisible groups are not read), so never trust record.data
        const resId = this.props.record.resId;
        if (!resId) {
            this.state.rows = [];
            this.state.total = 0;
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        const result = await this.orm.silent.call(
            "sn.wsd.quality.inspection",
            "oqc_ledger_page",
            [resId, this.state.verdict, this.state.page, PAGE_SIZE,
             this.state.search.trim()],
        );
        this.state.rows = result.rows || [];
        this.state.total = result.total || 0;
        this.state.counts = result.counts || { ok: 0, ng: 0, scrap: 0 };
        this.state.pageCount = result.page_count || 1;
        this.state.page = result.page || 1;
        this.state.loading = false;
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    onSearch(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        this.state.page = 1;
        this.load();
    }

    onVerdictChange(ev) {
        this.state.verdict = ev.target.value;
        this.state.page = 1;
        this.load();
    }

    prev() {
        if (this.state.page > 1) {
            this.state.page -= 1;
            this.load();
        }
    }

    next() {
        if (this.state.page < this.state.pageCount) {
            this.state.page += 1;
            this.load();
        }
    }

    verdictLabel(verdict) {
        return VERDICT_LABELS[verdict] || verdict;
    }

    dispositionLabel(state) {
        return state ? DISPOSITION_LABELS[state] || state : "";
    }

    verdictClass(verdict) {
        if (verdict === "ok" || verdict === "retested" || verdict === "concession") {
            return "text-bg-success";
        }
        if (verdict === "ng") {
            return "text-bg-danger";
        }
        return "text-bg-secondary";
    }

    defectCode(row) {
        return row.defect_code || "";
    }

    /** raw station passes of one board: the original pass-record entry */
    openStationHistory(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.labels.sn + " - " + (row.serial_name || ""),
            res_model: "sn.wsd.serial.operation.history",
            view_mode: "list",
            domain: [
                ["serial_identity_id", "=", row.serial_id],
                ["mes_order_id", "=", this.props.record.data.mes_order_id?.[0]],
            ],
        });
    }
}

export const oqcInspectedList = {
    component: OqcInspectedList,
};

registry.category("view_widgets").add("oqc_inspected_list", oqcInspectedList);

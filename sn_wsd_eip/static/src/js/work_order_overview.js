/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useBus, useChildSubEnv, useState } from "@odoo/owl";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { SearchModel } from "@web/search/search_model";
import { user } from "@web/core/user";

// the page survives a round-trip through a record form: the whole
// state snapshot rides in sessionStorage under this key and is
// restored on the next mount instead of starting empty
const STATE_KEY = "eip_work_order_overview_state";

// the detail search area searches the records of the open detail
const TAB_MODELS = {
    pass: "sn.wsd.eip.pass.record",
    raw: "sn.wsd.eip.raw.record",
    pack: "sn.wsd.eip.pack.record",
    ship: "sn.wsd.eip.ship.record",
};
const SEARCH_FIELD_NAMES = {
    pass: ["sn_name", "check_time", "state", "workcenter_id",
           "device_no", "conclusion"],
    raw: ["test_code", "material_batch", "check_time", "state"],
    pack: ["test_code", "nameplate_code", "storage_date", "state"],
    ship: ["test_code", "nameplate_start", "nameplate_final",
           "deliver_status", "state"],
};

/** The native search area of one detail list: the web client
 * SearchBar bound to a SearchModel over the detail's model. Its
 * conditions leave as a plain domain through onSearch. */
export class OverviewSearchArea extends Component {
    static template = "sn_wsd_eip.OverviewSearchArea";
    static components = { SearchBar };
    static props = {
        model: String,
        fieldNames: Array,
        domain: { type: Array, optional: true },
        onSearch: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.searchModel = new SearchModel(this.env, this.env.services);
        // SearchBar reads the model from the child environment
        useChildSubEnv({ searchModel: this.searchModel });
        this.state = useState({ ready: false });
        useBus(this.searchModel, "update", () =>
            this.props.onSearch(this.searchModel.domain || []));
        onWillStart(async () => {
            const fields = await this.orm.call(
                this.props.model, "fields_get", [this.props.fieldNames],
                { attributes: ["string", "type"] });
            const arch = "<search>" + this.props.fieldNames.map(
                (name) => `<field name="${name}"/>`).join("") + "</search>";
            await this.searchModel.load({
                resModel: this.props.model,
                searchViewArch: arch,
                searchViewFields: fields,
                searchMenuTypes: [],
                display: { searchPanel: false },
            });
            this.state.ready = true;
        });
    }
}

const PAGE_SIZE = 80;

export class WorkOrderOverview extends Component {
    static template = "sn_wsd_eip.WorkOrderOverview";
    static components = { OverviewSearchArea };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        // Request sequencing: every async answer whose sequence is not the
        // current one is dropped, so only the latest request may paint
        // (typing a new work order quickly, clicking numbers in turn).
        this.reqSeq = 0;
        this.suggestSeq = 0;
        this.searchTimer = null;
        this.state = useState({
            isManager: false,
            // work order picker
            term: "",
            suggestions: [],
            // overview snapshot (get_overview)
            loading: false,
            workOrderNo: "",
            header: {},
            tabs: [],
            activeTab: "",
            pass: [],
            raw: [],
            pack: [],
            ship: [],
            reportCount: 0,
            // drill-down (get_detail): {tab, code, name, operation, flag,
            // total, rows, loading, columns, searchDomain}
            detail: null,
        });
        if (!this._restoreState()) {
            this.state.isManager = false;
        }
        this.tabLabels = {
            pass: _t("Process Steps"),
            raw: _t("Raw Material Inspection"),
            pack: _t("Packing Storage"),
            ship: _t("Shipping"),
        };
        this.tabModels = {
            pass: "sn.wsd.eip.pass.record",
            raw: "sn.wsd.eip.raw.record",
            pack: "sn.wsd.eip.pack.record",
            ship: "sn.wsd.eip.ship.record",
        };
        this.flagLabels = {
            pass: {
                units: _t("Units"),
                ng: _t("NG"),
                missing: _t("Missing Required"),
                limit: _t("Out of Limit"),
                pending: _t("To Do"),
                rejected: _t("Rejected"),
            },
            raw: {
                all: _t("All"),
                ng: _t("NG"),
                pending: _t("Awaiting Delivery"),
                delivered: _t("Delivered"),
            },
            pack: {
                all: _t("All"),
                ng: _t("NG"),
                pending: _t("Awaiting Delivery"),
                delivered: _t("Delivered"),
            },
            ship: {
                all: _t("All"),
                shipped: _t("Shipped"),
                not_shipped: _t("Not Shipped"),
                pending: _t("Awaiting Delivery"),
                delivered: _t("Delivered"),
            },
        };
        this.stateLabels = {
            qualified: _t("Qualified"),
            rejected: _t("Rejected"),
            delivered: _t("Delivered"),
        };
        // The clean and batch-correction actions keep the rights of the
        // functions behind them (snapshots, detail lines and corrections
        // are writable for MRP managers only), so their buttons show for
        // managers only.
        onWillStart(async () => {
            this.state.isManager = await user.hasGroup(
                "mrp.group_mrp_manager"
            );
        });
        this.labels = {
            title: _t("Work Order Data Overview"),
            workOrder: _t("Work Order"),
            searchPlaceholder: _t("Work order number..."),
            cleanProcessData: _t("Generate Outbox Records"),
            productionOrder: _t("Production Order"),
            firstCheck: _t("First Check"),
            lastCheck: _t("Last Check"),
            plannedQty: _t("Production Quantity"),
            operation: _t("Operation"),
            code: _t("Code"),
            units: _t("Units"),
            qualifiedUnits: _t("Qualified Units"),
            ngUnits: _t("NG Units"),
            missingRequired: _t("Missing Required"),
            outOfLimit: _t("Out of Limit"),
            pendingClean: _t("To Do"),
            rejected: _t("Rejected"),
            inspection: _t("Inspection"),
            // the first column of the packing / shipping tables names the
            // collected data type (1090 / 2090 ...), not an API endpoint
            interfaceCol: _t("数据类型"),
            records: _t("Records"),
            ngRecords: _t("NG Records"),
            pending: _t("Awaiting Delivery"),
            delivered: _t("Delivered"),
            rawReports: _t("Raw Material Reports"),
            reports: _t("Reports"),
            storedUnits: _t("Stored Units"),
            batches: _t("Batches"),
            shippedQuantity: _t("Shipped Quantity"),
            shippedBatches: _t("Shipped Batches"),
            notShippedBatches: _t("Not Shipped Batches"),
            open: _t("Open"),
            loadMore: _t("Load more"),
            batchCorrection: _t("Batch Correction"),
            sn: _t("SN"),
            checkTime: _t("Check Time"),
            workcenter: _t("Workcenter"),
            state: _t("State"),
            conclusion: _t("Conclusion"),
            issues: _t("Issues"),
            testCode: _t("Test Code"),
            materialCheckBatch: _t("Material Check Batch"),
            materialBatch: _t("Material Batch"),
            nameplateCode: _t("Nameplate Code"),
            number: _t("Number"),
            storageDate: _t("Storage Date"),
            nameplateStart: _t("Nameplate Start"),
            nameplateFinal: _t("Nameplate Final"),
            deliverDate: _t("Deliver Date"),
            deliverStatus: _t("Deliver Status"),
            ok: _t("OK"),
            ng: _t("NG"),
            shipped: _t("Shipped"),
            notShipped: _t("Not Shipped"),
            emptyHint: _t(
                "Enter or pick a work order number to load its collected production data."
            ),
        };
    }

    // ------------------------------------------------------------------
    // template helpers
    // ------------------------------------------------------------------

    get hasData() {
        return !this.state.loading && this.state.tabs.length > 0;
    }

    get canClean() {
        return this.state.isManager && this.state.tabs.includes("pass");
    }

    get canBatchFix() {
        const d = this.state.detail;
        return (
            this.state.isManager &&
            Boolean(d) &&
            d.tab === "pass" &&
            d.flag === "missing"
        );
    }

    get canLoadMore() {
        const d = this.state.detail;
        return Boolean(d) && !d.loading && d.rows.length < d.total;
    }

    get detailRows() {
        return this.state.detail ? this.state.detail.rows : [];
    }

    get detailModel() {
        return this.state.detail ? TAB_MODELS[this.state.detail.tab] : "";
    }

    get detailFieldNames() {
        return this.state.detail
            ? SEARCH_FIELD_NAMES[this.state.detail.tab] : [];
    }

    /** The search area produced a new condition set: refetch the
     * detail from the first page with the domain applied. */
    onSearch(domain) {
        const d = this.state.detail;
        if (!d) {
            return;
        }
        if (JSON.stringify(domain) === JSON.stringify(d.searchDomain || [])) {
            return;
        }
        d.searchDomain = domain || [];
        d.rows = [];
        d.total = 0;
        d.loading = true;
        this.reqSeq += 1;
        this.fetchDetail(this.reqSeq);
    }

    get detailTitle() {
        const d = this.state.detail;
        if (!d) {
            return "";
        }
        const base = (d.tab === "pass" ? d.operation : d.name) || d.code;
        return `${base} · ${this.flagLabel(d.tab, d.flag)}`;
    }

    tabLabel(tab) {
        return this.tabLabels[tab] || tab;
    }

    tabCount(tab) {
        return (this.state[tab] || []).length;
    }

    flagLabel(tab, flag) {
        return (this.flagLabels[tab] || {})[flag] || flag;
    }

    stateLabel(state) {
        if (state === "pending") {
            return this.state.activeTab === "pass"
                ? _t("Pending Clean")
                : _t("Awaiting Delivery");
        }
        return this.stateLabels[state] || state || "";
    }

    badgeClass(state) {
        switch (state) {
            case "delivered":
                return "text-bg-success";
            case "rejected":
                return "text-bg-danger";
            case "pending":
                return "text-bg-warning";
            case "qualified":
                return "text-bg-info";
            default:
                return "text-bg-secondary";
        }
    }

    conclusionLabel(value) {
        // spec: 0 pass, 1 fail
        return Number(value) === 1 ? this.labels.ng : this.labels.ok;
    }

    conclusionClass(value) {
        return Number(value) === 1
            ? "text-bg-danger"
            : "text-bg-success";
    }

    deliverStatusLabel(value) {
        return String(value) === "1"
            ? this.labels.shipped
            : this.labels.notShipped;
    }

    deliverStatusClass(value) {
        return String(value) === "1"
            ? "text-bg-success"
            : "text-bg-secondary";
    }

    /** All collected units of the step are qualified: the step's
     * qualified count equals the work order's production quantity. */
    isFullyQualified(row) {
        const planned = Number(this.state.header.planned_qty);
        return planned > 0 && row.qualified === planned;
    }

    cellClass(code, flag) {
        const d = this.state.detail;
        if (
            d &&
            d.tab === this.state.activeTab &&
            d.code === code &&
            d.flag === flag
        ) {
            return "o_eip_drilled";
        }
        return "";
    }

    hasValue(value) {
        return (
            value !== undefined &&
            value !== null &&
            value !== false &&
            value !== ""
        );
    }

    /** Compact issue line: only the parts that are present. */
    issueLine(issue) {
        const parts = [];
        if (this.hasValue(issue.type_code)) {
            parts.push(String(issue.type_code));
        }
        if (this.hasValue(issue.field_name)) {
            parts.push(String(issue.field_name));
        }
        // the measured value and its limits belong to an
        // out-of-limit problem only
        if (issue.kind === "limit" && this.hasValue(issue.actual_value)) {
            parts.push(String(issue.actual_value));
        }
        const limits = issue.kind === "limit" ? this.issueLimits(issue) : "";
        if (limits) {
            parts.push(limits);
        }
        if (this.hasValue(issue.message)) {
            parts.push(String(issue.message));
        }
        return parts.join(" ");
    }

    issueLimits(issue) {
        const hasLower = this.hasValue(issue.lower_limit);
        const hasUpper = this.hasValue(issue.upper_limit);
        if (hasLower && hasUpper) {
            return `(${issue.lower_limit} ~ ${issue.upper_limit})`;
        }
        if (hasLower) {
            return `(>= ${issue.lower_limit})`;
        }
        if (hasUpper) {
            return `(<= ${issue.upper_limit})`;
        }
        return "";
    }

    errorMessage(error) {
        return (
            error?.data?.message || error?.message || String(error)
        );
    }

    notify(message, type) {
        this.notification.add(message, { type });
    }

    // ------------------------------------------------------------------
    // work order picker (type to search, click to apply)
    // ------------------------------------------------------------------

    onTermInput(ev) {
        this.state.term = ev.target.value;
        clearTimeout(this.searchTimer);
        const term = this.state.term.trim();
        if (!term) {
            this.state.suggestions = [];
            return;
        }
        this.searchTimer = setTimeout(() => {
            this.searchOrders(term);
        }, 250);
    }

    async searchOrders(term) {
        this.suggestSeq += 1;
        const seq = this.suggestSeq;
        let records = [];
        try {
            records = await this.orm.searchRead(
                "sn.wsd.mes.order",
                [["name", "ilike", term]],
                ["name"],
                { limit: 20 }
            );
        } catch (error) {
            return; // suggestions are best effort
        }
        if (seq !== this.suggestSeq) {
            return;
        }
        this.state.suggestions = records.map((r) => r.name);
    }

    onTermKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            clearTimeout(this.searchTimer);
            this.loadOverview(this.state.term);
        }
    }

    pickSuggestion(name) {
        this.loadOverview(name);
    }

    hideSuggestions() {
        this.state.suggestions = [];
    }

    // ------------------------------------------------------------------
    // overview (single call, summary of every tab)
    // ------------------------------------------------------------------

    /** Snapshot the mutable state (called before every paint). */
    persistState() {
        try {
            sessionStorage.setItem(
                STATE_KEY,
                JSON.stringify({
                    workOrderNo: this.state.workOrderNo,
                    activeTab: this.state.activeTab,
                    header: this.state.header,
                    tabs: this.state.tabs,
                    pass: this.state.pass,
                    raw: this.state.raw,
                    pack: this.state.pack,
                    ship: this.state.ship,
                    reportCount: this.state.reportCount,
                    detail: this.state.detail,
                }));
        } catch {
            // storage full / unavailable: the page just loses its
            // state on navigation, nothing breaks
        }
    }

    _restoreState() {
        let saved = null;
        try {
            saved = JSON.parse(sessionStorage.getItem(STATE_KEY) || "null");
        } catch {
            saved = null;
        }
        if (!saved || !saved.workOrderNo) {
            return false;
        }
        Object.assign(this.state, saved);
        this.state.loading = false;
        return true;
    }

    async loadOverview(workOrderNo) {
        const wo = String(workOrderNo || "").trim();
        if (!wo) {
            this.notify(_t("Enter a work order number."), "warning");
            return;
        }
        this.state.term = wo;
        this.state.suggestions = [];
        this.reqSeq += 1;
        const seq = this.reqSeq;
        this.state.loading = true;
        this.state.detail = null;
        try {
            const data = await this.orm.call(
                "sn.wsd.eip.pass.record",
                "get_overview",
                [wo]
            );
            if (seq !== this.reqSeq) {
                return;
            }
            this.state.workOrderNo = data.work_order_no || wo;
            this.persistState();
            this.state.header = data.header || {};
            this.state.tabs = data.tabs || [];
            this.state.pass = data.pass || [];
            this.state.raw = data.raw || [];
            this.state.pack = data.pack || [];
            this.state.ship = data.ship || [];
            this.state.reportCount = data.report_count || 0;
            this.state.activeTab = this.state.tabs[0] || "";
        } catch (error) {
            if (seq !== this.reqSeq) {
                return;
            }
            this.resetOverview();
            this.notify(this.errorMessage(error), "danger");
        } finally {
            if (seq === this.reqSeq) {
                this.state.loading = false;
            }
        }
    }

    resetOverview() {
        this.state.workOrderNo = "";
        this.state.header = {};
        this.state.tabs = [];
        this.state.activeTab = "";
        this.state.pass = [];
        this.state.raw = [];
        this.state.pack = [];
        this.state.ship = [];
        this.state.reportCount = 0;
    }

    reload() {
        if (this.state.workOrderNo) {
            this.loadOverview(this.state.workOrderNo);
        }
    }

    switchTab(tab) {
        if (this.state.activeTab === tab) {
            return;
        }
        this.reqSeq += 1; // drop any in-flight detail of the previous tab
        this.state.activeTab = tab;
        this.state.detail = null;
    }

    // ------------------------------------------------------------------
    // drill-down (server-side pagination, append on load more)
    // ------------------------------------------------------------------

    drill(row, flag) {
        if (this.state.loading) {
            return;
        }
        this.reqSeq += 1;
        const seq = this.reqSeq;
        // swap the detail immediately: old rows must not linger under the
        // newly clicked number while the fetch is in flight
        this.state.detail = {
            tab: this.state.activeTab,
            code: row.code,
            name: row.name || "",
            operation: row.operation || "",
            flag,
            total: 0,
            rows: [],
            loading: true,
            searchDomain: [],
        };
        this.fetchDetail(seq);
    }

    loadMore() {
        const d = this.state.detail;
        if (!d || d.loading) {
            return;
        }
        this.reqSeq += 1;
        const seq = this.reqSeq;
        d.loading = true;
        this.fetchDetail(seq);
    }

    async fetchDetail(seq) {
        const d = this.state.detail;
        if (!d) {
            return;
        }
        try {
            const res = await this.orm.call(
                "sn.wsd.eip.pass.record",
                "get_detail",
                [this.state.workOrderNo, d.tab, d.code, d.flag,
                 PAGE_SIZE, d.rows.length, d.searchDomain || []]
            );
            if (seq !== this.reqSeq || this.state.detail !== d) {
                return;
            }
            d.total = res.total || 0;
            d.rows = d.rows.concat(res.rows || []);
            d.columns = d.rows.length === res.rows.length
                ? res.columns || []
                : d.columns;
            d.loading = false;
            this.persistState();
        } catch (error) {
            if (seq !== this.reqSeq || this.state.detail !== d) {
                return;
            }
            d.loading = false;
            this.state.detail = null;
            this.notify(this.errorMessage(error), "danger");
        }
    }

    // ------------------------------------------------------------------
    // actions (built inline: ordinary users cannot read ir.actions.*)
    // ------------------------------------------------------------------

    async openRecord(row) {
        const model = this.tabModels[this.state.activeTab];
        if (!model) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: row.id,
            views: [[false, "form"]],
        });
    }

    batchCorrection() {
        const d = this.state.detail;
        if (!this.canBatchFix || d.loading || !d.rows.length) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Batch Correction"),
            res_model: "sn.wsd.eip.clean.fix.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                active_ids: d.rows.map((r) => r.id),
                active_model: "sn.wsd.eip.pass.record",
            },
        });
    }

    cleanProcessData() {
        if (!this.canClean || this.state.loading) {
            return;
        }
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Re-clean by Work Order"),
                res_model: "sn.wsd.eip.clean.order.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_work_order_no: this.state.workOrderNo,
                },
            },
            { onClose: () => this.reload() }
        );
    }
}

registry.category("actions").add(
    "sn_wsd_eip_work_order_overview",
    WorkOrderOverview
);

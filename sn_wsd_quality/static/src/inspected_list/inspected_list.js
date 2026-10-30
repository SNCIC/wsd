/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const PAGE_SIZE = 80;
const RESULT_LABELS = {
    ok: _t("OK"),
    ng: _t("NG"),
    scrap: _t("Scrap"),
};

/**
 * Inspected List (oqc-full-lot-form): paginated ledger of the boards that
 * passed this inspection's OQC operation. Server-side paging through the
 * pass history -- the form never loads the full list, so huge lots stay
 * fast. Read-only.
 */
export class OqcInspectedList extends Component {
    static template = "sn_wsd_quality.OqcInspectedList";
    static props = { record: Object };

    setup() {
        this.orm = useService("orm");
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
            inspectedAt: _t("Inspected At"),
            operator: _t("Operator"),
            defectCode: _t("Defect Code"),
        };
        this.state = useState({
            loading: true,
            rows: [],
            total: 0,
            page: 1,
            search: "",
            verdict: "all",
        });
        onWillStart(() => this.load());
        onWillUpdateProps(() => this.load());
    }

    get totalLabel() {
        return _t("%s record(s)", this.state.total);
    }

    get record() {
        return this.props.record;
    }

    get orderId() {
        return this.record.data.mes_order_id?.[0] || false;
    }

    get routeOperationIds() {
        // the OQC operation rows of this order's route
        return null; // computed in load() from the inspection's scheme op
    }

    buildDomain() {
        const domain = [
            ["mes_order_id", "=", this.orderId],
            ["result", "in", ["ok", "ng", "scrap"]],
        ];
        if (this.state.search.trim()) {
            domain.push(["serial_identity_id.name", "ilike", this.state.search.trim()]);
        }
        if (this.state.verdict !== "all") {
            domain.push(["result", "=", this.state.verdict]);
        }
        return domain;
    }

    async load() {
        // read the doc ourselves: hidden form fields carry no value in the
        // record (invisible groups are not read), so never trust record.data
        const resId = this.record.resId;
        if (!resId) {
            this.state.rows = [];
            this.state.total = 0;
            this.state.loading = false;
            return;
        }
        const docs = await this.orm.silent.read(
            "sn.wsd.quality.inspection", [resId],
            ["mes_order_id", "route_operation_id"]);
        const orderId = docs[0]?.mes_order_id?.[0] || false;
        // the inspection's own route_operation_id IS the OQC operation row
        const routeOpId = docs[0]?.route_operation_id?.[0] || false;
        if (!orderId || !routeOpId) {
            this.state.rows = [];
            this.state.total = 0;
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        const base = [
            ["mes_order_id", "=", orderId],
            ["route_operation_id", "=", routeOpId],
            ["result", "in", ["ok", "ng", "scrap"]],
        ];
        const extra = this.buildDomain().slice(2);
        const domain = [...base, ...extra];
        // the doc's own cell verdicts: an NG board re-judged pass on the doc
        // (in-place retest) leaves no new pass history -- merge the cell
        // verdict into the display so the ledger shows the final verdict.
        // Ledger mode keeps cells only for defective boards: tiny payload.
        const cellRead = this.orm.silent.read(
            "sn.wsd.quality.inspection", [resId], ["cell_ids"]);
        const [total, rows, cells] = await Promise.all([
            this.orm.silent.searchCount("sn.wsd.serial.operation.history", domain),
            this.orm.silent.searchRead(
                "sn.wsd.serial.operation.history", domain,
                ["serial_identity_id", "result", "out_date", "operator_code",
                 "defect_code_id"],
                { order: "out_date desc, id desc",
                  limit: PAGE_SIZE, offset: (this.state.page - 1) * PAGE_SIZE }),
            cellRead,
        ]);
        const cellIds = cells[0]?.cell_ids || [];
        let cellVerdicts = {};
        if (cellIds.length) {
            const cellRows = await this.orm.silent.searchRead(
                "sn.wsd.quality.inspection.cell",
                [["id", "in", cellIds],
                 ["inspection_id", "=", resId]],
                ["serial_identity_id", "result"]);
            for (const row of cellRows) {
                const snId = row.serial_identity_id[0];
                if (row.result === "fail") {
                    cellVerdicts[snId] = "ng";
                } else if (!cellVerdicts[snId]) {
                    cellVerdicts[snId] = row.result === "pass" ? "pass" : cellVerdicts[snId];
                }
            }
        }
        this.cellVerdicts = cellVerdicts;
        this.state.total = total;
        this.state.rows = rows;
        this.state.loading = false;
    }

    /** merged display verdict: an in-place retest flips an NG history row */
    displayVerdict(row) {
        const snId = row.serial_identity_id ? row.serial_identity_id[0] : false;
        const cell = snId ? this.cellVerdicts[snId] : undefined;
        if (row.result === "ng" && cell === "pass") {
            return "retested";
        }
        return row.result;
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

    get pageCount() {
        return Math.max(1, Math.ceil(this.state.total / PAGE_SIZE));
    }

    prev() {
        if (this.state.page > 1) {
            this.state.page -= 1;
            this.load();
        }
    }

    next() {
        if (this.state.page < this.pageCount) {
            this.state.page += 1;
            this.load();
        }
    }

    verdictLabel(result) {
        if (result === "retested") {
            return _t("Retested OK");
        }
        return RESULT_LABELS[result] || result;
    }

    defectCode(row) {
        return row.defect_code_id ? row.defect_code_id[1] : "";
    }
}

export const oqcInspectedList = {
    component: OqcInspectedList,
};

registry.category("view_widgets").add("oqc_inspected_list", oqcInspectedList);

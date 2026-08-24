/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, useState } from "@odoo/owl";

const COMPONENT_TYPE_LABELS = {
    main_pcb: _t("PCBA"),
    comm_module: _t("Module"),
    leadseal: _t("Lead seal"),
};

const RESULT_LABELS = {
    ok: "OK",
    ng: "NG",
    scrap: _t("Scrap"),
    skipped: _t("Skipped"),
};

export class SnTracePage extends Component {
    static template = "sn_wsd_api.TracePage";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            snInput: "",
            committedSn: "",
            identityId: null,
            notFound: false,
            loading: false,
            activeTab: "process",
            treeOpen: true,
            productInfo: null,
            treeChildren: [],
            batch: { rows: [], page: 1, pageSize: 20 },
            processRows: [],
            materialRows: [],
            qualityRows: [],
            repairRows: [],
        });
        this.labels = {
            query: _t("Query"),
            export: _t("Export"),
            snPlaceholder: _t("Enter product SN, press Enter or click Query"),
            productStructure: _t("Product Structure"),
            productInfo: _t("Product Information"),
            sameBatch: _t("Same Batch Products"),
            process: _t("Process"),
            material: _t("Material"),
            quality: _t("Quality"),
            repair: _t("Repair"),
            notFound: _t("SN not found"),
            noData: _t("No data"),
            finished: _t("Yes"),
            unfinished: _t("No"),
            total: _t("Total"),
            rows: _t("rows"),
        };
        this.tabDefs = [
            { key: "process", label: this.labels.process },
            { key: "material", label: this.labels.material },
            { key: "quality", label: this.labels.quality },
            { key: "repair", label: this.labels.repair },
        ];
    }

    // ------------------------------------------------------------------
    // query orchestration: six indexed reads, all in parallel where possible
    // ------------------------------------------------------------------
    async onTrace() {
        const sn = (this.state.snInput || "").trim();
        if (!sn || this.state.loading) {
            return;
        }
        this.state.loading = true;
        this.state.notFound = false;
        this.state.productInfo = null;
        this.state.treeChildren = [];
        this.state.processRows = [];
        this.state.materialRows = [];
        this.state.qualityRows = [];
        this.state.repairRows = [];
        this.state.batch = { rows: [], page: 1, pageSize: 20 };
        this.state.committedSn = "";
        try {
            const identityIds = await this.orm.silent.search(
                "sn.wsd.serial.identity", [["name", "=", sn]], { limit: 1 });
            if (!identityIds.length) {
                this.state.notFound = true;
                return;
            }
            const identityId = identityIds[0];
            this.state.identityId = identityId;
            const history = await this.orm.silent.searchRead(
                "sn.wsd.serial.operation.history",
                [["serial_identity_id", "=", identityId]],
                ["route_operation_id", "workcenter_id", "result", "in_date",
                 "out_date", "mes_order_id", "operator_code"],
                { order: "out_date asc, id asc" });
            if (!history.length) {
                this.state.notFound = true;
                return;
            }
            this.state.committedSn = sn;
            const lastOrder = history[history.length - 1].mes_order_id;
            const [productInfo, tests, components, batch, materials] = await Promise.all([
                this._loadProductInfo(sn, history, lastOrder),
                this.orm.silent.searchRead(
                    "sn.wsd.mes.test.result",
                    [["serial_identity_id", "=", identityId]],
                    ["route_operation_id", "test_time", "equipment_sn", "tooling_sns"],
                    { order: "test_time asc" }),
                this.orm.silent.searchRead(
                    "sn.wsd.meter.component.binding",
                    [["serial_identity_id", "=", identityId], ["state", "=", "active"]],
                    ["component_sn", "component_type"]),
                this._loadBatch(lastOrder[0], identityId),
                this._loadMaterials(identityId),
            ]);
            this.state.productInfo = productInfo;
            this.state.treeChildren = components.map((c) => ({
                sn: c.component_sn,
                type: COMPONENT_TYPE_LABELS[c.component_type] || c.component_type,
                id: c.id,
            }));
            this.state.batch = { ...this.state.batch, rows: batch, page: 1 };
            this.state.processRows = this._buildProcessRows(history, tests, productInfo);
            this.state.materialRows = materials;
            const [quality, repair] = await Promise.all([
                this._loadQuality(identityId),
                this._loadRepair(identityId),
            ]);
            this.state.qualityRows = quality;
            this.state.repairRows = repair;
        } finally {
            this.state.loading = false;
        }
    }

    async _loadProductInfo(sn, history, lastOrder) {
        const orderId = lastOrder && lastOrder[0];
        const order = orderId
            ? await this.orm.silent.read(
                "sn.wsd.mes.order", [orderId],
                ["name", "production_id", "production_line_id", "x_side",
                 "x_mes_route_id"])
            : [];
        const o = order[0] || {};
        const production = o.production_id
            ? (await this.orm.silent.read(
                "mrp.production", [o.production_id[0]],
                ["name", "product_id"]))[0] || {}
            : {};
        const product = production.product_id
            ? (await this.orm.silent.read(
                "product.product", [production.product_id[0]],
                ["default_code"]))[0] || {}
            : {};
        // flow finished (option A): an OK leave on the route's exit operation
        let finished = false;
        if (o.x_mes_route_id) {
            const ops = await this.orm.silent.searchRead(
                "sn.wsd.mes.order.route.operation",
                [["mes_route_id", "=", o.x_mes_route_id[0]]],
                ["x_allow_exit"]);
            const exitOpIds = ops.filter((r) => r.x_allow_exit).map((r) => r.id);
            finished = history.some(
                (h) => h.result === "ok" &&
                    exitOpIds.includes(h.route_operation_id[0]));
        }
        return {
            sn,
            productionName: production.name || "",
            orderName: o.name || "",
            productCode: product.default_code || "",
            line: o.production_line_id ? o.production_line_id[1] : "",
            side: o.x_side || "",
            route: o.x_mes_route_id ? o.x_mes_route_id[1] : "",
            finished,
        };
    }

    async _loadBatch(orderId, currentIdentityId) {
        const result = await this.orm.silent.webReadGroup(
            "sn.wsd.serial.operation.history",
            [["mes_order_id", "=", orderId]],
            ["serial_identity_id"], ["__count"]);
        const groups = (result && result.groups) || [];
        return groups.map((g) => ({
            identityId: g.serial_identity_id[0],
            sn: g.serial_identity_id[1],
            current: g.serial_identity_id[0] === currentIdentityId,
        }));
    }

    async _loadMaterials(identityId) {
        const rows = await this.orm.silent.searchRead(
            "sn.smt.material.consumption",
            [["serial_identity_id", "=", identityId]],
            ["material_sn", "required_item_code", "required_product_id",
             "point_qty", "loadpoint", "device_seq",
             "table_no", "operator_code", "consumed_at", "mes_order_id"],
            { order: "consumed_at asc" });
        const productIds = [...new Set(
            rows.map((r) => r.required_product_id && r.required_product_id[0])
                .filter(Boolean))];
        const products = productIds.length
            ? await this.orm.silent.read(
                "product.product", productIds, ["default_code", "name"])
            : [];
        const productById = Object.fromEntries(
            products.map((p) => [p.id, p]));
        return rows.map((r) => {
            const parts = (r.material_sn || "").split("$");
            const product = r.required_product_id
                && productById[r.required_product_id[0]];
            return {
                materialSn: r.material_sn || "",
                itemCode: r.required_item_code
                    || (product ? product.default_code || "" : ""),
                name: product ? product.name || "" : "",
                spec: "",
                lotDate: /^\d{8}$/.test(parts[2] || "") ? parts[2] : "",
                loadpoint: r.loadpoint || "",
                qty: r.point_qty,
                operator: r.operator_code || "",
                time: r.consumed_at,
                station: r.device_seq && r.table_no ?
                    `DEV${r.device_seq}.${r.table_no}` : "",
                orderId: r.mes_order_id ? r.mes_order_id[0] : false,
                orderName: r.mes_order_id ? r.mes_order_id[1] : "",
            };
        });
    }

    async _loadQuality(identityId) {
        const domain = [
            "|",
            ["evidence_serial_identity_id", "=", identityId],
            ["sample_ids.serial_identity_id", "=", identityId],
        ];
        try {
            const rows = await this.orm.silent.searchRead(
                "sn.wsd.quality.inspection", domain,
                ["name", "inspection_type", "result", "state", "mes_order_id",
                 "create_date", "create_uid", "inspector_id"],
                { order: "create_date desc" });
            return rows.map((r) => ({
                name: r.name,
                type: r.inspection_type || "",
                result: r.result || "",
                state: r.state || "",
                orderName: r.mes_order_id ? r.mes_order_id[1] : "",
                submitTime: r.create_date,
                submitter: r.create_uid ? r.create_uid[1] : "",
                inspector: r.inspector_id ? r.inspector_id[1] : "",
                id: r.id,
            }));
        } catch {
            return [];
        }
    }

    async _loadRepair(identityId) {
        const rows = await this.orm.silent.searchRead(
            "sn.wsd.repair.order",
            [["serial_identity_id", "=", identityId]],
            ["name", "state", "reported_time", "write_date", "repair_method",
             "repair_user_id", "defect_line_ids", "route_operation_id"],
            { order: "reported_time desc" });
        let defectsByOrder = {};
        if (rows.some((r) => r.defect_line_ids.length)) {
            const lines = await this.orm.silent.searchRead(
                "sn.wsd.repair.order.defect.line",
                [["id", "in", rows.flatMap((r) => r.defect_line_ids)]],
                ["repair_order_id", "defect_code_id"]);
            defectsByOrder = lines.reduce((acc, l) => {
                const key = l.repair_order_id[0];
                (acc[key] = acc[key] || []).push(
                    l.defect_code_id ? l.defect_code_id[1] : "");
                return acc;
            }, {});
        }
        return rows.map((r) => ({
            name: r.name,
            state: r.state,
            operation: r.route_operation_id ? r.route_operation_id[1] : "",
            defects: (defectsByOrder[r.id] || []).join(", "),
            method: r.repair_method || "",
            repairer: r.repair_user_id ? r.repair_user_id[1] : "",
            reportTime: r.reported_time,
            doneTime: r.state === "done" ? r.write_date : "",
            id: r.id,
        }));
    }

    _buildProcessRows(history, tests, productInfo) {
        // latest test per operation carries the device/tooling columns
        const testByOp = {};
        for (const t of tests) {
            testByOp[t.route_operation_id ? t.route_operation_id[0] : 0] = t;
        }
        return history.map((h, idx) => {
            const opLabel = h.route_operation_id ? h.route_operation_id[1] : "";
            const sep = opLabel.indexOf(" / ");
            const opCode = sep > 0 ? opLabel.slice(0, sep) : opLabel;
            const opName = sep > 0 ? opLabel.slice(sep + 3) : "";
            const test = testByOp[h.route_operation_id[0]];
            return {
                seq: idx + 1,
                opCode,
                opName,
                workcenter: h.workcenter_id ? h.workcenter_id[1] : "",
                line: productInfo && productInfo.line,
                flag: RESULT_LABELS[h.result] || h.result,
                isNg: h.result === "ng",
                orderName: h.mes_order_id ? h.mes_order_id[1] : "",
                orderId: h.mes_order_id ? h.mes_order_id[0] : false,
                productionName: productInfo && productInfo.productionName,
                productCode: productInfo && productInfo.productCode,
                operator: h.operator_code || "",
                equipment: test ? test.equipment_sn || "" : "",
                tooling: test ? test.tooling_sns || "" : "",
                time: h.out_date,
                opId: h.route_operation_id[0],
            };
        });
    }

    // ------------------------------------------------------------------
    // interactions
    // ------------------------------------------------------------------
    onKeydownInput(ev) {
        if (ev.key === "Enter") {
            this.onTrace();
        }
    }

    setActiveTab(key) {
        this.state.activeTab = key;
    }

    toggleTree() {
        this.state.treeOpen = !this.state.treeOpen;
    }

    get batchPageRows() {
        const b = this.state.batch;
        const start = (b.page - 1) * b.pageSize;
        return b.rows.slice(start, start + b.pageSize);
    }

    get batchPageCount() {
        return Math.max(1, Math.ceil(this.state.batch.rows.length / this.state.batch.pageSize));
    }

    batchPageMove(delta) {
        const b = this.state.batch;
        const page = Math.min(this.batchPageCount, Math.max(1, b.page + delta));
        this.state.batch = { ...b, page };
    }

    switchSn(row) {
        this.state.snInput = row.sn;
        this.onTrace();
    }



    // ------------------------------------------------------------------
    // CSV export of the active tab
    // ------------------------------------------------------------------
    exportCsv() {
        const tabs = {
            process: {
                headers: ["#", "Operation", "Operation Name", "Work Center",
                    "Line", "Flag", "MES Order", "Production", "Product",
                    "Operator", "Device SN", "Tooling", "Time"],
                rows: this.state.processRows.map((r) => [r.seq, r.opCode,
                    r.opName, r.workcenter, r.line, r.flag, r.orderName,
                    r.productionName, r.productCode, r.operator, r.equipment,
                    r.tooling, r.time]),
            },
            material: {
                headers: ["#", "Material SN", "Item Code", "Name", "Spec",
                    "Lot", "Loadpoint", "Qty", "Station", "Operator", "Time",
                    "MES Order"],
                rows: this.state.materialRows.map((r, i) => [i + 1, r.materialSn,
                    r.itemCode, r.name, r.spec, r.lotDate, r.loadpoint, r.qty,
                    r.station, r.operator, r.time, r.orderName]),
            },
            quality: {
                headers: ["#", "Inspection", "Type", "Result", "State",
                    "MES Order", "Submit Time", "Submitter", "Inspector"],
                rows: this.state.qualityRows.map((r, i) => [i + 1, r.name,
                    r.type, r.result, r.state, r.orderName, r.submitTime,
                    r.submitter, r.inspector]),
            },
            repair: {
                headers: ["#", "Repair Order", "State", "Operation",
                    "Defects", "Method", "Repairer", "Report Time", "Done Time"],
                rows: this.state.repairRows.map((r, i) => [i + 1, r.name,
                    r.state, r.operation, r.defects, r.method, r.repairer,
                    r.reportTime, r.doneTime]),
            },
        };
        const def = tabs[this.state.activeTab];
        if (!def || !def.rows.length) {
            return;
        }
        const esc = (v) => {
            const s = String(v ?? "");
            return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        };
        const lines = [def.headers.map(esc).join(",")]
            .concat(def.rows.map((r) => r.map(esc).join(",")));
        const blob = new Blob(["\ufeff" + lines.join("\r\n")],
            { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `trace_${this.state.committedSn}_${this.state.activeTab}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }
}

registry.category("actions").add("sn_wsd_trace_page", SnTracePage);

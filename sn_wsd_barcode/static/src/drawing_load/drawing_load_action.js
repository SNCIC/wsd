/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useBus } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// 投料（插件/装配，无料站表）：选产线 → 选工作中心，工位带出本产线在线
// 制令单与关键物料清单（不扫制令单条码），再循环扫 物料盘号/制具SN/辅料SN
// 上线。换单 = 切工位/产线选择器。换单收尾：[Unload All]（= 制令单批量下料，
// 制具/辅料联动下线）。
export class DrawingLoadAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.DrawingLoadAction";

    setup() {
        this.action = useService("action");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.state = useState({
            command: "",
            lines: [],
            stations: [],
            selectedLineId: false,
            selectedStationId: false,
            selector: false,
            selectorQuery: "",
            productionId: false,
            orderName: "",
            noControl: false,
            summary: {
                required_qty: 0,
                loaded_qty: 0,
                unloaded_qty: 0,
                line_complete: false,
            },
            rows: [],
            result: "",
            resultType: "info",
            loading: false,
        });
        useBus(this.mobileService.bus, "mobile_reader_scanned", (ev) => {
            for (const barcode of ev.detail.data || []) {
                this.onScan(barcode);
            }
        });
        onMounted(async () => {
            this.mobileService.enableReader();
            await this._loadSelectors();
            await this.loadContext();
            this.focusInput();
        });
        onWillUnmount(() => {
            this.mobileService.stopReader();
        });
    }

    async _loadSelectors() {
        const data = await rpc("/sn_wsd_barcode/get_workshop_operation_data");
        this.state.lines = data.lines || [];
        this.state.stations = data.stations || [];
        this.state.selectedLineId = this.state.lines[0]?.id || false;
        this.state.selectedStationId = this.stationsOfLine[0]?.id || false;
    }

    get stationsOfLine() {
        return this.state.stations.filter(
            (station) => !this.state.selectedLineId
                || station.line_id === this.state.selectedLineId);
    }

    get selectedLineName() {
        const line = this.state.lines.find(
            (l) => l.id === this.state.selectedLineId);
        return line ? line.display_name : _t("Line");
    }

    get selectedStationName() {
        const station = this.state.stations.find(
            (s) => s.id === this.state.selectedStationId);
        return station ? station.display_name : _t("Work Center");
    }

    focusInput() {
        setTimeout(() => {
            const input = this.el?.querySelector(".o_sn_wsd_drawing_command");
            if (input) {
                input.focus();
            }
        }, 50);
    }

    get title() {
        return _t("Critical Material Loading");
    }

    get backLabel() {
        return _t("Back");
    }

    get lineLabel() {
        return _t("Line");
    }

    get workCenterLabel() {
        return _t("Work Center");
    }

    get scanHint() {
        if (!this.state.selectedStationId) {
            return _t("Select a work center first.");
        }
        return _t("Scan a material reel, tooling SN or consumable SN.");
    }

    get unloadAllLabel() {
        return _t("Unload All");
    }

    get orderLabel() {
        return _t("Order");
    }

    get requiredLabel() {
        return _t("To Load");
    }

    get loadedLabel() {
        return _t("Loaded");
    }

    get unloadedLabel() {
        return _t("Not Loaded");
    }

    get completeLabel() {
        return _t("All rows loaded. Pass stations are now allowed.");
    }

    get noControlLabel() {
        return _t("No critical material control for the current order.");
    }

    typeLabel(type) {
        if (type === "tooling") {
            return _t("Tooling");
        }
        if (type === "consumable") {
            return _t("Consumable");
        }
        return _t("Material");
    }

    rowClass(row) {
        return row.load_status === "Y" ? "list-group-item text-success" : "list-group-item text-danger";
    }

    goBack() {
        this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_workshop_functions_action");
    }

    openSelector(kind) {
        this.state.selector = kind;
        this.state.selectorQuery = "";
    }

    closeSelector() {
        this.state.selector = false;
        this.state.selectorQuery = "";
        this.focusInput();
    }

    get selectorTitle() {
        return this.state.selector === "line"
            ? _t("Select a production line.")
            : _t("Select a work center.");
    }

    selectLine(line) {
        this.state.selectedLineId = line.id;
        this.state.selectedStationId = this.stationsOfLine[0]?.id || false;
        this.closeSelector();
        this.loadContext();
    }

    selectStation(station) {
        this.state.selectedStationId = station.id;
        this.state.selectedLineId = station.line_id || this.state.selectedLineId;
        this.closeSelector();
        this.loadContext();
    }

    get selectorRecords() {
        const query = this.state.selectorQuery.trim().toLowerCase();
        const records = this.state.selector === "line"
            ? this.state.lines
            : this.stationsOfLine;
        if (!query) {
            return records;
        }
        return records.filter(
            (record) => (record.display_name || record.name || "")
                .toLowerCase().includes(query));
    }

    _applyStatus(status) {
        this.state.orderName = status.mes_order_name || this.state.orderName;
        this.state.summary = status.summary || this.state.summary;
        this.state.rows = status.rows || [];
        if (status.production_id) {
            this.state.productionId = status.production_id;
        }
    }

    // 工位 → 本产线在线制令单 → 该单关键物料清单状态
    async loadContext() {
        if (!this.state.selectedStationId) {
            this.state.productionId = false;
            this.state.rows = [];
            this.state.result = _t("Select a work center first.");
            this.state.resultType = "warning";
            return;
        }
        this.state.loading = true;
        try {
            const status = await rpc("/sn_wsd_barcode/smt/do_drawing_context", {
                workcenter_id: this.state.selectedStationId,
            });
            if (status.ok) {
                this._applyStatus(status);
                this.state.noControl = !this.state.rows.length;
                if (this.state.rows.length) {
                    this.state.result = _t(
                        "Order %s. Scan the materials to load.",
                        this.state.orderName);
                    this.state.resultType = "success";
                } else {
                    this.state.result = this.noControlLabel;
                    this.state.resultType = "warning";
                }
            } else {
                this.state.productionId = false;
                this.state.rows = [];
                this.state.result = status.message || _t("Operation failed.");
                this.state.resultType = "danger";
            }
        } catch (error) {
            this.state.result = error.message || _t("Operation failed.");
            this.state.resultType = "danger";
        } finally {
            this.state.loading = false;
        }
    }

    async onScan(barcode) {
        const code = String(barcode || "").trim();
        if (!code || this.state.loading || this.state.selector) {
            return;
        }
        if (!this.state.productionId) {
            this.state.result = _t("Select a work center first.");
            this.state.resultType = "warning";
            return;
        }
        this.state.loading = true;
        try {
            const status = await rpc("/sn_wsd_barcode/smt/do_drawing_scan", {
                production_id: this.state.productionId,
                barcode: code,
            });
            this._applyStatus(status);
            this.state.result = status.message || "";
            this.state.resultType = status.ok ? "success" : "danger";
            this.state.command = "";
        } catch (error) {
            this.state.result = error.message || _t("Operation failed.");
            this.state.resultType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    async onSubmit(ev) {
        if (ev) {
            ev.preventDefault();
        }
        const code = this.state.command.trim();
        if (!code) {
            return;
        }
        await this.onScan(code);
    }

    async unloadAll() {
        if (!this.state.productionId || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            const status = await rpc("/sn_wsd_barcode/smt/do_drawing_unload_all", {
                production_id: this.state.productionId,
            });
            this._applyStatus(status);
            this.state.result = status.message || "";
            this.state.resultType = status.ok ? "success" : "danger";
        } catch (error) {
            this.state.result = error.message || _t("Operation failed.");
            this.state.resultType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }
}

registry.category("actions").add("sn_wsd_barcode_drawing_load", DrawingLoadAction);

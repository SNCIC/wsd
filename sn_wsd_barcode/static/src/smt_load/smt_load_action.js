/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useState } from "@odoo/owl";

export class SmtLoadAction extends Component {
    static template = "sn_wsd_barcode.SmtLoadAction";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            stations: [],
            selectedStationId: false,
            productionId: false,
            productionName: "",
            mesOrderName: "",
            summary: null,
            rows: [],
            activeRow: false,
            step: 0,
            result: "",
            resultType: "info",
            pendingFeeder: false,
            busy: false,
        });
        this.labels = {
            back: _t("Back"),
            station: _t("Work Center"),
            load: _t("Load"),
            cartLoad: _t("Cart Load"),
            offlinePrepare: _t("Offline Prepare"),
            unload: _t("Unload"),
            changeover: _t("Changeover"),
            scan: _t("Scan"),
            hintStep0: _t("Scan a loadpoint like 3.Table1"),
            hintStep1: _t("Scan the material reel SN"),
            loaded: _t("Loaded"),
            notLoaded: _t("Not loaded"),
        };
        onWillStart(() => this.loadData());
    }

    async loadData() {
        const data = await rpc("/sn_wsd_barcode/get_workshop_operation_data");
        if (data.ok === false) {
            this.setResult(data.message, "danger");
            return;
        }
        this.state.stations = data.stations || [];
        this.state.selectedStationId = this.state.stations[0]?.id || false;
        if (this.state.selectedStationId) {
            await this.loadContext();
        }
    }

    async loadContext() {
        try {
            const ctx = await rpc("/sn_wsd_barcode/smt/get_production_context", {
                workcenter_id: this.state.selectedStationId,
            });
            this.state.productionId = ctx.production_id;
            this.state.productionName = ctx.production_name;
            this.state.mesOrderName = ctx.mes_order_name;
            await this.loadRows();
        } catch (error) {
            this.state.productionId = false;
            this.state.rows = [];
            this.setResult(error.message || _t("No online production order."), "danger");
        }
    }

    async loadRows() {
        if (!this.state.productionId) {
            this.state.rows = [];
            return;
        }
        const status = await rpc("/sn_wsd_barcode/smt/get_material_table_status", {
            production_id: this.state.productionId,
        });
        this.state.summary = status.summary || null;
        this.state.rows = status.rows || [];
        this.state.activeRow = false;
        this.state.step = 0;
    }

    setResult(message, type) {
        this.state.result = message;
        this.state.resultType = type || "info";
    }

    async onStationChange(ev) {
        this.state.selectedStationId = Number(ev.target.value);
        this.setResult("", "info");
        await this.loadContext();
    }

    rowKey(row) {
        return `${row.device_seq}.${row.table_no}`;
    }

    async onScan(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const value = ev.target.value.trim();
        ev.target.value = "";
        if (!value) {
            return;
        }
        if (this.state.step === 0) {
            const row = this.state.rows.find((r) => this.rowKey(r) === value);
            if (!row) {
                this.setResult(_t("Loadpoint %s not found in the material table.", value), "danger");
                return;
            }
            this.state.activeRow = row;
            this.state.step = 1;
            this.setResult(this.labels.hintStep1, "info");
        } else {
            await this.doLoad(value);
        }
    }

    async doLoad(materialSn) {
        const row = this.state.activeRow;
        if (!row) {
            return;
        }
        this.state.busy = true;
        try {
            const res = await rpc("/sn_wsd_barcode/smt/do_online_load", {
                production_id: this.state.productionId,
                workcenter_id: this.state.selectedStationId,
                device_table_input: this.rowKey(row),
                loadpoint_input: row.loadpoint || "",
                material_sn_input: materialSn,
            });
            this.setResult(res.message || "", res.ok ? "success" : "danger");
            if (res.ok) {
                await this.loadRows();
            }
        } finally {
            this.state.busy = false;
        }
    }

    async simpleAction(kind, extra = {}) {
        this.state.busy = true;
        try {
            let res;
            if (kind === "cart_load") {
                const cart = prompt(_t("Scan or enter the cart SN"));
                if (!cart) {
                    return;
                }
                res = await rpc("/sn_wsd_barcode/smt/do_cart_load", {
                    production_id: this.state.productionId,
                    workcenter_id: this.state.selectedStationId,
                    device_table_input: "",
                    cart_sn_input: cart,
                });
            } else if (kind === "offline_prepare") {
                const table = prompt(_t("Scan the device table, e.g. 3.Table1"));
                if (!table) {
                    return;
                }
                res = await rpc("/sn_wsd_barcode/smt/do_offline_prepare", {
                    production_id: this.state.productionId,
                    workcenter_id: this.state.selectedStationId,
                    device_table_input: table,
                    loadpoint_input: "",
                    material_sn_input: "",
                });
            } else if (kind === "unload") {
                const table = prompt(_t("Scan the device table to unload, e.g. 3.Table1"));
                if (!table) {
                    return;
                }
                res = await rpc("/sn_wsd_barcode/smt/do_unload", {
                    production_id: this.state.productionId,
                    workcenter_id: this.state.selectedStationId,
                    unload_scope: "single",
                    device_table_input: table,
                });
            } else if (kind === "changeover") {
                const targetName = prompt(_t("Enter the target production order name"));
                if (!targetName) {
                    return;
                }
                const ids = await this.orm.search("mrp.production", [["name", "=", targetName]], { limit: 1 });
                if (!ids.length) {
                    this.setResult(_t("Production order %s not found.", targetName), "danger");
                    return;
                }
                res = await rpc("/sn_wsd_barcode/smt/do_changeover", {
                    production_id: this.state.productionId,
                    target_production_id: ids[0],
                    workcenter_id: this.state.selectedStationId,
                });
            }
            if (res) {
                this.setResult(res.message || "", res.ok ? "success" : "danger");
                if (res.ok) {
                    await this.loadContext();
                }
            }
        } finally {
            this.state.busy = false;
        }
    }

    goBack() {
        this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_action_main_menu");
    }
}

registry.category("actions").add("sn_wsd_barcode_smt_load_action", SmtLoadAction);

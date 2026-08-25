/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useBus } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// 投料（插件/装配，无料站表）：扫制令单定位 → 清单行视图（未上标红）
// → 循环扫 物料盘号/制具SN/辅料SN 上线 → 全部 is_load=Y 后过站放行。
// 换单收尾：[Unload All]（= 制令单批量下料，制具/辅料联动下线）。
export class DrawingLoadAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.DrawingLoadAction";

    setup() {
        this.action = useService("action");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.state = useState({
            command: "",
            productionId: false,
            orderName: "",
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
        onMounted(() => {
            this.mobileService.enableReader();
            this.focusInput();
        });
        onWillUnmount(() => {
            this.mobileService.stopReader();
        });
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

    get scanHint() {
        return this.state.productionId
            ? _t("Scan a material reel, tooling SN or consumable SN.")
            : _t("Scan the production order barcode.");
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
        this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_action_main_menu");
    }

    resetOrder() {
        this.state.productionId = false;
        this.state.orderName = "";
        this.state.rows = [];
        this.state.summary = {
            required_qty: 0,
            loaded_qty: 0,
            unloaded_qty: 0,
            line_complete: false,
        };
        this.state.result = "";
        this.state.resultType = "info";
        this.focusInput();
    }

    _applyStatus(status) {
        this.state.orderName = status.mes_order_name || this.state.orderName;
        this.state.summary = status.summary || this.state.summary;
        this.state.rows = status.rows || [];
        if (status.production_id) {
            this.state.productionId = status.production_id;
        }
    }

    async onScan(barcode) {
        const code = String(barcode || "").trim();
        if (!code || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            if (!this.state.productionId) {
                const status = await rpc("/sn_wsd_barcode/smt/do_drawing_open", {
                    barcode: code,
                });
                if (status.ok) {
                    this._applyStatus(status);
                    this.state.result = _t(
                        "Order %s. Scan the materials to load.",
                        this.state.orderName);
                    this.state.resultType = "success";
                } else {
                    this.state.result = status.message || _t("Operation failed.");
                    this.state.resultType = "danger";
                }
            } else {
                const status = await rpc("/sn_wsd_barcode/smt/do_drawing_scan", {
                    production_id: this.state.productionId,
                    barcode: code,
                });
                this._applyStatus(status);
                this.state.result = status.message || "";
                this.state.resultType = status.ok ? "success" : "danger";
            }
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

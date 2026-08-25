/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// 托屏双模式：
//   [托盘绑定] 扫托盘→循环扫箱；同箱二连扫=解绑（本托）/换绑（他托）
//   [托盘入库] 扫已关闭托盘攒车 → [开单入库] 按制令单开 WH/FR 入库单
export class PalletBindingAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.PalletBindingAction";

    setup() {
        this.action = useService("action");
        this.barcodeService = useService("barcode");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.inputRef = useRef("scanInput");
        this.state = useState({
            mode: "bind",
            palletNo: "",
            command: "",
            message: "",
            messageType: "info",
            cartonCount: 0,
            meterCount: 0,
            lastCartonNo: "",
            lastAction: "",
            receiveList: [],
            loading: false,
        });
        useBus(this.barcodeService.bus, "barcode_scanned", (event) => {
            this.processBarcode(event.detail.barcode);
        });
        useBus(this.mobileService.bus, "mobile_reader_scanned", (event) => {
            for (const code of event.detail.data || []) {
                this.processBarcode(code);
            }
        });
        onMounted(() => {
            this.mobileService.enableReader();
            this.focusInput();
            this.state.message = _t("Scan a pallet number.");
        });
        onWillUnmount(() => {
            this.mobileService.stopReader();
        });
    }

    get title() {
        return _t("Pallet Binding");
    }

    get backLabel() {
        return _t("Back");
    }

    get bindTabLabel() {
        return _t("Bind");
    }

    get receiveTabLabel() {
        return _t("Receive");
    }

    get cartonLabel() {
        return _t("Cartons");
    }

    get meterLabel() {
        return _t("Meters");
    }

    get palletLabel() {
        return _t("Pallets");
    }

    get currentPalletLabel() {
        return _t("Current Pallet");
    }

    get switchPalletLabel() {
        return _t("Switch Pallet");
    }

    get closePalletLabel() {
        return _t("Close Pallet");
    }

    get clearLabel() {
        return _t("Clear");
    }

    get receiveConfirmLabel() {
        return _t("Create Receipt");
    }

    get emptyReceiveLabel() {
        return _t("No pallet in the receipt list yet.");
    }

    get scanHint() {
        if (this.state.mode === "receive") {
            return _t("Scan a closed pallet.");
        }
        return this.state.palletNo
            ? _t("Scan a meter carton. Scan again to unbind/move.")
            : _t("Scan a pallet number.");
    }

    focusInput() {
        setTimeout(() => this.inputRef.el?.focus(), 0);
    }

    goBack() {
        this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_workshop_functions_action");
    }

    switchMode(mode) {
        this.state.mode = mode;
        this.state.command = "";
        this.state.lastCartonNo = "";
        this.state.lastAction = "";
        this.state.message = mode === "bind"
            ? (this.state.palletNo ? _t("Scan a meter carton.") : _t("Scan a pallet number."))
            : _t("Scan a closed pallet to add it to the receipt.");
        this.state.messageType = "info";
        if (mode === "receive") {
            this.state.palletNo = "";
            this.state.cartonCount = 0;
            this.state.meterCount = 0;
        }
        this.focusInput();
    }

    submitCommand(event) {
        event.preventDefault();
        const barcode = this.state.command.trim();
        this.state.command = "";
        if (barcode) {
            this.processBarcode(barcode);
        }
    }

    async processBarcode(rawBarcode) {
        const barcode = (rawBarcode || "").trim();
        if (!barcode || this.state.loading) {
            return;
        }
        if (this.state.mode === "receive") {
            await this.processReceiveScan(barcode);
        } else {
            await this.processBindScan(barcode);
        }
    }

    async processBindScan(barcode) {
        if (!this.state.palletNo) {
            this.state.palletNo = barcode;
            this.state.message = _t("Pallet recorded. Scan a meter carton.");
            this.state.messageType = "success";
            this.focusInput();
            return;
        }
        this.state.loading = true;
        this.state.command = "";
        try {
            // 同码二连扫 → 执行待确认动作（解绑/换绑）
            let action = "bind";
            if (this.state.lastCartonNo === barcode && this.state.lastAction) {
                action = this.state.lastAction;
            }
            const endpoint = action === "unbind" ? "/sn_wsd_barcode/pallet/unbind"
                : action === "move" ? "/sn_wsd_barcode/pallet/move"
                : "/sn_wsd_barcode/pallet/bind_carton";
            const result = await rpc(endpoint, {
                pallet_no: this.state.palletNo,
                carton_no: barcode,
            });
            this.state.lastCartonNo = "";
            this.state.lastAction = "";
            if (result.ok) {
                this.applyPalletCounts(result);
                if (result.confirm_unbind) {
                    this.state.lastCartonNo = barcode;
                    this.state.lastAction = "unbind";
                    this.state.message = result.message;
                    this.state.messageType = "warning";
                } else if (result.confirm_move) {
                    this.state.lastCartonNo = barcode;
                    this.state.lastAction = "move";
                    this.state.message = result.message;
                    this.state.messageType = "warning";
                } else if (result.unbound) {
                    this.state.message = _t("Carton %s unbound from pallet %s.",
                        barcode, this.state.palletNo);
                    this.state.messageType = "success";
                } else if (result.moved) {
                    this.state.message = _t("Carton %s moved from pallet %s to %s.",
                        barcode, result.moved_from, this.state.palletNo);
                    this.state.messageType = "success";
                } else {
                    this.state.message = _t("Carton bound. Scan the next meter carton.");
                    this.state.messageType = "success";
                }
            } else {
                this.state.message = result.message || _t("Carton binding failed.");
                this.state.messageType = "danger";
            }
        } catch (error) {
            this.state.message = error.message || _t("Operation failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    applyPalletCounts(result) {
        this.state.cartonCount = result.carton_count ?? this.state.cartonCount;
        this.state.meterCount = result.meter_count ?? this.state.meterCount;
    }

    resetPallet() {
        this.state.palletNo = "";
        this.state.cartonCount = 0;
        this.state.meterCount = 0;
        this.state.lastCartonNo = "";
        this.state.lastAction = "";
        this.state.message = _t("Scan a pallet number.");
        this.state.messageType = "info";
        this.focusInput();
    }

    async closePallet() {
        if (!this.state.palletNo || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            const result = await rpc("/sn_wsd_barcode/pallet/close", {
                pallet_no: this.state.palletNo,
            });
            if (!result.ok) {
                this.state.message = result.message || _t("Pallet closing failed.");
                this.state.messageType = "danger";
                return;
            }
            this.state.message = _t("Pallet %s closed. Ready for receipt.", this.state.palletNo);
            this.state.messageType = "success";
            this.state.palletNo = "";
            this.state.cartonCount = 0;
            this.state.meterCount = 0;
        } catch (error) {
            this.state.message = error.message || _t("Pallet closing failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    async processReceiveScan(barcode) {
        if (this.state.receiveList.some((item) => item.pallet_no === barcode)) {
            this.state.message = _t("Pallet %s is already in the receipt list.", barcode);
            this.state.messageType = "warning";
            this.focusInput();
            return;
        }
        this.state.loading = true;
        this.state.command = "";
        try {
            const result = await rpc("/sn_wsd_barcode/pallet/receive", {
                pallet_nos: [barcode],
                dry_run: true,
            });
            if (result.ok) {
                this.state.receiveList.push({
                    pallet_no: barcode,
                    carton_count: result.pallets?.[0]?.carton_count || 0,
                    meter_count: result.pallets?.[0]?.meter_count || 0,
                });
                this.state.message = _t("Pallet %s added. Scan the next pallet or press [Receive].", barcode);
                this.state.messageType = "success";
            } else {
                this.state.message = result.message || _t("Pallet validation failed.");
                this.state.messageType = "danger";
            }
        } catch (error) {
            this.state.message = error.message || _t("Operation failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    get receiveTotals() {
        return {
            pallets: this.state.receiveList.length,
            cartons: this.state.receiveList.reduce((sum, item) => sum + item.carton_count, 0),
            meters: this.state.receiveList.reduce((sum, item) => sum + item.meter_count, 0),
        };
    }

    removePallet(palletNo) {
        this.state.receiveList = this.state.receiveList.filter(
            (item) => item.pallet_no !== palletNo);
    }

    async confirmReceive() {
        if (!this.state.receiveList.length || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            const result = await rpc("/sn_wsd_barcode/pallet/receive", {
                pallet_nos: this.state.receiveList.map((item) => item.pallet_no),
            });
            if (result.ok) {
                const lines = result.receipts.map(
                    (r) => `${r.picking} (${r.order} x${r.qty})`).join(" | ");
                this.state.message = _t("Receipts created: %s", lines);
                this.state.messageType = "success";
                this.state.receiveList = [];
            } else {
                this.state.message = result.message || _t("Receipt creation failed.");
                this.state.messageType = "danger";
            }
        } catch (error) {
            this.state.message = error.message || _t("Receipt creation failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }
}

registry.category("actions").add("sn_wsd_barcode_pallet_binding", PalletBindingAction);

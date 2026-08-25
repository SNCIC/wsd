import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component, useRef, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";


export class PalletBindingAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.PalletBindingAction";

    setup() {
        this.action = useService("action");
        this.barcodeService = useService("barcode");
        this.inputRef = useRef("scanInput");
        this.state = useState({
            palletNo: "",
            command: "",
            message: _t("Scan a pallet number."),
            messageType: "info",
            cartonCount: 0,
            meterCount: 0,
            lastCartonNo: "",
            loading: false,
        });
        useBus(this.barcodeService.bus, "barcode_scanned", (event) => {
            this.processBarcode(event.detail.barcode);
        });
    }

    get messageClass() {
        return `alert-${this.state.messageType}`;
    }

    focusInput() {
        setTimeout(() => this.inputRef.el?.focus(), 0);
    }

    goBack() {
        if (this.env.config.breadcrumbs.length > 1) {
            this.env.config.historyBack();
        } else {
            this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_workshop_functions_action");
        }
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
        if (!this.state.palletNo) {
            this.state.palletNo = barcode;
            this.state.message = _t("Pallet recorded. Scan a meter carton.");
            this.state.messageType = "success";
            this.focusInput();
            return;
        }
        this.state.loading = true;
        try {
            const result = await rpc("/sn_wsd_barcode/pallet/bind_carton", {
                pallet_no: this.state.palletNo,
                carton_no: barcode,
            });
            if (result.ok) {
                this.state.lastCartonNo = result.carton_no;
                this.state.cartonCount = result.carton_count;
                this.state.meterCount = result.meter_count;
                this.state.message = result.duplicated
                    ? _t("This carton is already bound to the current pallet.")
                    : _t("Carton bound. Scan the next meter carton.");
                this.state.messageType = result.duplicated ? "warning" : "success";
            } else {
                this.state.message = result.message || _t("Carton binding failed.");
                this.state.messageType = "danger";
            }
        } catch (error) {
            this.state.message = error.message || _t("Carton binding failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    resetPallet() {
        this.state.palletNo = "";
        this.state.lastCartonNo = "";
        this.state.cartonCount = 0;
        this.state.meterCount = 0;
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
            this.state.message = _t("Pallet closed successfully.");
            this.state.messageType = "success";
            this.state.cartonCount = result.carton_count;
            this.state.meterCount = result.meter_count;
            this.state.palletNo = "";
        } catch (error) {
            this.state.message = error.message || _t("Pallet closing failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }
}

registry.category("actions").add("sn_wsd_barcode_pallet_binding", PalletBindingAction);

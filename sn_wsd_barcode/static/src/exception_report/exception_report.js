/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useBus } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// 异常上报（全员）：第1扫 SN → 第2扫缺陷代码 → 生成质量问题单。
// 备注输入框可选，提交后停在缺陷码步继续报下一处。
export class ExceptionReportAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.ExceptionReportAction";

    setup() {
        this.action = useService("action");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.state = useState({
            command: "",
            note: "",
            serialSn: "",
            serialId: false,
            result: "",
            resultType: "info",
            loading: false,
        userName: "",
        });
        useBus(this.mobileService.bus, "mobile_reader_scanned", (ev) => {
            for (const barcode of ev.detail.data || []) {
                this.onScan(barcode);
            }
        });
        onMounted(() => {
            this.mobileService.enableReader();
            this._loadUserInfo();
            this.focusInput();
        });
        onWillUnmount(() => {
            this.mobileService.stopReader();
        });
    }

    async _loadUserInfo() {
        try {
            const data = await rpc("/sn_wsd_barcode/get_workshop_operation_data");
            this.state.userName = data.user_name || "";
        } catch (error) { /* non-critical */ }
    }

    focusInput() {
        setTimeout(() => {
            const input = this.el?.querySelector(".o_sn_wsd_exception_command");
            if (input) {
                input.focus();
            }
        }, 50);
    }

    get title() {
        return _t("Exception Report");
    }

    get backLabel() {
        return _t("Back");
    }

    get scanHint() {
        return this.state.serialId
            ? _t("Scan the defect code.")
            : _t("Scan the product SN.");
    }

    get resetLabel() {
        return _t("Reset");
    }

    get noteLabel() {
        return _t("Note (optional)");
    }

    get snLabel() {
        return _t("SN");
    }

    goBack() {
        if (this.env.config.breadcrumbs.length > 1) {
            this.env.config.historyBack();
        } else {
            this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_action_main_menu");
        }
    }

    async onScan(barcode) {
        const code = String(barcode || "").trim();
        if (!code || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            if (!this.state.serialId) {
                const res = await rpc("/sn_wsd_barcode/quality/resolve_exception_sn", {
                    sn: code,
                });
                this.state.serialId = res.serial_id;
                this.state.serialSn = res.serial_sn;
                this.state.result = _t("SN %s. Scan the defect code.", res.serial_sn);
                this.state.resultType = "success";
            } else {
                const res = await rpc("/sn_wsd_barcode/quality/report_exception", {
                    serial_id: this.state.serialId,
                    defect_input: code,
                    note: this.state.note,
                });
                this.state.result = res.message || _t("Exception reported.");
                this.state.resultType = "success";
                this.state.serialId = false;
                this.state.serialSn = "";
                this.state.note = "";
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

    resetSerial() {
        this.state.serialId = false;
        this.state.serialSn = "";
        this.state.result = "";
        this.focusInput();
    }
}

registry.category("actions").add("sn_wsd_barcode_exception_report", ExceptionReportAction);

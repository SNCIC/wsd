/** @odoo-module */

import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const SERIAL_FORM_TEMPLATE = {
    report_type: "complete",
    operator_code: "",
    serial_no: "",
    remark: "",
    override_route: false,
    seal_no: "",
    carton_no: "",
    pallet_no: "",
    aging_batch_id: "",
    aging_slot_no: "",
};

const QTY_FORM_TEMPLATE = {
    mode: "manual",
    report_type: "complete",
    operator_code: "",
    external_event_id: "",
    qty_in: 0,
    qty_ok: 0,
    qty_ng: 0,
    qty_scrap: 0,
    qty_repair: 0,
    qty_rework: 0,
    remark: "",
};

export class SnWsdTerminalClientAction extends Component {
    static template = "sn_wsd_report.TerminalClientAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.serialInputRef = useRef("serialInput");
        this.qtyInputRef = useRef("qtyInput");
        this.state = useState({
            loading: true,
            submitting: false,
            activeMode: this.props.action.context.default_serial_no ? "serial" : "qty",
            successFlash: "",
            dashboard: null,
            lastSubmittedReportId: false,
            serialForm: {
                ...SERIAL_FORM_TEMPLATE,
                report_type: this.props.action.context.default_report_type || "complete",
                operator_code: this.props.action.context.default_operator_code || "",
                serial_no: this.props.action.context.default_serial_no || "",
                remark: this.props.action.context.default_remark || "",
            },
            qtyForm: {
                ...QTY_FORM_TEMPLATE,
                mode: this.props.action.context.default_mode || "manual",
                report_type: this.props.action.context.default_report_type || "complete",
                operator_code: this.props.action.context.default_operator_code || "",
                qty_in: this.props.action.context.default_qty_in || 0,
            },
        });
        onWillStart(async () => {
            await this.loadDashboard();
        });
        onMounted(() => {
            this.focusPrimaryInput();
        });
    }

    get workorderId() {
        return this.props.action.context.default_workorder_id;
    }

    get stationTitle() {
        if (!this.state.dashboard) {
            return "";
        }
        return `${this.state.dashboard.station_name || ""} ${this.state.dashboard.station_code ? `(${this.state.dashboard.station_code})` : ""}`.trim();
    }

    get serialOutputQty() {
        return this.state.serialForm.report_type === "complete" && this.state.serialForm.serial_no ? 1 : 0;
    }

    get qtyOutputQty() {
        const form = this.state.qtyForm;
        return Number(form.qty_ok || 0) + Number(form.qty_ng || 0) + Number(form.qty_scrap || 0) + Number(form.qty_repair || 0);
    }

    get qtyConflictMessage() {
        const form = this.state.qtyForm;
        if (form.mode === "machine" && !form.external_event_id) {
            return "Machine mode requires an external event ID.";
        }
        if (form.qty_rework && (form.qty_ok || form.qty_ng || form.qty_scrap || form.qty_repair)) {
            return "Rework quantity must be submitted separately from output quantities.";
        }
        if (this.qtyOutputQty > Number(form.qty_in || 0)) {
            return "Output total cannot exceed input quantity.";
        }
        return "";
    }

    get serialConflictMessage() {
        if (!this.state.serialForm.serial_no) {
            return "Please enter an SN or barcode.";
        }
        return "";
    }

    async loadDashboard() {
        this.state.loading = true;
        this.state.dashboard = await this.orm.call("mrp.workorder", "get_terminal_dashboard_data", [[this.workorderId]]);
        this.state.loading = false;
    }

    switchMode(mode) {
        this.state.activeMode = mode;
        this.state.successFlash = "";
        this.focusPrimaryInput();
    }

    focusPrimaryInput() {
        const target = this.state.activeMode === "serial" ? this.serialInputRef.el : this.qtyInputRef.el;
        if (target) {
            target.focus();
            if (target.select) {
                target.select();
            }
        }
    }

    setSerialValue(ev) {
        const field = ev.target.name;
        this.state.serialForm[field] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
    }

    setQtyValue(ev) {
        const field = ev.target.name;
        const inputType = ev.target.type;
        if (inputType === "checkbox") {
            this.state.qtyForm[field] = ev.target.checked;
            return;
        }
        const value = ev.target.value;
        if (["qty_in", "qty_ok", "qty_ng", "qty_scrap", "qty_repair", "qty_rework"].includes(field)) {
            this.state.qtyForm[field] = Number(value || 0);
            return;
        }
        this.state.qtyForm[field] = value;
    }

    onKeydownSubmit(ev, mode) {
        if (ev.key !== "Enter") {
            return;
        }
        const tagName = ev.target.tagName;
        if (tagName === "TEXTAREA") {
            return;
        }
        ev.preventDefault();
        if (mode === "serial") {
            this.submitSerial();
        } else {
            this.submitQty();
        }
    }

    async submitSerial(ev) {
        if (ev) {
            ev.preventDefault();
        }
        if (this.serialConflictMessage) {
            this.notification.add(this.serialConflictMessage, { type: "warning" });
            this.focusPrimaryInput();
            return;
        }
        await this.submitPayload(
            {
                mode: "manual",
                report_type: this.state.serialForm.report_type,
                operator_code: this.state.serialForm.operator_code,
                serial_no: this.state.serialForm.serial_no,
                remark: this.state.serialForm.remark,
                override_route: this.state.serialForm.override_route,
                seal_no: this.state.serialForm.seal_no,
                carton_no: this.state.serialForm.carton_no,
                pallet_no: this.state.serialForm.pallet_no,
                aging_batch_id: this.state.serialForm.aging_batch_id || false,
                aging_slot_no: this.state.serialForm.aging_slot_no,
                qty_in: 1,
                qty_ok: this.state.serialForm.report_type === "complete" ? 1 : 0,
            },
            "Serial report submitted.",
            "serial"
        );
    }

    async submitQty(ev) {
        if (ev) {
            ev.preventDefault();
        }
        if (this.qtyConflictMessage) {
            this.notification.add(this.qtyConflictMessage, { type: "warning" });
            this.focusPrimaryInput();
            return;
        }
        await this.submitPayload({ ...this.state.qtyForm }, "Quantity report submitted.", "qty");
    }

    async submitPayload(payload, successMessage, mode) {
        try {
            this.state.submitting = true;
            this.state.dashboard = await this.orm.call("mrp.workorder", "action_submit_terminal_payload", [[this.workorderId], payload]);
            const reports = this.state.dashboard?.recent_reports || [];
            this.state.lastSubmittedReportId = reports.length ? reports[0].id : false;
            this.state.successFlash = successMessage;
            this.notification.add(successMessage, { type: "success" });
            if (mode === "serial") {
                this.state.serialForm = {
                    ...SERIAL_FORM_TEMPLATE,
                    report_type: this.state.serialForm.report_type,
                    operator_code: this.state.serialForm.operator_code,
                };
                this.state.activeMode = "serial";
            } else {
                this.state.qtyForm = {
                    ...QTY_FORM_TEMPLATE,
                    mode: this.state.qtyForm.mode,
                    report_type: this.state.qtyForm.report_type,
                    operator_code: this.state.qtyForm.operator_code,
                };
                this.state.activeMode = "qty";
            }
        } catch (error) {
            this.notification.add(error.message || "Report submission failed.", { type: "danger" });
        } finally {
            this.state.submitting = false;
            this.focusPrimaryInput();
        }
    }

    openReports() {
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Workorder Reports",
            res_model: "mrp.workorder.report",
            view_mode: "list,form,pivot,graph",
            domain: [["workorder_id", "=", this.workorderId]],
        });
    }

    recentRowClass(report) {
        if (report.id === this.state.lastSubmittedReportId) {
            return "o_is_recent_highlight";
        }
        if (report.qty_scrap) {
            return "o_is_scrap";
        }
        if (report.qty_ng) {
            return "o_is_ng";
        }
        if (report.qty_rework || report.qty_repair) {
            return "o_is_rework";
        }
        return "";
    }
}

registry.category("actions").add("sn_wsd_terminal_client_action", SnWsdTerminalClientAction);

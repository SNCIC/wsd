/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, onWillStart, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const PHOTO_MAX_EDGE = 1280;

// Exception reporting (everyone): pick a work center, the line context and
// root categories come from the exception terminal service. Reporting is
// one root category + a one-line description + an optional photo. Instead
// of a ticket-number list, the screen carries the reporter's own closure
// confirmations: cards with confirm / reject (note required), shown only
// while the current user has tickets awaiting their confirmation.
export class ExceptionReportAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.ExceptionReportAction";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({
            workcenters: [],
            lines: [],
            selectedLineId: false,
            selectedWorkcenterId: false,
            lineId: false,
            lineName: "",
            categories: [],
            pendingConfirms: [],
            categoryId: null,
            note: "",
            photoBase64: false,
            selector: false, // 'line' | 'workcenter'
            result: "",
            resultType: "info",
            loading: false,
            userName: "",
        });
        onWillStart(() => this.loadWorkcenters(false));
        onMounted(() => {
            this._loadUserInfo();
        });
    }

    async _loadUserInfo() {
        try {
            const data = await rpc("/sn_wsd_barcode/get_workshop_operation_data");
            this.state.userName = data.user_name || "";
        } catch (error) { /* non-critical */ }
    }

    get title() {
        return _t("Exception Report");
    }

    get backLabel() {
        return _t("Back");
    }

    get productionLineLabel() {
        return _t("Production Line");
    }

    get workCenterLabel() {
        return _t("Work Center");
    }

    get pendingTitleLabel() {
        return _t("Awaiting your confirmation");
    }

    get confirmCardLabel() {
        return _t("Confirm closure");
    }

    get rejectLabel() {
        return _t("Reject closure");
    }

    get rejectNoteLabel() {
        return _t("Rejection note");
    }

    get submitRejectLabel() {
        return _t("Submit");
    }

    get cancelLabel() {
        return _t("Cancel");
    }

    get noteLabel() {
        return _t("Description");
    }

    get notePlaceholder() {
        return _t("One line: what happened on the line?");
    }

    get photoLabel() {
        return _t("Photo");
    }

    get retakePhotoLabel() {
        return _t("Retake photo");
    }

    get submitLabel() {
        return _t("Report Exception");
    }

    get categoryRequiredMsg() {
        return _t("Select a category first.");
    }

    get selectedLineName() {
        const line = this.state.lines.find(
            (l) => l.id === this.state.selectedLineId);
        return line ? line.name : "";
    }

    get selectedWorkcenterLabel() {
        const wc = this.state.workcenters.find(
            (w) => w.id === this.state.selectedWorkcenterId);
        return wc ? wc.label : "";
    }

    get selectorRecords() {
        if (this.state.selector === "line") {
            return this.state.lines.map((l) => ({ id: l.id, name: l.name }));
        }
        return this.state.workcenters
            .filter((w) => !this.state.selectedLineId
                || w.line_id === this.state.selectedLineId)
            .map((w) => ({ id: w.id, name: w.label }));
    }

    goBack() {
        if (this.env.config.breadcrumbs.length > 1) {
            this.env.config.historyBack();
        } else {
            this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_action_main_menu");
        }
    }

    async loadWorkcenters(workcenterId) {
        this.state.loading = true;
        try {
            const data = await this.orm.silent.call(
                "sn.wsd.mes.order", "sn_station_floor_data", [workcenterId || false]);
            this.state.workcenters = data.workcenters || [];
            const lines = [];
            for (const wc of this.state.workcenters) {
                if (wc.line_id && !lines.some((l) => l.id === wc.line_id)) {
                    lines.push({ id: wc.line_id, name: wc.line_name });
                }
            }
            this.state.lines = lines;
            this.state.selectedWorkcenterId = (data.workcenter || {}).id || false;
            const wc = this.state.workcenters.find(
                (w) => w.id === this.state.selectedWorkcenterId);
            this.state.selectedLineId = (wc && wc.line_id) || false;
            await this._loadExceptionContext();
        } catch (error) {
            this._error(error);
        } finally {
            this.state.loading = false;
        }
    }

    async _loadExceptionContext() {
        if (!this.state.selectedWorkcenterId) {
            this.state.lineId = false;
            this.state.lineName = "";
            this.state.categories = [];
            this.state.pendingConfirms = [];
            return;
        }
        try {
            const data = await this.orm.silent.call(
                "sn.wsd.exception.service", "terminal_context",
                [this.state.selectedWorkcenterId]);
            this.state.lineId = data.line_id || false;
            this.state.lineName = data.line_name || "";
            this.state.categories = data.categories || [];
            this.state.pendingConfirms = (data.my_pending_confirms || [])
                .map((card) => ({ ...card, rejecting: false, note: "" }));
            this.state.categoryId = null;
        } catch (error) {
            // exception module unavailable or no access: say it once
            this.state.lineId = false;
            this.state.lineName = "";
            this.state.categories = [];
            this.state.pendingConfirms = [];
            this._error(error);
        }
    }

    async confirmCard(card) {
        this.state.loading = true;
        try {
            const result = await this.orm.silent.call(
                "sn.wsd.exception.service", "confirm", [card.ticket_id]);
            this._setResult(result.message || _t("Exception closed."), "success");
            await this._loadExceptionContext();
        } catch (error) {
            this._error(error);
        } finally {
            this.state.loading = false;
        }
    }

    toggleReject(card) {
        card.rejecting = !card.rejecting;
    }

    async submitReject(card) {
        if (!card.note.trim()) {
            this._setResult(_t("Write a rejection note first."), "warning");
            return;
        }
        this.state.loading = true;
        try {
            const result = await this.orm.silent.call(
                "sn.wsd.exception.service", "reject",
                [card.ticket_id, card.note.trim()]);
            this._setResult(result.message || _t("Exception rejected."),
                "success");
            await this._loadExceptionContext();
        } catch (error) {
            this._error(error);
        } finally {
            this.state.loading = false;
        }
    }

    openSelector(selector) {
        this.state.selector = selector;
    }

    closeSelector() {
        this.state.selector = false;
    }

    async selectRecord(record) {
        if (this.state.selector === "line") {
            this.state.selectedLineId = record.id || false;
            const first = this.state.workcenters.find(
                (w) => w.line_id === record.id);
            this.state.selector = false;
            if (first) {
                await this.loadWorkcenters(first.id);
            }
            return;
        }
        this.state.selector = false;
        await this.loadWorkcenters(record.id);
    }

    pickCategory(categoryId) {
        this.state.categoryId = categoryId;
    }

    async onPhotoPicked(ev) {
        const file = (ev.target.files || [])[0];
        ev.target.value = "";
        if (!file) {
            return;
        }
        try {
            this.state.photoBase64 = await this._compressPhoto(file);
        } catch (error) {
            this._error(error);
        }
    }

    _compressPhoto(file) {
        // camera pictures are multi-megabyte; keep the request body sane
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(reader.error);
            reader.onload = () => {
                const img = new Image();
                img.onerror = () => reject(new Error("Invalid image."));
                img.onload = () => {
                    const scale = Math.min(
                        1, PHOTO_MAX_EDGE / Math.max(img.width, img.height));
                    const canvas = document.createElement("canvas");
                    canvas.width = Math.round(img.width * scale);
                    canvas.height = Math.round(img.height * scale);
                    canvas.getContext("2d").drawImage(img, 0, 0,
                                                       canvas.width, canvas.height);
                    const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
                    resolve(dataUrl.split(",")[1] || false);
                };
                img.src = reader.result;
            };
            reader.readAsDataURL(file);
        });
    }

    clearPhoto() {
        this.state.photoBase64 = false;
    }

    async submitReport(ev) {
        if (ev) {
            ev.preventDefault();
        }
        if (!this.state.lineId) {
            this._setResult(
                _t("This work center has no production line; exceptions are reported per line."),
                "warning");
            return;
        }
        if (!this.state.categoryId) {
            this._setResult(this.categoryRequiredMsg, "warning");
            return;
        }
        this.state.loading = true;
        try {
            const result = await this.orm.silent.call(
                "sn.wsd.exception.service", "report", [], {
                    line_id: this.state.lineId,
                    category_id: this.state.categoryId,
                    note: this.state.note || "",
                    image_base64: this.state.photoBase64 || false,
                });
            this._setResult(result.message || _t("Exception reported."), "success");
            this.state.note = "";
            this.state.photoBase64 = false;
            await this._loadExceptionContext();
        } catch (error) {
            this._error(error);
        } finally {
            this.state.loading = false;
        }
    }

    _setResult(message, type) {
        this.state.result = message;
        this.state.resultType = type || "info";
    }

    _error(error) {
        this._setResult(
            error?.data?.message || error?.message || String(error), "danger");
    }
}

registry.category("actions").add("sn_wsd_barcode_exception_report", ExceptionReportAction);

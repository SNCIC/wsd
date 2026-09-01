/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useBus } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const MODES = [
    { key: "ok", label: _t("OK") },
    { key: "ng", label: _t("NG") },
    { key: "scrap", label: _t("Scrap") },
];

// Station passing (everyone): pick a work center, pick a sticky result
// mode, scan in-progress SNs. OK leaves in one scan; NG holds the WIP row
// client-side and waits for the defect-code scan (two-step, like the shop
// floor terminal); scrap opens the mandatory reason list. Exit-only by
// design: feeding and order switching stay on the shop floor terminal.
export class StationPassAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.StationPassAction";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.state = useState({
            workcenters: [],
            lines: [],
            selectedLineId: false,
            selectedWorkcenterId: false,
            operationLabel: "",
            orders: [],
            wipTotal: 0,
            scrapReasons: [],
            mode: "ok",
            ngPending: false,   // {wipId, sn} while waiting for the defect code
            scrapDialog: false, // {wipId, sn, reasonId}
            selector: false,    // 'line' | 'workcenter'
            command: "",
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
        onWillStart(() => this.loadData(false));
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

    get modes() {
        return MODES;
    }

    get title() {
        return _t("Station Pass");
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

    get inProgressLabel() {
        return _t("In progress");
    }

    get ordersLabel() {
        return _t("Orders");
    }

    get scrapTitle() {
        return this.state.scrapDialog
            ? _t("Scrap %s — pick a reason", this.state.scrapDialog.sn)
            : _t("Scrap — pick a reason");
    }

    get confirmScrapLabel() {
        return _t("Scrap");
    }

    get cancelLabel() {
        return _t("Cancel");
    }

    get scanHint() {
        if (this.state.ngPending) {
            return _t("Scan the defect code.");
        }
        return _t("Scan the SN in progress.");
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

    async loadData(workcenterId) {
        this.state.loading = true;
        try {
            const data = await this.orm.silent.call(
                "sn.wsd.mes.order", "sn_station_floor_data", [workcenterId || false]);
            this._applyFloorData(data);
            this.state.result = "";
        } catch (error) {
            this._error(error);
        } finally {
            this.state.loading = false;
        }
    }

    _applyFloorData(data) {
        const state = this.state;
        state.workcenters = data.workcenters || [];
        const lines = [];
        for (const wc of state.workcenters) {
            if (wc.line_id && !lines.some((l) => l.id === wc.line_id)) {
                lines.push({ id: wc.line_id, name: wc.line_name });
            }
        }
        state.lines = lines;
        state.orders = data.orders || [];
        state.wipTotal = data.wip_total || 0;
        state.scrapReasons = data.scrap_reasons || [];
        state.selectedWorkcenterId = (data.workcenter || {}).id || false;
        const wc = state.workcenters.find(
            (w) => w.id === state.selectedWorkcenterId);
        state.selectedLineId = (wc && wc.line_id) || false;
        state.operationLabel = (data.workcenter || {}).operation || "";
        state.ngPending = false;
        state.scrapDialog = false;
    }

    async _refreshCounts() {
        try {
            const data = await this.orm.silent.call(
                "sn.wsd.mes.order", "sn_station_floor_data",
                [this.state.selectedWorkcenterId || false]);
            const pending = this.state.ngPending;
            const dialog = this.state.scrapDialog;
            this._applyFloorData(data);
            // a refresh must never eat an in-flight NG/scrap interaction
            this.state.ngPending = pending;
            this.state.scrapDialog = dialog;
        } catch (error) { /* counts are cosmetic */ }
    }

    focusInput() {
        setTimeout(() => {
            const input = this.el?.querySelector(".o_sn_wsd_station_command");
            if (input) {
                input.focus();
            }
        }, 50);
    }

    setMode(key) {
        this.state.mode = key;
        this.state.ngPending = false;
        this.focusInput();
    }

    async onScan(barcode) {
        const code = String(barcode || "").trim();
        if (!code || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            if (this.state.ngPending) {
                await this._leaveNg(code);
            } else {
                await this._resolveAndLeave(code);
            }
            this.state.command = "";
        } catch (error) {
            this._error(error);
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    async _resolveAndLeave(code) {
        if (!this.state.selectedWorkcenterId) {
            this._setResult(_t("Select a work center first."), "warning");
            return;
        }
        const hit = await this.orm.silent.call(
            "sn.wsd.mes.order", "sn_station_scan_leave",
            [this.state.selectedWorkcenterId, code]);
        if (!hit.leave) {
            // one-scan kernel: the scan parked the board at this station
            // (feeding or arrival pull) -- no completion happens here
            this._setResult(
                _t("SN %s parked at %s.", code, this.state.operationLabel || ""),
                "success");
            await this._refreshCounts();
            return;
        }
        if (this.state.mode === "ng") {
            // two-step NG: hold the WIP row, wait for the defect code scan
            this.state.ngPending = { wipId: hit.wip_id, sn: code };
            this._setResult(_t("SN %s — scan the defect code.", code), "info");
            return;
        }
        if (this.state.mode === "scrap") {
            this.state.scrapDialog = {
                wipId: hit.wip_id, sn: code, reasonId: null,
            };
            return;
        }
        await this.orm.silent.call(
            "sn.wsd.mes.order", "sn_station_leave", [hit.wip_id, "ok"]);
        this._setResult(
            _t("SN %s passed %s.", code, this.state.operationLabel || ""), "success");
        await this._refreshCounts();
    }

    async _leaveNg(code) {
        const defect = await this.orm.silent.call(
            "sn.wsd.mes.order", "sn_resolve_ng_defect", [code]);
        if (!defect) {
            this._setResult(_t("No defect code matches %s.", code), "danger");
            return;
        }
        const pending = this.state.ngPending;
        await this.orm.silent.call(
            "sn.wsd.mes.order", "sn_station_leave",
            [pending.wipId, "ng", false, defect.id]);
        this.state.ngPending = false;
        this._setResult(
            _t("SN %s left %s with NG (%s).",
               pending.sn, this.state.operationLabel || "", defect.name),
            "success");
        await this._refreshCounts();
    }

    async submitCommand(ev) {
        if (ev) {
            ev.preventDefault();
        }
        const code = this.state.command.trim();
        if (!code) {
            return;
        }
        await this.onScan(code);
    }

    pickScrapReason(reasonId) {
        if (this.state.scrapDialog) {
            this.state.scrapDialog.reasonId = reasonId;
        }
    }

    cancelScrap() {
        this.state.scrapDialog = false;
        this.focusInput();
    }

    async confirmScrap() {
        const dialog = this.state.scrapDialog;
        if (!dialog) {
            return;
        }
        if (!dialog.reasonId) {
            this._setResult(_t("Select a scrap reason."), "warning");
            return;
        }
        this.state.loading = true;
        try {
            await this.orm.silent.call(
                "sn.wsd.mes.order", "sn_station_leave",
                [dialog.wipId, "scrap", dialog.reasonId]);
            this.state.scrapDialog = false;
            this._setResult(
                _t("SN %s scrapped.", dialog.sn), "success");
            await this._refreshCounts();
        } catch (error) {
            // surface the failure inside the dialog -- the result strip
            // sits behind the modal backdrop and would hide it
            this._error(error);
            if (this.state.scrapDialog) {
                this.state.scrapDialog.error =
                    error.data?.message || error.message || String(error);
            }
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    openSelector(selector) {
        this.state.selector = selector;
    }

    closeSelector() {
        this.state.selector = false;
        this.focusInput();
    }

    async selectRecord(record) {
        if (this.state.selector === "line") {
            this.state.selectedLineId = record.id || false;
            const first = this.state.workcenters.find(
                (w) => w.line_id === record.id);
            this.state.selector = false;
            if (first) {
                await this.loadData(first.id);
            }
            return;
        }
        this.state.selector = false;
        await this.loadData(record.id);
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

registry.category("actions").add("sn_wsd_barcode_station_pass", StationPassAction);

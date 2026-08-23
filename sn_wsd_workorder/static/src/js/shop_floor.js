/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useState } from "@odoo/owl";

const STATE_LABELS = {
    blocked: _t("Blocked"),
    ready: _t("To Do"),
    progress: _t("In Progress"),
    done: _t("Finished"),
    cancel: _t("Cancelled"),
};

const UI_LABELS = {
    allWorkcenters: _t("All Work Centers"),
    blockWorkcenter: _t("Block Work Center"),
    cancel: _t("Cancel"),
    confirm: _t("Confirm"),
    correctReport: _t("Correct Report"),
    consumedQuantity: _t("Consumed Quantity"),
    currentOperator: _t("Current Operator:"),
    customerLabel: _t("Customer"),
    doneButton: _t("Complete (Receipt)"),
    doneLabel: _t("Done"),
    doneQtyLabel: _t("Done Qty"),
    doneTitle: _t("Complete Products"),
    doneSuccess: _t("Completion receipt created."),
    orderDone: _t("MES order completed."),
    destinationLabel: _t("Destination"),
    destinationLineside: _t("Workshop line side (auto-validated)"),
    destinationStock: _t("Finished goods stock (waiting for validation)"),
    enterSn: _t("Feed SN"),
    exceptionCategoryRequired: _t("Select a category first."),
    exceptionNoLine: _t("This work center has no production line; exceptions are reported per line."),
    exceptionNoteLabel: _t("Description"),
    exceptionNotePlaceholder: _t("One line: what happened on the line?"),
    exceptionSubmit: _t("Report"),
    exceptionTitle: _t("Report Exception"),
    reportException: _t("Report Exception"),
    finish: _t("Finish"),
    inProgressHere: _t("In progress at this station"),
    inputPoint: _t("Input Point"),
    inputQtyLabel: _t("Input"),
    loadingWorkorders: _t("Loading Work Orders"),
    loadingStation: _t("Loading Station"),
    logIn: _t("Log In"),
    logOut: _t("Log Out"),
    materials: _t("Materials"),
    needOrder: _t("Select a MES order first."),
    noOperator: _t("No Operator"),
    noOperators: _t("No Operators"),
    noStationOrders: _t("No online MES orders run through this operation."),
    noWorkorders: _t("No work orders to process."),
    openManufacturingOrder: _t("Open Manufacturing Order"),
    openWorkOrder: _t("Open Work Order"),
    operationLabel: _t("Operation"),
    outputPoint: _t("Output Point"),
    outputQtyLabel: _t("Output"),
    okQtyLabel: _t("OK Qty"),
    ngQtyLabel: _t("NG Qty"),
    scrapBtn: _t("Scrap"),
    modeNg: _t("NG mode"),
    modeOk: _t("OK pass-through"),
    modeScrap: _t("Scrap mode"),
    moreWipHidden: _t("More WIP hidden — scanning still works"),
    otherOrders: _t("Other live orders"),
    snLeftNg: _t("SN left with NG."),
    snLeftOk: _t("SN left with OK."),
    scanGo: _t("Go"),
    scanHint: _t("Scan an order barcode to switch, a WIP SN to leave, or a new SN to feed the current order."),
    scanPlaceholder: _t("Scan SN / order barcode…"),
    switchOrder: _t("Switch"),
    tapToAct: _t("tap to act"),
    scrapConfirmTitle: _t("Confirm Scrap"),
    scrapReasonLabel: _t("Scrap Reason"),
    scrapReasonRequired: _t("Select a scrap reason."),
    scrapQtyLabel: _t("Scrap Qty"),
    pauseWork: _t("Pause Work"),
    planned: _t("Planned:"),
    plannedQtyLabel: _t("Planned"),
    reason: _t("Reason"),
    registerMaterialConsumption: _t("Register Material Consumption"),
    remainingQuantity: _t("Remaining Quantity:"),
    reportAndFinish: _t("Report and Finish"),
    reportModeBadge: _t("Work Report"),
    reportedLabel: _t("Reported"),
    reportedQuantity: _t("Reported Quantity"),
    reportQuantity: _t("Report Quantity"),
    searchWorkorders: _t("Search Work Orders"),
    selectEmployee: _t("Select Employee"),
    pickWorkshop: _t("Select a workshop"),
    selectProductionLine: _t("All Production Lines"),
    selectWorkshop: _t("All Workshops"),
    signedInOperators: _t("Signed-in Operators:"),
    snEntered: _t("SN entered the operation."),
    snFlowFinished: _t("SN flow finished on this MES order."),
    snPlaceholder: _t("Scan or type SN, then press Enter"),
    startWork: _t("Start Work"),
    stationModeBadge: _t("Station"),
    stationTab: _t("Station Passing"),
    tabWorkorders: _t("Work Orders"),
    unblockWorkcenter: _t("Unblock Work Center"),
    wipQtyLabel: _t("WIP"),
    workcenter: _t("Work Center:"),
    workorderInputPoint: _t("Work Order Input Point"),
    workorderInputQtyLabel: _t("Work Order Input"),
};

export class SnWsdShopFloor extends Component {
    static template = "sn_wsd_workorder.ShopFloor";
    static props = standardActionServiceProps;

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.menu = useService("menu");
        this.notification = useService("notification");
        this.barcode = useService("barcode");
        this.state = useState({
            operator: false,
            station: {
                loading: false,
                workcenterId: null,
                workcenters: [],
                workcenter: false,
                orders: [],
                wip: [],
                scrapReasons: [],
                selectedOrderId: null,
                scan: "",
                expandedWipId: null,
                mode: "ok",
            },
            stationScrapDialog: {
                open: false,
                row: false,
                reasonId: null,
            },
            stationReportDialog: {
                open: false,
                order: false,
                qtyOk: 0,
                qtyNg: 0,
                qtyScrap: 0,
                scrapReasonId: null,
            },
            stationDoneDialog: {
                open: false,
                order: false,
                qty: 0,
                destination: "stock",
                workshopId: null,
            },
            exception: {
                lineId: null,
                lineName: "",
                categories: [],
            },
            exceptionDialog: {
                open: false,
                categoryId: null,
                note: "",
            },
        });
        onWillStart(async () => {
            // the station page is the whole terminal: one payload brings
            // the orders, WIP rows and the signed-in operator
            await this.loadStation();
        });
        this.barcode.bus.addEventListener("barcode_scanned", (event) => this.onBarcode(event.detail.barcode));
    }

    get labels() {
        return UI_LABELS;
    }

    close() {
        // breadcrumbs include the terminal itself: only go back when a
        // controller actually precedes us (e.g. opened from the MO form)
        if ((this.env.config?.breadcrumbs || []).length > 1) {
            this.env.config.historyBack();
            return;
        }
        // entered from the shop-floor menu or a fresh URL: land on the
        // Manufacturing app so the navbar shows its menus -- not a bare
        // action page stranded under the shop-floor app
        const apps = this.menu.getApps();
        const mfg = apps.find(
            (app) => app.xmlid === "mrp.menu_mrp_root"
                || /制造|Manufacturing/i.test(app.name || ""));
        if (mfg) {
            this.menu.selectMenu(mfg);
        } else {
            this.action.doAction("sn_wsd_mrp.action_sn_wsd_mes_orders");
        }
    }

    async onBarcode(barcode) {
        await this.onScanSubmit(barcode);
    }

    // ------------------------------------------------------------------
    // station passing tab: work center -> orders -> feed SNs / report qty
    // ------------------------------------------------------------------
    get selectedStationOrder() {
        return this.state.station.orders.find((o) => o.id === this.state.station.selectedOrderId) || false;
    }

    get showSnBar() {
        const order = this.selectedStationOrder;
        return Boolean(order) && order.manage_mode === "station";
    }

    // uncontrolled select: read the picked value here instead of t-model,
    // so the browser's own selection is never reset by a re-render
    onWorkcenterChange(ev) {
        const value = ev.target.value;
        this.state.station.workcenterId = value ? Number(value) : null;
        this.loadStation();
    }

    async loadStation(workcenterId) {
        this.state.station.loading = true;
        try {
            const data = await this.orm.call("sn.wsd.mes.order", "sn_station_floor_data", [
                workcenterId ?? this.state.station.workcenterId ?? false,
            ]);
            this.applyStationData(data);
            await this.loadExceptionContext();
        } finally {
            this.state.station.loading = false;
        }
    }

    // ------------------------------------------------------------------
    // exception reporting (delegated to sn_wsd_exception terminal service)
    // ------------------------------------------------------------------

    async loadExceptionContext() {
        const workcenterId = this.state.station.workcenterId;
        if (!workcenterId) {
            return;
        }
        try {
            const data = await this.orm.silent.call(
                "sn.wsd.exception.service", "terminal_context", [workcenterId]);
            this.state.exception.lineId = data.line_id || null;
            this.state.exception.lineName = data.line_name || "";
            this.state.exception.categories = data.categories || [];
        } catch {
            // exception module unavailable or no access: keep the terminal alive
            this.state.exception.lineId = null;
        }
    }

    openExceptionDialog() {
        if (!this.state.exception.lineId) {
            this.notification.add(this.labels.exceptionNoLine, { type: "warning" });
            return;
        }
        const dialog = this.state.exceptionDialog;
        dialog.open = true;
        dialog.categoryId = null;
        dialog.note = "";
    }

    closeExceptionDialog() {
        this.state.exceptionDialog.open = false;
    }

    async submitException() {
        const dialog = this.state.exceptionDialog;
        if (!dialog.categoryId) {
            this.notification.add(this.labels.exceptionCategoryRequired, { type: "warning" });
            return;
        }
        try {
            const result = await this.orm.silent.call(
                "sn.wsd.exception.service", "report", [], {
                    line_id: this.state.exception.lineId,
                    category_id: dialog.categoryId,
                    note: dialog.note || "",
                });
            this.notification.add(result.message, { type: "success" });
            this.closeExceptionDialog();
        } catch (error) {
            this.notifyError(error);
        }
    }

    applyStationData(data) {
        const station = this.state.station;
        const employees = data.employees || {};
        const owner = (employees.connected || []).find(
            (e) => e.id === employees.owner_id) || (employees.connected || [])[0];
        this.state.operator = owner || false;
        station.workcenters = data.workcenters;
        station.workcenter = data.workcenter;
        station.orders = data.orders;
        station.wip = data.wip;
        station.scrapReasons = data.scrap_reasons || [];
        station.wipTotal = data.wip_total || data.wip.length;
        station.workcenterId = data.workcenter?.id || null;
        if (!station.orders.some((o) => o.id === station.selectedOrderId)) {
            // one station, one order: prefer whatever is actually running
            const wipOrderIds = new Set(station.wip.map((w) => w.order_id));
            const withWip = station.orders.find((o) => wipOrderIds.has(o.id));
            const started = station.orders.find(
                (o) => (o.input_qty || 0) > 0 || (o.op?.reported_qty || 0) > 0);
            station.selectedOrderId = (withWip || started || station.orders[0] || {}).id || null;
        }
    }

    get hiddenWipCount() {
        return Math.max((this.state.station.wipTotal || 0) - this.state.station.wip.length, 0);
    }

    get otherOrders() {
        return this.state.station.orders.filter(
            (o) => o.id !== this.state.station.selectedOrderId);
    }

    get groupedWip() {
        const groups = [];
        const byOrder = new Map();
        for (const row of this.state.station.wip) {
            if (!byOrder.has(row.order_id)) {
                const group = { order_id: row.order_id, order_name: row.order_name, rows: [] };
                byOrder.set(row.order_id, group);
                groups.push(group);
            }
            byOrder.get(row.order_id).rows.push(row);
        }
        return groups;
    }

    setStationMode(mode) {
        this.state.station.mode = mode;
    }

    toggleWipRow(row) {
        const station = this.state.station;
        station.expandedWipId = station.expandedWipId === row.id ? null : row.id;
    }

    selectStationOrder(order) {
        this.state.station.selectedOrderId = order.id;
    }

    onScanKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onScanSubmit();
        }
    }

    async onScanSubmit(explicitCode) {
        const station = this.state.station;
        const code = (explicitCode ?? station.scan ?? "").trim();
        if (!code) {
            return;
        }
        try {
            const result = await this.orm.silent.call("sn.wsd.mes.order", "sn_station_scan", [
                station.workcenterId, code, station.selectedOrderId || false,
            ]);
            if (result.action === "select_order" || result.action === "entered") {
                if (result.data) {
                    this.applyStationData(result.data);
                }
                station.selectedOrderId = result.order_id;
                if (result.action === "entered") {
                    this.notification.add(this.labels.snEntered, { type: "success" });
                }
            } else if (result.action === "leave") {
                station.selectedOrderId = result.order_id;
                station.scan = "";
                this.focusScanInput();
                const mode = station.mode;
                if (mode === "ok" || mode === "ng") {
                    await this.leaveStationWip({ id: result.wip_id }, mode);
                } else {
                    // scrap keeps its mandatory reason dialog
                    const row = station.wip.find((w) => w.id === result.wip_id);
                    const dialog = this.state.stationScrapDialog;
                    dialog.open = true;
                    dialog.row = row || { id: result.wip_id };
                    dialog.reasonId = null;
                }
                return;
            }
            station.scan = "";
            this.focusScanInput();
        } catch (error) {
            this.notifyError(error);
            this.focusScanInput();
        }
    }

    focusScanInput() {
        setTimeout(() => {
            document.querySelector(".o_sn_wsd_scan_input")?.focus();
        }, 0);
    }

    async leaveStationWip(row, result) {
        if (result === "scrap") {
            const dialog = this.state.stationScrapDialog;
            dialog.open = true;
            dialog.row = row;
            dialog.reasonId = null;
            return;
        }
        try {
            const payload = await this.orm.silent.call("sn.wsd.mes.order", "sn_station_leave", [
                row.id, result, false,
            ]);
            this.applyStationData(payload.data);
            this.notification.add(
                result === "ok" ? this.labels.snLeftOk : this.labels.snLeftNg,
                { type: result === "ok" ? "success" : "warning" });
            if (payload.finished) {
                this.notification.add(this.labels.snFlowFinished, { type: "success" });
            }
        } catch (error) {
            this.notifyError(error);
        }
    }

    async submitStationScrap() {
        const dialog = this.state.stationScrapDialog;
        if (!dialog.reasonId) {
            this.notification.add(this.labels.scrapReasonRequired, { type: "warning" });
            return;
        }
        try {
            const payload = await this.orm.silent.call("sn.wsd.mes.order", "sn_station_leave", [
                dialog.row.id, "scrap", dialog.reasonId,
            ]);
            this.state.stationScrapDialog.open = false;
            this.state.stationScrapDialog.row = false;
            this.applyStationData(payload.data);
            if (payload.finished) {
                this.notification.add(this.labels.snFlowFinished, { type: "success" });
            }
        } catch (error) {
            this.notifyError(error);
        }
    }

    openStationReportDialog(order) {
        const dialog = this.state.stationReportDialog;
        dialog.open = true;
        dialog.order = order;
        dialog.qtyOk = 1;
        dialog.qtyNg = 0;
        dialog.qtyScrap = 0;
        dialog.scrapReasonId = null;
    }

    closeStationReportDialog() {
        const dialog = this.state.stationReportDialog;
        dialog.open = false;
        dialog.order = false;
        dialog.qtyOk = 0;
        dialog.qtyNg = 0;
        dialog.qtyScrap = 0;
    }

    async submitStationReport() {
        const dialog = this.state.stationReportDialog;
        const qtyOk = Number(dialog.qtyOk) || 0;
        const qtyNg = Number(dialog.qtyNg) || 0;
        const qtyScrap = Number(dialog.qtyScrap) || 0;
        if (qtyOk < 0 || qtyNg < 0 || qtyScrap < 0 || qtyOk + qtyNg + qtyScrap <= 0) {
            this.notification.add(_t("Enter a positive quantity."), { type: "warning" });
            return;
        }
        if (qtyScrap > 0 && !dialog.scrapReasonId) {
            this.notification.add(this.labels.scrapReasonRequired, { type: "warning" });
            return;
        }
        try {
            const data = await this.orm.silent.call("sn.wsd.mes.order", "sn_station_report", [
                [dialog.order.id], this.state.station.workcenterId, qtyOk, qtyNg, qtyScrap,
                dialog.scrapReasonId || false,
            ]);
            this.applyStationData(data);
            this.closeStationReportDialog();
        } catch (error) {
            this.notifyError(error);
        }
    }



    // completion (完工入库) from the station terminal
    openStationDoneDialog(order) {
        const dialog = this.state.stationDoneDialog;
        dialog.open = true;
        dialog.order = order;
        dialog.qty = Math.max(order.output_qty - (order.done_qty || 0), 0);
        dialog.destination = "stock";
        dialog.workshopId = null;
    }

    closeStationDoneDialog() {
        const dialog = this.state.stationDoneDialog;
        dialog.open = false;
        dialog.order = false;
        dialog.qty = 0;
        dialog.destination = "stock";
        dialog.workshopId = null;
    }

    async submitStationDone() {
        const dialog = this.state.stationDoneDialog;
        const qty = Number(dialog.qty);
        if (!qty || qty <= 0) {
            this.notification.add(_t("Enter a positive quantity."), { type: "warning" });
            return;
        }
        if (dialog.destination === "lineside" && !dialog.workshopId) {
            this.notification.add(_t("Select a workshop."), { type: "warning" });
            return;
        }
        try {
            const result = await this.orm.silent.call("sn.wsd.mes.order", "sn_station_done", [
                [dialog.order.id], qty, dialog.destination, dialog.workshopId || false,
            ]);
            this.closeStationDoneDialog();
            this.notification.add(this.labels.doneSuccess, { type: "success" });
            if (result.state === "done") {
                this.notification.add(this.labels.orderDone, { type: "success" });
            }
            await this.loadStation();
        } catch (error) {
            this.notifyError(error);
        }
    }



    notifyError(error) {
        this.notification.add(error?.data?.message || error?.message || String(error), {
            type: "danger",
        });
    }

    formatMinutes(minutes) {
        const value = Number(minutes || 0);
        const hours = Math.floor(value / 60);
        const mins = Math.round(value % 60);
        return hours ? `${hours}h ${mins}m` : `${mins}m`;
    }
}

registry.category("actions").add("sn_wsd_shop_floor", SnWsdShopFloor);

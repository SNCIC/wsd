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
    finish: _t("Finish"),
    loadingWorkorders: _t("Loading Work Orders"),
    logIn: _t("Log In"),
    logOut: _t("Log Out"),
    materials: _t("Materials"),
    noOperator: _t("No Operator"),
    noOperators: _t("No Operators"),
    noWorkorders: _t("No work orders to process."),
    openManufacturingOrder: _t("Open Manufacturing Order"),
    openWorkOrder: _t("Open Work Order"),
    pauseWork: _t("Pause Work"),
    planned: _t("Planned:"),
    reason: _t("Reason"),
    registerMaterialConsumption: _t("Register Material Consumption"),
    remainingQuantity: _t("Remaining Quantity:"),
    reportAndFinish: _t("Report and Finish"),
    reportedQuantity: _t("Reported Quantity"),
    reportQuantity: _t("Report Quantity"),
    searchWorkorders: _t("Search Work Orders"),
    selectEmployee: _t("Select Employee"),
    selectProductionLine: _t("All Production Lines"),
    selectWorkshop: _t("All Workshops"),
    signedInOperators: _t("Signed-in Operators:"),
    startWork: _t("Start Work"),
    unblockWorkcenter: _t("Unblock Work Center"),
    workcenter: _t("Work Center:"),
};

export class SnWsdShopFloor extends Component {
    static template = "sn_wsd_workorder.ShopFloor";
    static props = standardActionServiceProps;

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.barcode = useService("barcode");
        this.state = useState({
            loading: true,
            context: { ...(this.props.action?.context || {}) },
            operator: false,
            workorders: [],
            search: "",
            openMenuWorkorderId: false,
            quantityDialog: {
                open: false,
                workorder: false,
                quantity: 0,
                finish: false,
            },
            consumeDialog: {
                open: false,
                workorder: false,
                component: false,
                quantity: 0,
            },
        });
        onWillStart(async () => {
            await this.reload();
        });
        this.barcode.bus.addEventListener("barcode_scanned", (event) => this.onBarcode(event.detail.barcode));
    }

    async reload(context = undefined) {
        this.state.loading = true;
        if (context) {
            this.state.context = { ...this.state.context, ...context };
        }
        const data = await this.orm.call("mrp.workorder", "sn_shop_floor_get_data", [
            this.state.context,
        ]);
        this.state.operator = data.operator;
        this.state.workorders = data.workorders;
        this.state.loading = false;
    }

    get filteredWorkorders() {
        const query = this.state.search.trim().toLowerCase();
        if (!query) {
            return this.state.workorders;
        }
        return this.state.workorders.filter((workorder) => {
            const haystack = [
                workorder.name,
                workorder.display_name,
                workorder.production?.name,
                workorder.production?.product,
                workorder.workcenter?.name,
                workorder.operation_type,
            ].filter(Boolean).join(" ").toLowerCase();
            return haystack.includes(query);
        });
    }

    get labels() {
        return UI_LABELS;
    }

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    stateClass(state) {
        return {
            blocked: "text-bg-danger",
            ready: "text-bg-info",
            progress: "text-bg-warning",
            done: "text-bg-success",
            cancel: "text-bg-secondary",
        }[state] || "text-bg-secondary";
    }

    async execute(workorder, operation, payload = {}) {
        this.state.openMenuWorkorderId = false;
        const data = await this.orm.call(
            "mrp.workorder",
            "sn_shop_floor_execute",
            [workorder.id, operation, { ...payload, context: this.state.context }]
        );
        this.state.operator = data.operator;
        this.state.workorders = data.workorders;
    }

    async openWorkorder(workorder) {
        this.state.openMenuWorkorderId = false;
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "mrp.workorder",
            views: [[false, "form"]],
            res_id: workorder.id,
        });
    }

    toggleWorkorderMenu(workorder) {
        this.state.openMenuWorkorderId = this.state.openMenuWorkorderId === workorder.id ? false : workorder.id;
    }

    async openProduction(workorder) {
        this.state.openMenuWorkorderId = false;
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "mrp.production",
            views: [[false, "form"]],
            res_id: workorder.production.id,
        });
    }

    async openReportCorrection(workorder) {
        this.state.openMenuWorkorderId = false;
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Correct Report"),
            res_model: "mrp.workorder.report",
            views: [[false, "list"], [false, "form"]],
            domain: [["workorder_id", "=", workorder.id]],
            context: {
                default_workorder_id: workorder.id,
                default_production_id: workorder.production.id,
            },
        });
    }

    openQuantityDialog(workorder, finish = false) {
        this.state.openMenuWorkorderId = false;
        this.state.quantityDialog.open = true;
        this.state.quantityDialog.workorder = workorder;
        this.state.quantityDialog.quantity = workorder.qty_producing || workorder.qty_remaining || 1;
        this.state.quantityDialog.finish = Boolean(finish);
    }

    closeQuantityDialog() {
        this.state.quantityDialog.open = false;
        this.state.quantityDialog.workorder = false;
        this.state.quantityDialog.quantity = 0;
        this.state.quantityDialog.finish = false;
    }

    async submitQuantity() {
        const dialog = this.state.quantityDialog;
        const quantity = Number(dialog.quantity);
        if (!quantity || quantity <= 0) {
            this.notification.add(_t("Enter a positive quantity."), { type: "warning" });
            return;
        }
        await this.execute(dialog.workorder, "register_quantity", {
            quantity,
            finish: dialog.finish,
        });
        this.closeQuantityDialog();
    }

    openConsumeDialog(workorder, component) {
        this.state.openMenuWorkorderId = false;
        this.state.consumeDialog.open = true;
        this.state.consumeDialog.workorder = workorder;
        this.state.consumeDialog.component = component;
        this.state.consumeDialog.quantity = component.done_qty || component.planned_qty || 0;
    }

    closeConsumeDialog() {
        this.state.consumeDialog.open = false;
        this.state.consumeDialog.workorder = false;
        this.state.consumeDialog.component = false;
        this.state.consumeDialog.quantity = 0;
    }

    async submitConsume() {
        const dialog = this.state.consumeDialog;
        const quantity = Number(dialog.quantity);
        if (Number.isNaN(quantity) || quantity < 0) {
            this.notification.add(_t("Enter a valid consumed quantity."), { type: "warning" });
            return;
        }
        await this.execute(dialog.workorder, "consume_material", {
            move_id: dialog.component.id,
            quantity,
        });
        this.closeConsumeDialog();
    }

    close() {
        window.history.back();
    }

    async onBarcode(barcode) {
        const workorder = this.state.workorders.find((item) => item.barcode === barcode || item.production?.name === barcode);
        if (workorder) {
            await this.execute(workorder, workorder.state === "progress" ? "pause" : "start");
            return;
        }
        this.state.search = barcode;
    }

    formatMinutes(minutes) {
        const value = Number(minutes || 0);
        const hours = Math.floor(value / 60);
        const mins = Math.round(value % 60);
        return hours ? `${hours}h ${mins}m` : `${mins}m`;
    }
}

registry.category("actions").add("sn_wsd_shop_floor", SnWsdShopFloor);

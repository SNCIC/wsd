/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// 设备作业屏（先看后扫）：开屏=今日待办看板（跨设备聚合，不扫码），
// 人到设备前扫设备编码进入该设备待办执行。
export class DevicePdaAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.DevicePdaAction";

    setup() {
        this.action = useService("action");
        this.barcodeService = useService("barcode");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.inputRef = useRef("scanInput");
        this.state = useState({
            view: "board",           // board | equipment
            command: "",
            message: "",
            messageType: "info",
            loading: false,
            userName: "",
            progress: {due: 0, done: 0, todo: 0, overdue: 0},
            groups: [],
            done: [],
            showDone: false,
            equipment: null,
            tasks: [],
            locations: [],
            locationId: null,
            locationName: "",
            showLocationModal: false,
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
            this._loadUserInfo();
            this.loadBoard();
            this.loadLocations();
            this.focusInput();
        });
        onWillUnmount(() => {
            this.mobileService.stopReader();
        });
    }

    get title() {
        return _t("Device Operations");
    }

    get backLabel() {
        return _t("Back");
    }

    get dueLabel() {
        return _t("Due");
    }

    get doneLabel() {
        return _t("Done");
    }

    get todoLabel() {
        return _t("Todo");
    }

    get overdueLabel() {
        return _t("Overdue");
    }

    get doneFoldLabel() {
        return this.state.showDone
            ? _t("Hide done today")
            : _t("Done today (%s)", this.state.done.length);
    }

    get emptyBoardLabel() {
        return _t("No open task today. Scan an equipment code to see its card.");
    }

    get startLabel() {
        return _t("Start");
    }

    get backToBoardLabel() {
        return _t("Back to list");
    }

    get itemsLabel() {
        return _t("items");
    }

    get noTasksLabel() {
        return _t("No open task for this equipment today.");
    }

    get locationFilterLabel() {
        return this.state.locationName || _t("All locations");
    }

    get scanHint() {
        return _t("Scan an equipment code at the machine");
    }

    get lastCheckLabel() {
        return _t("Last check");
    }

    get lastMaintLabel() {
        return _t("Last maintenance");
    }

    async _loadUserInfo() {
        try {
            const data = await rpc("/sn_wsd_barcode/get_workshop_operation_data");
            this.state.userName = data.user_name || "";
        } catch (error) { /* non-critical */ }
    }

    async _deviceCall(action, params = {}) {
        return rpc("/sn_wsd_barcode/pda/device/call", {action, ...params});
    }

    focusInput() {
        setTimeout(() => this.inputRef.el?.focus(), 0);
    }

    goBack() {
        this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_workshop_functions_action");
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
        const code = (rawBarcode || "").trim();
        if (!code || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            const result = await this._deviceCall("resolve", {code});
            if (!result.ok) {
                this.state.message = result.message;
                this.state.messageType = "danger";
            } else {
                const data = result.data;
                this.state.equipment = data.equipment;
                this.state.tasks = data.tasks;
                this.state.view = "equipment";
                if (data.tasks.length) {
                    this.state.message = _t(
                        "%s: %s open task(s).",
                        data.equipment.code, data.tasks.length);
                    this.state.messageType = "success";
                } else {
                    this.state.message = this.noTasksLabel;
                    this.state.messageType = "warning";
                }
            }
        } catch (error) {
            this.state.message = error.message || _t("Operation failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    async loadBoard() {
        this.state.loading = true;
        try {
            const params = {};
            if (this.state.locationId) {
                params.location_id = this.state.locationId;
            }
            const result = await this._deviceCall("today_board", params);
            if (result.ok) {
                this.state.progress = result.data.progress;
                this.state.groups = result.data.groups;
                this.state.done = result.data.done;
                if (this.state.view === "equipment") {
                    this.state.view = "board";
                }
            }
        } catch (error) { /* keep the board as-is */ } finally {
            this.state.loading = false;
        }
    }

    async loadLocations() {
        try {
            const result = await this._deviceCall("locations");
            if (result.ok) {
                this.state.locations = result.data;
            }
        } catch (error) { /* filter stays on All */ }
    }

    openLocationModal() {
        this.state.showLocationModal = true;
    }

    closeLocationModal() {
        this.state.showLocationModal = false;
        this.focusInput();
    }

    async selectLocation(location) {
        this.state.locationId = location ? location.id : null;
        this.state.locationName = location ? location.name : "";
        this.state.showLocationModal = false;
        this.state.message = "";
        await this.loadBoard();
        this.focusInput();
    }

    async refreshEquipment() {
        if (!this.state.equipment) {
            return;
        }
        try {
            const result = await this._deviceCall("resolve", {
                code: this.state.equipment.code,
            });
            if (result.ok) {
                this.state.equipment = result.data.equipment;
                this.state.tasks = result.data.tasks;
            }
        } catch (error) { /* keep current view */ }
    }

    async backToBoard() {
        this.state.view = "board";
        this.state.equipment = null;
        this.state.tasks = [];
        await this.loadBoard();
        this.focusInput();
    }

    async startTask(task) {
        if (this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            const result = await this._deviceCall("task_start", {
                kind: task.kind,
                task_id: task.id,
            });
            if (!result.ok) {
                this.state.message = result.message;
                this.state.messageType = "danger";
            } else {
                this.state.message = _t(
                    "Task %s started. Items are pre-filled OK, adjust any abnormal item.",
                    task.name);
                this.state.messageType = "success";
            }
            await this.refreshEquipment();
        } catch (error) {
            this.state.message = error.message || _t("Operation failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    taskStatusLabel(status) {
        return {
            pending: _t("Pending"),
            in_progress: _t("In Progress"),
            completed: _t("Completed"),
            overdue: _t("Overdue"),
        }[status] || status;
    }

    taskKindLabel(kind) {
        return kind === "maint" ? _t("Maintenance") : _t("Spot Check");
    }

    equipmentStatusLabel(status) {
        return {
            enabled: _t("In Use"),
            repair: _t("Under Repair"),
            sealed: _t("Sealed"),
            scrapped: _t("Scrapped"),
        }[status] || status;
    }
}

registry.category("actions").add("sn_wsd_barcode_device_action", DevicePdaAction);

/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// 设备作业屏（先看后扫）：开屏=今日待办看板（跨设备聚合，不扫码），
// 人到设备前扫设备编码进入该设备待办执行；检查项默认全 OK，异常才改。
export class DevicePdaAction extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.DevicePdaAction";

    setup() {
        this.action = useService("action");
        this.barcodeService = useService("barcode");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.inputRef = useRef("scanInput");
        this.state = useState({
            view: "board",           // board | equipment | task
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
            // task execution view
            task: null,
            lines: [],
            // repair report modal
            showRepairModal: false,
            repairFaultType: null,
            repairFaultLevel: null,
            repairDescription: "",
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

    get continueLabel() {
        return _t("Continue");
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

    get locationFilterTitle() {
        return _t("Location Filter");
    }

    get allLocationsLabel() {
        return _t("All locations");
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

    // ===== task execution view labels =====

    get taskViewTitle() {
        return _t("Task Execution");
    }

    get backToEquipmentLabel() {
        return _t("Back to equipment");
    }

    get defaultOkHintLabel() {
        return _t("All items are pre-filled OK. Only touch abnormal ones.");
    }

    get normalLabel() {
        return _t("Normal");
    }

    get abnormalLabel() {
        return _t("Abnormal");
    }

    get noteLabel() {
        return _t("Note");
    }

    get submitTaskLabel() {
        return _t("Submit");
    }

    get viewGuideLabel() {
        return _t("Guide");
    }

    // ===== repair modal labels =====

    get repairLabel() {
        return _t("Report Repair");
    }

    get faultTypeLabel() {
        return _t("Fault Type");
    }

    get faultLevelLabel() {
        return _t("Fault Level");
    }

    get faultDescriptionLabel() {
        return _t("Fault Description");
    }

    get cancelLabel() {
        return _t("Cancel");
    }

    get confirmLabel() {
        return _t("Confirm");
    }

    get faultTypes() {
        return [
            ['mechanical', _t("Mechanical")],
            ['electrical', _t("Electrical")],
            ['software', _t("Software")],
            ['other', _t("Other")],
        ];
    }

    get faultLevels() {
        return [
            ['minor', _t("Minor")],
            ['general', _t("General")],
            ['critical', _t("Critical")],
        ];
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
                this.state.locations = result.data || [];
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
        this.state.locationName = location ? location.full_name : "";
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

    async backToEquipment() {
        this.state.view = "equipment";
        this.state.task = null;
        this.state.lines = [];
        await this.refreshEquipment();
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
                this.state.task = result.data.task;
                this.state.equipment = result.data.equipment;
                this.state.lines = result.data.lines;
                this.state.view = "task";
                this.state.message = _t(
                    "Task %s started. %s", task.name, this.defaultOkHintLabel);
                this.state.messageType = "success";
            }
        } catch (error) {
            this.state.message = error.message || _t("Operation failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    _replaceLine(updated) {
        const index = this.state.lines.findIndex((line) => line.id === updated.id);
        if (index >= 0) {
            this.state.lines.splice(index, 1, updated);
        }
    }

    async updateLine(line, params) {
        try {
            const result = await this._deviceCall("task_update_line", {
                kind: this.state.task.kind,
                line_id: line.id,
                ...params,
            });
            if (result.ok) {
                this._replaceLine(result.data);
            } else {
                this.state.message = result.message;
                this.state.messageType = "danger";
            }
        } catch (error) {
            this.state.message = error.message || _t("Operation failed.");
            this.state.messageType = "danger";
        }
    }

    setLineResult(line, lineResult) {
        if (line.line_result === lineResult) {
            return;
        }
        this.updateLine(line, {line_result: lineResult});
    }

    setMeasuredValue(line, ev) {
        const value = parseFloat(ev.target.value);
        if (isNaN(value) || value === line.measured_value) {
            return;
        }
        this.updateLine(line, {measured_value: value});
    }

    setLineNote(line, ev) {
        const note = ev.target.value;
        if (note === line.line_note) {
            return;
        }
        this.updateLine(line, {line_note: note});
    }

    async submitTask() {
        if (!this.state.task || this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            const result = await this._deviceCall("task_submit", {
                kind: this.state.task.kind,
                task_id: this.state.task.id,
            });
            if (!result.ok) {
                this.state.message = result.message;
                this.state.messageType = "danger";
            } else {
                const overall = result.data.overall_result === 'fail'
                    ? _t("FAIL") : _t("PASS");
                this.state.message = _t("Task %s submitted: %s.",
                    result.data.name, overall);
                this.state.messageType = result.data.overall_result === 'fail'
                    ? "warning" : "success";
                await this.backToEquipment();
            }
        } catch (error) {
            this.state.message = error.message || _t("Operation failed.");
            this.state.messageType = "danger";
        } finally {
            this.state.loading = false;
            this.focusInput();
        }
    }

    guideUrl(line) {
        const model = this.state.task.kind === 'maint'
            ? 'sn.wsd.device.maint.task.line'
            : 'sn.wsd.device.check.task.line';
        return `/web/content?model=${model}&id=${line.id}` +
            `&field=guide_file&filename_field=guide_filename&download=true`;
    }

    locationIcon(location) {
        return {
            factory: 'fa-building-o',
            workshop: 'fa-industry',
            line: 'fa-arrows-h',
            station: 'fa-bullseye',
        }[location.kind] || 'fa-map-marker';
    }

    // ===== repair report =====

    openRepairModal() {
        this.state.showRepairModal = true;
        this.state.repairFaultType = null;
        this.state.repairFaultLevel = null;
        this.state.repairDescription = "";
    }

    closeRepairModal() {
        this.state.showRepairModal = false;
        this.focusInput();
    }

    selectRepairFaultType(value) {
        this.state.repairFaultType = value;
    }

    selectRepairFaultLevel(value) {
        this.state.repairFaultLevel = value;
    }

    async confirmRepair() {
        if (!this.state.repairFaultType || !this.state.repairFaultLevel) {
            this.state.message = _t("Select a fault type and a fault level.");
            this.state.messageType = "danger";
            return;
        }
        if (!this.state.repairDescription.trim()) {
            this.state.message = this.faultDescriptionLabel + ': ' +
                _t("required");
            this.state.messageType = "danger";
            return;
        }
        this.state.loading = true;
        try {
            const result = await this._deviceCall("repair_create", {
                code: this.state.equipment.code,
                fault_type: this.state.repairFaultType,
                fault_level: this.state.repairFaultLevel,
                description: this.state.repairDescription.trim(),
            });
            if (!result.ok) {
                this.state.message = result.message;
                this.state.messageType = "danger";
            } else {
                this.state.message = _t(
                    "Repair order %s created for %s.",
                    result.data.order, result.data.equipment);
                this.state.messageType = "success";
                this.state.showRepairModal = false;
            }
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

import { _t } from "@web/core/l10n/translation";
import { Mutex } from "@web/core/utils/concurrency";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import {
    BarcodeVideoScanner,
    isBarcodeScannerSupported,
} from "@web/core/barcode/barcode_video_scanner";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const SMT_OPS = new Set(["smt_offline_prepare", "smt_online_load", "smt_cart_load", "smt_unload", "smt_material_refill"]);

// SMT material operations collapsed into one sub-mode button: picking a
// pill routes to the same step flows the old top-level buttons used
const SMT_MATERIAL_ACTIONS = [
    { key: "smt_online_load", label: _t("Load") },
    { key: "smt_offline_prepare", label: _t("Prepare") },
    { key: "smt_unload", label: _t("Unload") },
    { key: "smt_material_refill", label: _t("Refill") },
    { key: "smt_cart_load", label: _t("Cart Mount") },
    { key: "smt_changeover", label: _t("Changeover") },
];

const SMT_OPERATION_BUTTONS = [
    { key: "smt_material", label: _t("SMT Material") },
];

// jigs are shared by both workshops: SMT and DIP each get the button
const JIG_BUTTON = { key: "equipment_tooling", label: _t("Jig") };

// product station passing is NOT done on PDA for now -- the DIP screen
// only carries the shared jig sub-mode
const DIP_OPERATION_BUTTONS = [JIG_BUTTON];

// equipment sub-modes of the SMT workshop screen: pick a pill, scan the SN
const EQUIPMENT_MODES = {
    tooling: {
        key: "equipment_tooling",
        label: _t("Tooling"),
        actions: [
            { key: "online", label: _t("Put online") },
            { key: "offline", label: _t("Take offline") },
            { key: "issue", label: _t("Issue") },
            { key: "return_", label: _t("Return") },
            { key: "maintain_start", label: _t("Maintain start") },
            { key: "maintain_done", label: _t("Maintain done") },
            { key: "repair_start", label: _t("Repair start"), extra: "fault" },
            { key: "repair_done", label: _t("Repair done") },
        ],
    },
    consumable: {
        key: "equipment_consumable",
        label: _t("Consumables"),
        actions: [
            { key: "load", label: _t("Put online") },
            { key: "unload", label: _t("Take offline") },
            { key: "issue", label: _t("Issue") },
            { key: "return_", label: _t("Return") },
            { key: "thaw_start", label: _t("Thaw start") },
            { key: "thaw_end", label: _t("Thaw done") },
            { key: "stir_start", label: _t("Stir start") },
            { key: "stir_end", label: _t("Stir done") },
            { key: "exhaust", label: _t("Exhaust") },
        ],
    },
};

export class WorkshopOperationAction extends Component {
    static template = "sn_wsd_barcode.WorkshopOperationAction";
    static props = { ...standardActionServiceProps };
    static components = { BarcodeVideoScanner };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.barcodeService = useService("barcode");
        this.mobileService = useService("sn_wsd_barcode_mobile");
        this.scanMutex = new Mutex();
        this.operationMode = this.props.action.context?.operation_mode || "smt";
        // workshop-functions grid entries open the action directly in an
        // equipment sub-mode (tooling / consumable pills only)
        this.initialEquipmentDomain = this.props.action.context?.initial_equipment_domain || false;
        this.state = useState({
            lines: [],
            stations: [],
            selectedLineId: false,
            selectedStationId: false,
            command: "",
            rawValue: "",
            result: "",
            resultType: "info",
            selectedOperation: false,
            selector: false,
            selectorQuery: "",
            total: 0,
            userName: "",
            smtStep: 0,
            smtDeviceTable: "",
            smtLoadpoint: "",
            smtMaterialSn: "",
            smtFeederSn: "",
            smtOldMaterialSn: "",
            productionId: false,
            productionName: "",
            materialTableName: "",
            smtMaterialSummary: {
                required_qty: 0,
                loaded_qty: 0,
                unloaded_qty: 0,
            },
            smtMaterialRows: [],
            smtLoading: false,
            cameraScannerEnabled: false,
            readyToToggleCamera: true,
                    equipmentDomain: false,
            equipmentAction: false,
            equipmentExtra: "",
            prepareCartSn: "",
            changeoverTargetProduction: false,
        });

        this.cameraScannerSupported = isBarcodeScannerSupported();
        if (this.initialEquipmentDomain) {
            this.state.equipmentDomain = this.initialEquipmentDomain;
        }
        this.barcodeVideoScannerProps = {
            delayBetweenScan: 1200,
            facingMode: "environment",
            onResult: (barcode) => this.onBarcodeScanned(barcode),
            onError: (error) => {
                this.state.cameraScannerEnabled = false;
                this.state.readyToToggleCamera = true;
                this.notification.add(error.message, { type: "warning" });
            },
            onReady: () => {
                this.state.readyToToggleCamera = true;
            },
            cssClass: "o_stock_barcode_camera_video",
        };

        useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
            this.onBarcodeScanned(ev.detail.barcode)
        );
        useBus(this.mobileService.bus, "mobile_reader_scanned", (ev) => {
            for (const barcode of ev.detail.data || []) {
                this.onBarcodeScanned(barcode);
            }
        });

        onWillStart(() => this.loadData());
        onMounted(() => {
            this.mobileService.enableReader();
            this.focusCommandInput();
        });
        onWillUnmount(() => {
            this.mobileService.stopReader();
        });
    }

    async loadData() {
        const data = await rpc("/sn_wsd_barcode/get_workshop_operation_data");
        this.state.lines = data.lines || [];
        this.state.stations = data.stations || [];
        this.state.userName = data.user_name || "";
        this.state.selectedLineId = this.state.lines[0]?.id || false;
        this.state.selectedStationId =
            this.filteredStations[0]?.id || this.state.stations[0]?.id || false;
        if (this.isSmtMode && this.state.selectedStationId) {
            await this.loadSmtContext();
        }
    }

    async loadSmtContext() {
        try {
            const ctx = await rpc("/sn_wsd_barcode/smt/get_production_context", {
                workcenter_id: this.state.selectedStationId,
                production_line_id: this.state.selectedLineId || false,
            });
            this.state.productionId = ctx.production_id;
            this.state.productionName = ctx.production_name;
            this.state.materialTableName = ctx.smt_material_table_name;
            await this.loadSmtMaterialStatus(ctx.production_id);
        } catch {
            this.state.productionId = false;
            this.state.productionName = "";
            this.state.materialTableName = "";
            this.clearSmtMaterialStatus();
        }
    }

    async loadSmtMaterialStatus(productionId) {
        if (!productionId) {
            this.clearSmtMaterialStatus();
            return;
        }
        const status = await rpc("/sn_wsd_barcode/smt/get_material_table_status", {
            production_id: productionId,
        });
        this.state.smtMaterialSummary = status.summary || {
            required_qty: 0,
            loaded_qty: 0,
            unloaded_qty: 0,
        };
        this.state.smtMaterialRows = status.rows || [];
    }

    clearSmtMaterialStatus() {
        this.state.smtMaterialSummary = {
            required_qty: 0,
            loaded_qty: 0,
            unloaded_qty: 0,
        };
        this.state.smtMaterialRows = [];
    }

    get smtOperationButtons() {
        if (this.isDipMode) {
            return DIP_OPERATION_BUTTONS;
        }
        return [...SMT_OPERATION_BUTTONS,
                JIG_BUTTON, EQUIPMENT_MODES.consumable];
    }

    get equipmentModeDef() {
        if (this.state.equipmentDomain === "smt_material") {
            return { key: "smt_material", label: _t("SMT Material"),
                     actions: SMT_MATERIAL_ACTIONS };
        }
        return this.state.equipmentDomain
            ? EQUIPMENT_MODES[this.state.equipmentDomain] : false;
    }

    get equipmentActionDef() {
        const def = this.equipmentModeDef;
        return def
            ? def.actions.find((a) => a.key === this.state.equipmentAction) || false
            : false;
    }

    get isSmtMode() {
        return this.operationMode === "smt";
    }

    // feeder control flag of the selected production line: when on, the
    // online-load cycle scans the feeder channel SN before each loadpoint
    get smtFeederControl() {
        const line = this.state.lines.find((l) => l.id === this.state.selectedLineId);
        return Boolean(line && line.is_feeder_control);
    }

    get isDipMode() {
        return this.operationMode === "dip";
    }

    get backLabel() {
        return _t("Back");
    }

    get loadingLabel() {
        return _t("Processing...");
    }

    get workshopOperationsLabel() {
        return this.isDipMode ? _t("DIP Operations") : _t("SMT Operations");
    }

    get productionLineLabel() {
        return _t("Production Line");
    }

    get workCenterLabel() {
        return _t("Work Center");
    }

    get scanMessage() {
        if (this.isDipMode) {
            return this.state.selectedOperation
                ? _t("Scan material SN.")
                : _t("Select an operation, then scan.");
        }
        if (!this.isSmtOperation) {
            return _t("Scan a barcode or enter it manually.");
        }
        const op = this.state.selectedOperation;
        const step = this.state.smtStep;
        if (op === "smt_offline_prepare") {
            const parts = [];
            if (this.state.prepareCartSn) {
                parts.push(_t("Cart SN: ") + this.state.prepareCartSn);
            }
            if (this.state.smtFeederSn) {
                parts.push(_t("Channel SN: ") + this.state.smtFeederSn);
            }
            if (this.state.smtLoadpoint) {
                parts.push(_t("Loadpoint: ") + this.state.smtLoadpoint);
            }
            if (this.state.smtMaterialSn) {
                parts.push(_t("Material SN: ") + this.state.smtMaterialSn);
            }
            return parts.join(" | " );
        }
        if (op === "smt_online_load") {
            const messages = [
                _t("Scan the TABLE code, for example 3.T1."),
                _t("Scan the feeder channel SN."),
                _t("Scan the loadpoint, then the material SN."),
            ];
            return messages[Math.max(step - 1, 0)] || messages[0];
        }
        if (op === "smt_material_refill") {
            const messages = [_t("Scan old material SN."), _t("Scan new material SN.")];
            return messages[Math.max(step - 1, 0)] || messages[0];
        }
        if (op === "smt_unload") {
            return _t("Scan material SN.");
        }
        return _t("Select an operation, then scan.");
    }

    get enterCommandLabel() {
        return this.scanMessage;
    }

    get originalValueLabel() {
        return _t("Last Scan");
    }

    get processingResultLabel() {
        return _t("Result");
    }


    get requiredQtyLabel() {
        return _t("Required");
    }

    get loadedQtyLabel() {
        return _t("Loaded");
    }

    get unloadedQtyLabel() {
        return _t("Not Loaded");
    }

    get enterKeywordLabel() {
        return _t("Enter keyword");
    }

    get hasSmtMaterialStatus() {
        return this.isSmtMode && Boolean(this.state.productionId);
    }

    get selectedLine() {
        return this.state.lines.find((line) => line.id === this.state.selectedLineId);
    }

    get filteredStations() {
        if (!this.state.selectedLineId) {
            return this.state.stations;
        }
        return this.state.stations.filter((station) => station.line_id === this.state.selectedLineId);
    }

    get selectedStation() {
        return this.state.stations.find((station) => station.id === this.state.selectedStationId);
    }

    get selectorTitle() {
        return this.state.selector === "line" ? _t("Select Production Line") : _t("Select Work Center");
    }

    get selectorRecords() {
        const records = this.state.selector === "line" ? this.state.lines : this.filteredStations;
        const query = this.state.selectorQuery.trim().toLowerCase();
        if (!query) {
            return records;
        }
        return records.filter((record) =>
            `${record.display_name || ""} ${record.name || ""} ${record.code || ""}`
                .toLowerCase()
                .includes(query)
        );
    }

    get isSmtOperation() {
        return this.isSmtMode && this.state.selectedOperation && SMT_OPS.has(this.state.selectedOperation);
    }

    get smtScanSummary() {
        const op = this.state.selectedOperation;
        if (op === "smt_offline_prepare") {
            const parts = [];
            if (this.state.prepareCartSn) {
                parts.push(_t("Cart SN: ") + this.state.prepareCartSn);
            }
            if (this.state.smtFeederSn) {
                parts.push(_t("Channel SN: ") + this.state.smtFeederSn);
            }
            if (this.state.smtLoadpoint) {
                parts.push(_t("Loadpoint: ") + this.state.smtLoadpoint);
            }
            if (this.state.smtMaterialSn) {
                parts.push(_t("Material SN: ") + this.state.smtMaterialSn);
            }
            return parts.join(" | " );
        }
        if (op === "smt_online_load") {
            const parts = [];
            if (this.state.smtDeviceTable) {
                parts.push(_t("Device Table: ") + this.state.smtDeviceTable);
            }
            if (this.state.smtLoadpoint) {
                parts.push(_t("Feeder Position: ") + this.state.smtLoadpoint);
            }
            if (this.state.smtMaterialSn) {
                parts.push(_t("Material SN: ") + this.state.smtMaterialSn);
            }
            return parts.join(" | ");
        }
        if (op === "smt_material_refill") {
            const parts = [];
            if (this.state.smtOldMaterialSn) {
                parts.push(_t("Old Material: ") + this.state.smtOldMaterialSn);
            }
            if (this.state.smtMaterialSn) {
                parts.push(_t("New Material: ") + this.state.smtMaterialSn);
            }
            return parts.join(" | ");
        }
        if (op === "smt_cart_load") {
            const parts = [];
            if (this.state.smtDeviceTable) {
                parts.push(_t("Device Table: ") + this.state.smtDeviceTable);
            }
            if (this.state.smtFeederSn) {
                parts.push(_t("Cart SN: ") + this.state.smtFeederSn);
            }
            return parts.join(" | " );
        }
        if (op === "smt_unload" && this.state.smtMaterialSn) {
            return _t("Material SN: ") + this.state.smtMaterialSn;
        }
        return "";
    }

    get cameraScannerClassState() {
        if (!this.state.readyToToggleCamera) {
            return "bg-secondary";
        }
        return this.state.cameraScannerEnabled ? "bg-success text-white" : "text-primary";
    }

    get resultClass() {
        return {
            "text-success": this.state.resultType === "success",
            "text-danger": this.state.resultType === "danger",
            "text-warning": this.state.resultType === "warning",
            "text-muted": this.state.resultType === "info",
        };
    }

    goBack() {
        this.state.cameraScannerEnabled = false;
        if (this.env.config.breadcrumbs.length > 1) {
            this.env.config.historyBack();
        } else {
            this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_workshop_functions_action");
        }
    }

    toggleCameraScanner() {
        if (!this.state.cameraScannerEnabled) {
            this.state.cameraScannerEnabled = true;
            this.state.readyToToggleCamera = false;
        } else if (this.state.readyToToggleCamera) {
            this.state.cameraScannerEnabled = false;
        }
    }

    focusCommandInput() {
        setTimeout(() => {
            const input = this.el?.querySelector(".o_sn_wsd_workshop_command");
            if (input) {
                input.focus();
                input.setSelectionRange(input.value.length, input.value.length);
            }
        }, 50);
    }

    openSelector(selector) {
        this.state.selector = selector;
        this.state.selectorQuery = "";
    }

    closeSelector() {
        this.state.selector = false;
        this.state.selectorQuery = "";
        this.focusCommandInput();
    }

    selectRecord(record) {
        if (this.state.selector === "line") {
            this.state.selectedLineId = record.id;
            const nextStation = this.filteredStations[0];
            this.state.selectedStationId = nextStation?.id || false;
        } else {
            this.state.selectedStationId = record.id;
        }
        this.closeSelector();
        if (this.isSmtMode) {
            this.loadSmtContext();
        }
    }

    resetSmtScan() {
        this.state.smtStep = 0;
        this.state.smtDeviceTable = "";
        this.state.smtLoadpoint = "";
        this.state.smtMaterialSn = "";
        this.state.smtFeederSn = "";
        this.state.smtOldMaterialSn = "";
    }

    setResult(message, type = "info") {
        this.state.result = message;
        this.state.resultType = type;
    }

    parseBarcodeFields(barcode) {
        const fields = {};
        for (const part of barcode.split("|")) {
            const index = part.indexOf("=");
            if (index <= 0) {
                continue;
            }
            const key = part.slice(0, index).trim().toUpperCase();
            const value = part.slice(index + 1).trim();
            if (key && value) {
                fields[key] = value;
            }
        }
        return fields;
    }

    async submitCommand(ev) {
        ev.preventDefault();
        const command = this.state.command.trim();
        if (!command) {
            return;
        }
        await this.onBarcodeScanned(command);
    }

    async onBarcodeScanned(barcode) {
        const cleanBarcode = String(barcode || "").trim();
        if (!cleanBarcode || this.state.selector) {
            return;
        }
        await this.scanMutex.exec(async () => {
            if (this.state.equipmentDomain === "smt_material") {
                await this._handleSmtMaterialScan(cleanBarcode);
            } else if (this.state.equipmentDomain) {
                await this._handleEquipmentScan(cleanBarcode);
            } else if (this.isSmtOperation) {
                await this._handleSmtScan(cleanBarcode);
            } else if (this.state.selectedOperation) {
                await this.processScan(cleanBarcode, this.state.selectedOperation);
            } else {
                this.state.rawValue = cleanBarcode;
                this.setResult(_t("Select an operation before scanning."), "warning");
            }
            if ("vibrate" in window.navigator) {
                window.navigator.vibrate(100);
            }
        });
    }

    async _handleSmtMaterialScan(barcode) {
        const action = this.state.equipmentAction;
        if (!action) {
            this.setResult(_t("Pick a material action before scanning."), "warning");
            return;
        }
        if (action === "smt_offline_prepare") {
            await this._handleOfflinePrepareFlow(barcode);
        } else if (action === "smt_changeover") {
            await this._handleChangeoverFlow(barcode);
        } else {
            await this._handleSmtScan(barcode);
        }
    }

    // offline prepare: scan cart once, then loop ([channel SN ->] loadpoint
    // -> reel) mirroring the online-loading order; feeder channel scan only
    // when the production line enables feeder control
    async _handleOfflinePrepareFlow(barcode) {
        if (!this.state.prepareCartSn) {
            this.state.prepareCartSn = barcode;
            this.state.command = "";
            this.resetSmtScan();
            this.state.smtStep = 2; // skip the device-table step: offline
            this.setResult(
                this.smtFeederControl
                    ? _t("Cart %s locked. Scan the feeder channel SN.", barcode)
                    : _t("Cart %s locked. Scan the loadpoint.", barcode),
                "success"
            );
            this.focusCommandInput();
            return;
        }
        // cart locked: channel SN -> reel SN -> slot -> stage submit (loop)
        await this._handleOfflinePrepareStep(barcode);
    }

    // changeover: scan target production order barcode, then device table
    async _handleChangeoverFlow(barcode) {
        if (!this.state.changeoverTargetProduction) {
            // resolve the production order by name via the ORM
            const ids = await this.orm.search(
                "mrp.production", [["name", "=", barcode]], { limit: 1 });
            if (!ids.length) {
                this.setResult(
                    _t("Production order %s not found.", barcode), "danger");
                return;
            }
            this.state.changeoverTargetProduction = ids[0];
            this.state.command = "";
            this.setResult(
                _t("Target order recorded. Scan the device table (e.g. 3.Table1)."),
                "info");
            this.focusCommandInput();
            return;
        }
        try {
            const res = await rpc("/sn_wsd_barcode/smt/do_changeover", {
                production_id: this.state.productionId,
                target_production_id: this.state.changeoverTargetProduction,
                workcenter_id: this.state.selectedStationId,
            });
            this.state.command = "";
            this.setResult(res.message || "", res.ok ? "success" : "danger");
            if (res.ok) {
                this.state.changeoverTargetProduction = false;
                await this.loadSmtContext();
            }
        } catch (error) {
            this.setResult(error.message || _t("Operation failed."), "danger");
        } finally {
            this.focusCommandInput();
        }
    }

    pickEquipmentAction(key) {
        this.state.equipmentAction = key;
        this.state.equipmentExtra = "";
        this.state.command = "";
        if (this.state.equipmentDomain === "smt_material") {
            // route to the standard SMT step flow for that operation
            this.state.selectedOperation = key;
            this.resetSmtScan();
            this.state.smtStep = 1;
            this.setResult(this._smtStepHint(key), "info");
            this.focusCommandInput();
            return;
        }
        this.setResult(_t("Scan the equipment SN."), "info");
        this.focusCommandInput();
    }

    _smtStepHint(key) {
        if (key === "smt_online_load") {
            return _t("TP: scan the TABLE code, for example 3.T1.");
        }
        if (key === "smt_offline_prepare") {
            this.state.prepareCartSn = "";
            return _t("Prepare: scan the cart SN first.");
        }
        // (hint only -- the flow starts at the cart scan, not at smtStep)
        if (key === "smt_unload") {
            return _t("Unload: scan material SN.");
        }
        if (key === "smt_material_refill") {
            return _t("Refill: scan old material SN.");
        }
        if (key === "smt_changeover") {
            this.state.changeoverTargetProduction = false;
            return _t("Changeover: scan the target production order barcode.");
        }
        return _t("Scan.");
    }

    async _handleEquipmentScan(sn) {
        if (!this.state.equipmentAction) {
            this.setResult(_t("Pick an equipment action before scanning."), "warning");
            return;
        }
        const payload = { action: this.state.equipmentAction, sn };
        if (this.equipmentActionDef?.extra && this.state.equipmentExtra) {
            payload[this.equipmentActionDef.extra] = this.state.equipmentExtra;
        }
        try {
            const result = await rpc(`/sn_wsd_barcode/pda/${this.state.equipmentDomain}/call`, payload);
            this.state.command = "";
            if (result.data) {
                this.setResult(
                    `${result.data.sn} · ${result.data.state || ""}`, "success");
            } else {
                this.setResult(result.message || "", result.ok ? "success" : "danger");
            }
        } catch (error) {
            this.setResult(error.message || _t("Operation failed."), "danger");
        } finally {
            this.focusCommandInput();
        }
    }

    async _handleSmtScan(rawBarcode) {
        if (this.state.smtLoading) {
            return;
        }
        const op = this.state.selectedOperation;
        const barcode = rawBarcode.trim();

        if (barcode.includes("=")) {
            const fields = this.parseBarcodeFields(barcode);
            this.state.rawValue = barcode;
            if (op === "smt_offline_prepare") {
                this.state.smtDeviceTable = fields.DEV || "";
                this.state.smtLoadpoint = fields.LP || "";
                this.state.smtMaterialSn = fields.MAT || "";
                this.state.smtFeederSn = fields.CART || fields.FD || "";
            } else if (op === "smt_online_load") {
                this.state.smtDeviceTable = fields.DEV || "";
                this.state.smtLoadpoint = fields.LP || "";
                this.state.smtMaterialSn = fields.MAT || "";
                this.state.smtFeederSn = fields.FD || "";
            } else if (op === "smt_material_refill") {
                this.state.smtOldMaterialSn = fields.OLD_MAT || fields.MAT || "";
                this.state.smtMaterialSn = fields.NEW_MAT || "";
            } else if (op === "smt_unload") {
                this.state.smtMaterialSn = fields.MAT || "";
            }
            await this._submitSmtOperation(op);
            return;
        }

        if (op === "smt_offline_prepare") {
            await this._handleOfflinePrepareStep(barcode);
        } else if (op === "smt_online_load") {
            await this._handleOnlineLoadStep(barcode);
        } else if (op === "smt_cart_load") {
            await this._handleCartLoadStep(barcode);
        } else if (op === "smt_material_refill") {
            await this._handleMaterialRefillStep(barcode);
        } else if (op === "smt_unload") {
            await this._handleUnloadStep(barcode);
        }
    }

    // prepare loop per scan, order mirrors online loading:
    // [channel SN ->] loadpoint -> reel (one RPC per reel)
    async _handleOfflinePrepareStep(barcode) {
        if (this.smtFeederControl && !this.state.smtFeederSn) {
            this.state.smtFeederSn = barcode;
            this.state.rawValue = barcode;
            this.state.smtStep = 3;
            this.state.command = "";
            this.setResult(_t("Channel recorded. Scan the loadpoint."), "success");
            return;
        }
        if (!this.state.smtLoadpoint) {
            this.state.smtLoadpoint = barcode;
            this.state.rawValue = barcode;
            this.state.smtStep = 4;
            this.state.command = "";
            this.setResult(_t("Loadpoint %s recorded. Scan the material reel SN.", barcode), "success");
            return;
        }
        this.state.smtMaterialSn = barcode;
        this.state.rawValue = barcode;
        if (this.state.equipmentDomain === "smt_material"
                && this.state.equipmentAction === "smt_offline_prepare") {
            await this._submitOfflinePrepareStage();
            return;
        }
        await this._submitSmtOperation("smt_offline_prepare");
    }

    async _submitOfflinePrepareStage() {
        this.state.smtLoading = true;
        try {
            const res = await rpc("/sn_wsd_barcode/smt/do_offline_prepare_stage", {
                cart_sn_input: this.state.prepareCartSn,
                feeder_sn_input: this.state.smtFeederSn,
                material_sn_input: this.state.smtMaterialSn,
                slot_no: this.state.smtLoadpoint,
                production_id: this.state.productionId || false,
            });
            if (res.ok) {
                this.resetSmtScan();
                this.state.command = "";
                // stay in the loop: cart stays locked, scan the next
                // channel SN (or loadpoint when feeder control is off)
                this.setResult(
                    this.smtFeederControl
                        ? _t("Prepared. Cart %s -- scan the next feeder channel SN.",
                             this.state.prepareCartSn)
                        : _t("Prepared. Cart %s -- scan the next loadpoint.",
                             this.state.prepareCartSn),
                    "success");
            } else {
                this.setResult(res.message || _t("Operation failed."), "danger");
            }
        } catch (error) {
            this.setResult(error.message || _t("Operation failed."), "danger");
        } finally {
            this.state.smtLoading = false;
            this.focusCommandInput();
        }
    }

    async _handleCartLoadStep(barcode) {
        const step = this.state.smtStep;
        if (step === 0 || step === 1) {
            if (/^\d+\.[A-Za-z0-9_-]+$/.test(barcode)) {
                this.state.smtDeviceTable = barcode;
                this.state.rawValue = barcode;
                this.state.smtStep = 2;
                this.state.command = "";
                this.setResult(_t("Device table recorded. Scan cart SN."), "success");
            } else {
                this.setResult(_t("Invalid device table format. Expected N.T, for example 3.T1."), "danger");
            }
            return;
        }
        if (step === 2) {
            this.state.smtFeederSn = barcode;
            this.state.rawValue = barcode;
            await this._submitSmtOperation("smt_cart_load");
        }
    }

    async _handleOnlineLoadStep(rawBarcode) {
        // Continuous stream: a TABLE barcode (N.T) is the table-switch
        // signal from ANY state; everything else flows inside the cycle
        // [channel ->] loadpoint -> material, one RPC per material.
        const barcode = rawBarcode.trim();
        if (/^\d+\.[A-Za-z0-9_-]+$/.test(barcode)) {
            this.resetSmtScan();
            this.state.smtDeviceTable = barcode;
            this.state.rawValue = barcode;
            this.state.command = "";
            this.setResult(
                this.smtFeederControl
                    ? _t("Table %s. Scan the feeder channel SN.", barcode)
                    : _t("Table %s. Scan the loadpoint.", barcode),
                "success"
            );
            return;
        }
        if (!this.state.smtDeviceTable) {
            this.setResult(_t("Scan a TABLE code first, for example 3.T1."), "warning");
            return;
        }
        if (this.smtFeederControl && !this.state.smtFeederSn) {
            this.state.smtFeederSn = barcode;
            this.state.rawValue = barcode;
            this.state.command = "";
            this.setResult(_t("Channel recorded. Scan the loadpoint."), "success");
            return;
        }
        if (!this.state.smtLoadpoint) {
            this.state.smtLoadpoint = barcode;
            this.state.rawValue = barcode;
            this.state.command = "";
            this.setResult(_t("Loadpoint %s. Scan the material reel SN.", barcode), "success");
            return;
        }
        this.state.smtMaterialSn = barcode;
        this.state.rawValue = barcode;
        await this._submitOnlineLoad();
    }

    // per-material submit of the continuous online-load cycle; the table
    // context survives so the operator keeps scanning loadpoint -> reel
    // until they scan the next TABLE code
    async _submitOnlineLoad() {
        const table = this.state.smtDeviceTable;
        const loadpoint = this.state.smtLoadpoint;
        const material = this.state.smtMaterialSn;
        if (!this.state.selectedStationId) {
            this.setResult(_t("Select a work center first."), "warning");
            return;
        }
        this.state.smtLoading = true;
        try {
            const barcode = this._buildSmtBarcode("smt_online_load");
            const result = await rpc("/sn_wsd_barcode/smt/process_smt_scan", {
                station_id: this.state.selectedStationId,
                barcode,
                operation: "online_load",
            });
            if (result.ok) {
                this.state.command = "";
                this._resetOnlineCycle(table);
                this.setResult(
                    _t(
                        "Loaded %s / %s (%s). Scan the next loadpoint or a new TABLE.",
                        table,
                        loadpoint,
                        material
                    ),
                    "success"
                );
                await this.loadSmtContext();
            } else {
                this._resetOnlineCycle(table);
                this.setResult(result.message || _t("Operation failed."), "danger");
            }
        } catch (error) {
            this._resetOnlineCycle(table);
            this.setResult(error.message || _t("Operation failed."), "danger");
        } finally {
            this.state.smtLoading = false;
            this.focusCommandInput();
        }
    }

    _resetOnlineCycle(keepTable) {
        this.state.smtStep = 0;
        this.state.smtFeederSn = "";
        this.state.smtLoadpoint = "";
        this.state.smtMaterialSn = "";
        this.state.smtDeviceTable = keepTable || "";
    }

    async _handleMaterialRefillStep(barcode) {
        const step = this.state.smtStep;
        if (step === 0 || step === 1) {
            this.state.smtOldMaterialSn = barcode;
            this.state.rawValue = barcode;
            this.state.smtStep = 2;
            this.state.command = "";
            this.setResult(_t("Old material recorded. Scan new material SN."), "success");
            return;
        }
        if (step === 2) {
            if (barcode === this.state.smtOldMaterialSn) {
                this.setResult(_t("Old and new material SN cannot be the same."), "danger");
                return;
            }
            this.state.smtMaterialSn = barcode;
            this.state.rawValue = barcode;
            await this._submitSmtOperation("smt_material_refill");
        }
    }

    async _handleUnloadStep(barcode) {
        this.state.smtMaterialSn = barcode;
        this.state.rawValue = barcode;
        await this._submitSmtOperation("smt_unload");
    }

    _buildSmtBarcode(operation) {
        if (operation === "smt_offline_prepare") {
            const parts = [`DEV=${this.state.smtDeviceTable}`, `LP=${this.state.smtLoadpoint}`];
            if (this.state.smtMaterialSn) {
                parts.push(`MAT=${this.state.smtMaterialSn}`);
            }
            if (this.state.smtFeederSn) {
                parts.push(`CART=${this.state.smtFeederSn}`);
            }
            return parts.join("|");
        }
        if (operation === "smt_online_load") {
            const parts = [`DEV=${this.state.smtDeviceTable}`, `LP=${this.state.smtLoadpoint}`];
            if (this.state.smtMaterialSn) {
                parts.push(`MAT=${this.state.smtMaterialSn}`);
            }
            if (this.state.smtFeederSn) {
                parts.push(`FD=${this.state.smtFeederSn}`);
            }
            return parts.join("|");
        }
        if (operation === "smt_material_refill") {
            return `OLD_MAT=${this.state.smtOldMaterialSn}|NEW_MAT=${this.state.smtMaterialSn}`;
        }
        if (operation === "smt_cart_load") {
            return `DEV=${this.state.smtDeviceTable}|CART=${this.state.smtFeederSn}`;
        }
        if (operation === "smt_unload") {
            return `MAT=${this.state.smtMaterialSn}`;
        }
        return "";
    }

    async _submitSmtOperation(operation) {
        if (!this.state.selectedStationId) {
            this.setResult(_t("Select a work center first."), "warning");
            return;
        }
        this.state.smtLoading = true;
        try {
            const barcode = this._buildSmtBarcode(operation);
            const operationMap = {
                smt_offline_prepare: "offline_prepare",
                smt_online_load: "feeder_unload",
                smt_cart_load: "cart_load",
                smt_unload: "table_unload",
                smt_material_refill: "material_refill",
            };
            const result = await rpc("/sn_wsd_barcode/smt/process_smt_scan", {
                station_id: this.state.selectedStationId,
                barcode,
                operation: operationMap[operation],
            });
            if (result.ok) {
                this.setResult(result.message || _t("Operation completed."), "success");
                this.resetSmtScan();
                this.state.command = "";
                await this.loadSmtContext();
            } else {
                this.setResult(result.message || _t("Operation failed."), "danger");
            }
        } catch (error) {
            this.setResult(error.message || _t("Operation failed."), "danger");
        } finally {
            this.state.smtLoading = false;
            this.focusCommandInput();
        }
    }

    async runOperation(operation) {
        this.state.selectedOperation = operation.key;
        this.setResult("", "info");
        if (operation.key === "smt_material") {
            this.state.equipmentDomain = "smt_material";
            this.state.equipmentAction = false;
            this.state.equipmentExtra = "";
            this.resetSmtScan();
            this.state.command = "";
            this.setResult(_t("Pick a material action, then scan."), "info");
            this.focusCommandInput();
            return;
        }
        if (EQUIPMENT_MODES.tooling.key === operation.key
                || EQUIPMENT_MODES.consumable.key === operation.key) {
            this.state.equipmentDomain =
                operation.key === EQUIPMENT_MODES.tooling.key ? "tooling" : "consumable";
            this.state.equipmentAction = false;
            this.state.equipmentExtra = "";
            this.resetSmtScan();
            this.state.command = "";
            this.setResult(_t("Pick an equipment action, then scan the SN."), "info");
            this.focusCommandInput();
            return;
        }
        this.state.equipmentDomain = false;
        this.state.equipmentAction = false;
        this.state.equipmentExtra = "";

        if (SMT_OPS.has(operation.key)) {
            this.resetSmtScan();
            this.state.smtStep = 1;
            if (operation.key === "smt_offline_prepare") {
                this.setResult(_t("BL: scan the TABLE code, for example 3.T1."), "info");
            } else if (operation.key === "smt_online_load") {
                this.setResult(_t("TP: scan the TABLE code, for example 3.T1."), "info");
            } else if (operation.key === "smt_cart_load") {
                this.setResult(_t("LCSL: scan the TABLE code, for example 3.T1."), "info");
            } else if (operation.key === "smt_material_refill") {
                this.setResult(_t("Refill: scan old material SN."), "info");
            } else if (operation.key === "smt_unload") {
                this.setResult(_t("Unload: scan material SN."), "info");
            }
            this.focusCommandInput();
            return;
        }

        const command = this.state.command.trim();
        if (!command) {
            this.setResult(_t("Scan or enter a barcode first."), "warning");
            return;
        }
        await this.processScan(command, operation.key);
    }

    async processScan(barcode, operation) {
        if (!this.state.selectedStationId) {
            this.setResult(_t("Select a work center first."), "warning");
            return;
        }
        this.state.rawValue = barcode;
        const result = await rpc("/sn_wsd_barcode/process_workshop_scan", {
            station_id: this.state.selectedStationId,
            barcode,
            operation,
        });
        this.setResult(result.message || (result.ok ? _t("Scan accepted") : _t("Scan rejected")), result.ok ? "success" : "danger");
        if (result.ok) {
            this.state.command = "";
                    }
    }

    cancelSmtOperation() {
        this.state.selectedOperation = false;
        this.resetSmtScan();
        this.state.command = "";
        this.setResult("", "info");
        this.focusCommandInput();
    }
}

registry.category("actions").add("sn_wsd_barcode_workshop_action", WorkshopOperationAction);

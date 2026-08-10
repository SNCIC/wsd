/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class SamplingMatrixAction extends Component {
    static template = "sn_wsd_quality.SamplingMatrixAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.env.config.setDisplayName(this.props.action.name || _t("AQL Sampling Matrix"));
        this.state = useState({
            loading: true,
            saving: false,
            dirty: false,
            standards: [],
            standardId: false,
            switchingMode: "normal",
            levels: [],
            modes: [],
            aqls: [],
            lotRows: [],
            planRows: [],
        });
        onWillStart(() => this.loadMatrix());
    }

    get display() {
        return { controlPanel: {} };
    }

    async loadMatrix() {
        this.state.loading = true;
        const data = await this.orm.call(
            "sn.wsd.quality.sampling.standard",
            "get_sampling_matrix_data",
            [this.state.standardId || false, this.state.switchingMode || "normal"]
        );
        this.applyData(data);
        this.state.loading = false;
        this.state.dirty = false;
    }

    applyData(data) {
        this.state.standards = data.standards || [];
        this.state.standardId = data.standard_id || false;
        this.state.switchingMode = data.switching_mode || "normal";
        this.state.levels = data.levels || [];
        this.state.modes = data.modes || [];
        this.state.aqls = data.aqls || [];
        this.state.lotRows = data.lot_rows || [];
        this.state.planRows = data.plan_rows || [];
    }

    async onStandardChange(ev) {
        this.state.standardId = Number(ev.target.value) || false;
        await this.loadMatrix();
    }

    async onModeChange(ev) {
        this.state.switchingMode = ev.target.value;
        await this.loadMatrix();
    }

    markDirty() {
        this.state.dirty = true;
    }

    updateLotQty(row, field, value) {
        row[field] = Number(value) || 0;
        this.markDirty();
    }

    updateLotCode(row, level, value) {
        row.codes = row.codes || {};
        row.codes[level] = (value || "").toUpperCase();
        this.markDirty();
    }

    updatePlanCode(row, value) {
        row.sample_size_code = (value || "").toUpperCase();
        this.markDirty();
    }

    updatePlanSampleSize(row, value) {
        row.sample_size = Number(value) || 0;
        this.markDirty();
    }

    updatePlanCell(row, aqlKey, field, value) {
        row.cells = row.cells || {};
        row.cells[aqlKey] = row.cells[aqlKey] || {};
        row.cells[aqlKey][field] = value === "" ? "" : Number(value);
        this.markDirty();
    }

    addLotRow() {
        const previous = this.state.lotRows[this.state.lotRows.length - 1];
        const nextMin = previous ? Number(previous.lot_qty_max || 0) + 1 : 1;
        this.state.lotRows.push({
            lot_qty_min: nextMin,
            lot_qty_max: nextMin,
            codes: {},
        });
        this.markDirty();
    }

    removeLotRow(row) {
        const index = this.state.lotRows.indexOf(row);
        if (index >= 0) {
            this.state.lotRows.splice(index, 1);
            this.markDirty();
        }
    }

    addPlanRow() {
        this.state.planRows.push({
            sample_size_code: "",
            sample_size: 1,
            cells: {},
        });
        this.markDirty();
    }

    removePlanRow(row) {
        const index = this.state.planRows.indexOf(row);
        if (index >= 0) {
            this.state.planRows.splice(index, 1);
            this.markDirty();
        }
    }

    async saveMatrix() {
        if (!this.state.standardId) {
            this.notification.add(_t("Select a sampling standard before saving."), { type: "warning" });
            return;
        }
        this.state.saving = true;
        try {
            const data = await this.orm.call(
                "sn.wsd.quality.sampling.standard",
                "save_sampling_matrix_data",
                [
                    this.state.standardId,
                    this.state.switchingMode,
                    this.state.lotRows,
                    this.state.planRows,
                ]
            );
            this.applyData(data);
            this.state.dirty = false;
            this.notification.add(_t("Sampling matrix saved."), { type: "success" });
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add("sn_wsd_quality.sampling_matrix", SamplingMatrixAction);

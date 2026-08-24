/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, useState } from "@odoo/owl";

const TOOLING_ACTIONS = [
    { key: "online", label: _t("Put online") },
    { key: "offline", label: _t("Take offline") },
    { key: "issue", label: _t("Issue") },
    { key: "return_", label: _t("Return") },
    { key: "maintain_start", label: _t("Maintain start") },
    { key: "maintain_done", label: _t("Maintain done") },
    { key: "repair_start", label: _t("Repair start"), extra: "fault" },
    { key: "repair_done", label: _t("Repair done") },
    { key: "disable", label: _t("Disable"), extra: "reason" },
    { key: "enable", label: _t("Enable") },
    { key: "resolve", label: _t("Info") },
];

const CONSUMABLE_ACTIONS = [
    { key: "load", label: _t("Put online") },
    { key: "unload", label: _t("Take offline") },
    { key: "issue", label: _t("Issue") },
    { key: "return_", label: _t("Return") },
    { key: "thaw_start", label: _t("Thaw start") },
    { key: "thaw_end", label: _t("Thaw done") },
    { key: "stir_start", label: _t("Stir start") },
    { key: "stir_end", label: _t("Stir done") },
    { key: "exhaust", label: _t("Exhaust") },
    { key: "resolve", label: _t("Info") },
];

export class PdaEquipmentAction extends Component {
    static template = "sn_wsd_barcode.PdaEquipmentAction";
    static props = { ...standardActionServiceProps };

    setup() {
        this.action = useService("action");
        this.domain = this.props.action.context?.equipment_domain || "tooling";
        this.actions = this.domain === "tooling" ? TOOLING_ACTIONS : CONSUMABLE_ACTIONS;
        this.state = useState({
            selectedAction: false,
            extraValue: "",
            result: "",
            resultType: "info",
            detail: null,
            busy: false,
        });
        this.labels = {
            back: _t("Back"),
            title: this.domain === "tooling" ? _t("Tooling") : _t("Consumables"),
            scanHint: _t("Select an action, then scan the SN"),
            extra: _t("Extra info"),
        };
    }

    get selectedDef() {
        return this.actions.find((a) => a.key === this.state.selectedAction) || false;
    }

    pickAction(key) {
        this.state.selectedAction = key;
        this.state.extraValue = "";
        this.state.detail = null;
        this.setResult(this.labels.scanHint, "info");
    }

    setResult(message, type) {
        this.state.result = message;
        this.state.resultType = type || "info";
    }

    async onScan(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const sn = ev.target.value.trim();
        ev.target.value = "";
        if (!sn || !this.state.selectedAction || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const payload = { action: this.state.selectedAction, sn };
            if (this.selectedDef?.extra && this.state.extraValue) {
                payload[this.selectedDef.extra] = this.state.extraValue;
            }
            const res = await rpc(`/sn_wsd_barcode/pda/${this.domain}/call`, payload);
            this.state.detail = res.data || null;
            if (this.state.detail) {
                this.setResult(
                    `${this.state.detail.sn} · ${this.state.detail.state || ""}`,
                    res.ok ? "success" : "danger"
                );
            } else {
                this.setResult(res.message || "", res.ok ? "success" : "danger");
            }
        } finally {
            this.state.busy = false;
        }
    }

    goBack() {
        this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_action_main_menu");
    }
}

registry.category("actions").add("sn_wsd_barcode_pda_equipment_action", PdaEquipmentAction);

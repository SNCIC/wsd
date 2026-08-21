/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { View } from "@web/views/view";
import { Component, useState } from "@odoo/owl";

export class FeederCareAction extends Component {
    setup() {
        this.tabs = [
            {
                id: "pending_care",
                label: _t("Pending Care"),
                props: {
                    resModel: "sn.smt.feeder",
                    type: "list",
                    domain: [["care_state", "!=", "ok"]],
                    display: { controlPanel: true },
                },
            },
            {
                id: "repair",
                label: _t("Repair Records"),
                props: {
                    resModel: "sn.smt.feeder.repair",
                    type: "list",
                    display: { controlPanel: true },
                },
            },
            {
                id: "scrap",
                label: _t("Scrap Records"),
                props: {
                    resModel: "sn.smt.feeder.scrap",
                    type: "list",
                    display: { controlPanel: true },
                },
            },
            {
                id: "maintenance",
                label: _t("Maintenance Records"),
                props: {
                    resModel: "sn.smt.feeder.maintenance",
                    type: "list",
                    display: { controlPanel: true },
                },
            },
        ];
        this.state = useState({ activeTab: "pending_care" });
    }

    setActiveTab(tab) {
        this.state.activeTab = tab.id;
    }
}

FeederCareAction.template = "sn_wsd_smt.FeederCareAction";
FeederCareAction.components = { View };

registry.category("actions").add("sn_wsd_smt.feeder_care", FeederCareAction);

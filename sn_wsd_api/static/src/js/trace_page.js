/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useState } from "@odoo/owl";

export class SnTracePage extends Component {
    static template = "sn_wsd_api.TracePage";
    static components = { View };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            snInput: "",
            committedSn: "",
            summary: null,
            searching: false,
            listViewId: false,
        });
        this.labels = {
            trace: _t("Trace"),
            hint: _t("Scan or type an SN, press Enter to trace"),
            events: _t("events"),
            ng: _t("NG"),
            notFound: _t("No trace events found for this SN"),
        };
        onWillStart(async () => {
            const data = await this.orm.silent.call("ir.model.data", "search_read", [
                [
                    ["module", "=", "sn_wsd_api"],
                    ["model", "=", "ir.ui.view"],
                    ["name", "=", "view_sn_wsd_trace_event_list"],
                ],
            ], { fields: ["res_id"] });
            this.state.listViewId = (data[0] && data[0].res_id) || false;
        });
    }

    async onTrace() {
        const sn = (this.state.snInput || "").trim();
        if (!sn || this.state.searching) {
            return;
        }
        this.state.searching = true;
        this.state.summary = null;
        this.state.committedSn = "";
        const rows = await this.orm.silent.searchRead(
            "sn.wsd.trace.event",
            [["sn", "ilike", sn]],
            ["event_time", "result"],
            { limit: 5000, order: "event_time asc" },
        );
        // guard against rapid re-traces
        if ((this.state.snInput || "").trim() === sn) {
            this.state.committedSn = sn;
            this.state.summary = {
                count: rows.length,
                ng: rows.filter((r) => ["ng", "fail"].includes(r.result)).length,
                first: rows.length ? rows[0].event_time : "",
                last: rows.length ? rows[rows.length - 1].event_time : "",
            };
        }
        this.state.searching = false;
    }

    onKeydownInput(ev) {
        if (ev.key === "Enter") {
            this.onTrace();
        }
    }

    get traceDomain() {
        return [["sn", "ilike", this.state.committedSn]];
    }
}

registry.category("actions").add("sn_wsd_trace_page", SnTracePage);

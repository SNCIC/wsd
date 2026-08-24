/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onWillStart, useState } from "@odoo/owl";

export class SnWsdTestResultSplit extends Component {
    static template = "sn_wsd_api.TestResultSplit";
    static components = { View };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            selectedId: null,
            summary: null,
            viewIds: {},
        });
        this.onSelectRecord = (resId) => this.selectResult(resId);
        // template scope cannot call _t directly; precompute labels here
        this.labels = {
            openForm: _t("Open Full Form"),
            hint: _t("Click a test result above to view its item details"),
        };

        onWillStart(async () => {
            // resolve xmlids once; the embedded View component wants numeric ids
            const data = await this.orm.silent.call("ir.model.data", "search_read", [
                [
                    ["module", "=", "sn_wsd_api"],
                    ["model", "=", "ir.ui.view"],
                    [
                        "name",
                        "in",
                        [
                            "view_sn_wsd_test_result_list",
                            "view_sn_wsd_test_result_search",
                            "view_sn_wsd_test_result_detail_split_list",
                        ],
                    ],
                ],
            ], { fields: ["name", "res_id"] });
            for (const row of data) {
                this.state.viewIds[row.name] = row.res_id;
            }
        });
    }

    async selectResult(resId) {
        this.state.selectedId = resId;
        this.state.summary = null;
        const recs = await this.orm.silent.read("sn.wsd.mes.test.result", [resId], [
            "display_name",
            "result",
            "test_time",
            "serial_identity_id",
            "route_operation_id",
        ]);
        // guard against rapid re-clicks
        if (this.state.selectedId === resId && recs.length) {
            const r = recs[0];
            this.state.summary = {
                displayName: r.display_name,
                sn: r.serial_identity_id ? r.serial_identity_id[1] : "",
                operation: r.route_operation_id ? r.route_operation_id[1] : "",
                result: r.result,
                testTime: r.test_time,
            };
        }
    }

    openForm() {
        if (!this.state.selectedId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sn.wsd.mes.test.result",
            res_id: this.state.selectedId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    get listViewId() {
        return this.state.viewIds.view_sn_wsd_test_result_list || false;
    }

    get searchViewId() {
        return this.state.viewIds.view_sn_wsd_test_result_search || false;
    }

    get detailViewId() {
        return this.state.viewIds.view_sn_wsd_test_result_detail_split_list || false;
    }

    get topContext() {
        return this.props.action.context || {};
    }

    get detailDomain() {
        return [["test_result_id", "=", this.state.selectedId]];
    }
}

registry.category("actions").add("sn_wsd_test_result_split", SnWsdTestResultSplit);

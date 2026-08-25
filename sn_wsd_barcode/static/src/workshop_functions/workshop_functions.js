/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Component, onMounted, useState } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// 车间作业功能宫格：数据源 = ir.ui.menu 子树（后台可配 groups/sequence/
// active），点格子 doAction 到对应 client action。按当前用户组过滤后渲染。
export class WorkshopFunctionsMenu extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.WorkshopFunctionsMenu";

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            functions: [],
            ready: false,
        });
        onMounted(() => this._load());
    }

    async _load() {
        try {
            const data = await rpc("/sn_wsd_barcode/get_workshop_functions");
            this.state.functions = data.functions || [];
        } catch (error) {
            this.notification.add(error.message || _t("Failed to load functions."), {
                type: "danger",
            });
        } finally {
            this.state.ready = true;
        }
    }

    get title() {
        return _t("Workshop Operations");
    }

    get backLabel() {
        return _t("Back");
    }

    get emptyLabel() {
        return _t("No workshop function is assigned to you.");
    }

    goBack() {
        if (this.env.config.breadcrumbs.length > 1) {
            this.env.config.historyBack();
        } else {
            this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_action_main_menu");
        }
    }

    openFunction(fn) {
        if (!fn.action_id) {
            return;
        }
        this.action.doAction(fn.action_id);
    }
}

registry.category("actions").add("sn_wsd_barcode_workshop_functions", WorkshopFunctionsMenu);

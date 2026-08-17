/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * 保存 / 取消 button bar rendered right above the route title.
 *
 * Same semantics as the native top-bar buttons, made prominent where the user
 * works: 保存 = record.save() (the flow canvas is part of the record — the
 * server versions it), 取消 = record.discard() (nothing is saved; the flow
 * canvas redraws from the record through its own observer).
 */
export class RouteFormActions extends Component {
    static template = "sn_wsd_route_graph.RouteFormActions";

    setup() {
        this.notification = useService("notification");
    }

    get record() {
        return this.props.record;
    }

    get inEdition() {
        const rec = this.record;
        return Boolean(rec && rec.isInEdition);
    }

    async onClickSave() {
        const rec = this.record;
        if (!rec || !rec.save) return;
        try {
            await rec.save();
        } catch (e) {
            // Invalid required fields are highlighted on the form by the
            // record itself; a short toast keeps the cause visible.
            const reason = (e && (e.data?.message || e.message)) || "";
            this.notification.add(
                "保存失败: " + String(reason || "请检查必填项（名称/路线代码/车间）"),
                { type: "warning" });
        }
    }

    async onClickDiscard() {
        const rec = this.record;
        if (!rec || !rec.discard) return;
        const isNew = !rec.resId;
        try {
            await rec.discard();
        } catch (e) {
            this.notification.add("取消失败: " + String((e && e.message) || e), { type: "danger" });
            return;
        }
        if (isNew) {
            // A discarded new record has nothing to show — leave the form,
            // like the native 放弃所有更改 does.
            this.env.config?.historyBack?.();
        }
    }
}

registry.category("view_widgets").add("route_form_actions", { component: RouteFormActions });

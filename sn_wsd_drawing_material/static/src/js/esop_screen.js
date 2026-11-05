/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";

const SIDE_LABELS = {
    single: _t("Single"),
    top: _t("Top (T)"),
    bottom: _t("Bottom (B)"),
};

const TYPE_LABELS = {
    instruction: _t("Work Instruction"),
    drawing: _t("Drawing"),
    inspection: _t("Inspection Standard"),
    other: _t("Other"),
};

const UI_LABELS = {
    ackButton: _t("Acknowledge"),
    back: _t("Back"),
    clearSearch: _t("Clear"),
    loading: _t("Loading…"),
    noDocs: _t("No documents for this drawing number."),
    noInProduction: _t("No MES order in progress. Scan or type a drawing number to search."),
    refresh: _t("Refresh"),
    searchGo: _t("Search"),
    searchPlaceholder: _t("Scan or type a drawing number…"),
    title: _t("ESOP"),
    updatedTo: _t("Updated to"),
};

export class SnWsdEsopScreen extends Component {
    static template = "sn_wsd_drawing_material.EsopScreen";
    static props = standardActionServiceProps;

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.menu = useService("menu");
        this.notification = useService("notification");
        this.bus = useService("bus_service");
        this.state = useState({
            loading: false,
            search: "",
            companyId: null,
            canAck: false,
            cards: [],
            docs: [],
            viewing: false,
        });
        this.onBusNotification = () => {
            this.load();
        };
        this.onVisibilityChange = () => {
            // safety net for notifications missed while the tab was hidden
            if (document.visibilityState === "visible") {
                this.load();
            }
        };
        onWillStart(async () => {
            await this.load();
            // the payload tells us which company channel to join
            if (this.state.companyId) {
                await this.bus.addChannel(this.channel());
            }
            this.bus.subscribe("esop_refresh", this.onBusNotification);
        });
        onMounted(() => {
            document.addEventListener("visibilitychange", this.onVisibilityChange);
        });
        onWillUnmount(() => {
            document.removeEventListener("visibilitychange", this.onVisibilityChange);
            if (this.state.companyId) {
                this.bus.deleteChannel(this.channel());
            }
            this.bus.unsubscribe("esop_refresh", this.onBusNotification);
        });
    }

    get labels() {
        return UI_LABELS;
    }

    channel() {
        return `sn_wsd_drawing_material.esop_${this.state.companyId}`;
    }

    sideLabel(side) {
        return SIDE_LABELS[side] || side;
    }

    typeLabel(docType) {
        return TYPE_LABELS[docType] || docType;
    }

    get hasSearch() {
        return Boolean(this.state.search.trim());
    }

    get groupedDocs() {
        const groups = [];
        const byKey = new Map();
        for (const doc of this.state.docs) {
            const key = `${doc.operation}|${doc.side}`;
            if (!byKey.has(key)) {
                const group = {
                    key,
                    operation: doc.operation,
                    side: doc.side,
                    docs: [],
                };
                byKey.set(key, group);
                groups.push(group);
            }
            byKey.get(key).docs.push(doc);
        }
        return groups;
    }

    close() {
        // breadcrumbs include the screen itself: only go back when a
        // controller actually precedes us
        if ((this.env.config?.breadcrumbs || []).length > 1) {
            this.env.config.historyBack();
            return;
        }
        // entered from the ESOP menu or a fresh URL: land on the Shop
        // Floor app so the navbar shows its menus
        const apps = this.menu.getApps();
        const shopFloor = apps.find((app) => app.xmlid === "sn_wsd_workorder.menu_sn_wsd_shop_floor_root");
        if (shopFloor) {
            this.menu.selectMenu(shopFloor);
        } else {
            this.action.doAction("sn_wsd_mrp.action_sn_wsd_mes_orders");
        }
    }

    async load() {
        this.state.loading = true;
        try {
            const data = await this.orm.silent.call(
                "sn.wsd.esop.document", "esop_screen_data", [],
                { search: this.state.search });
            this.applyData(data);
        } finally {
            this.state.loading = false;
        }
    }

    applyData(data) {
        this.state.companyId = data.company_id;
        this.state.canAck = data.can_ack;
        this.state.cards = data.cards || [];
        this.state.docs = data.docs || [];
        // keep an open document fresh: swap in its latest payload so the
        // reversion banner can appear while the worker is reading
        if (this.state.viewing) {
            const fresh = this.state.docs.find(
                (doc) => doc.id === this.state.viewing.id);
            this.state.viewing = fresh || false;
        }
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.load();
        }
    }

    async clearSearch() {
        this.state.search = "";
        await this.load();
    }

    async openCard(card) {
        this.state.search = card.drawing;
        await this.load();
    }

    openDoc(doc) {
        this.state.viewing = doc;
    }

    closeDoc() {
        this.state.viewing = false;
    }

    async ackDoc(doc) {
        try {
            await this.orm.silent.call(
                "sn.wsd.esop.document", "esop_acknowledge", [[doc.id]]);
            doc.unacked = false;
        } catch (error) {
            this.notification.add(
                error?.data?.message || error?.message || String(error),
                { type: "danger" });
        }
    }

    toggleFullscreen() {
        if (document.fullscreenElement) {
            document.exitFullscreen?.();
        } else {
            document.documentElement.requestFullscreen?.();
        }
    }
}

registry.category("actions").add("sn_wsd_esop_screen", SnWsdEsopScreen);

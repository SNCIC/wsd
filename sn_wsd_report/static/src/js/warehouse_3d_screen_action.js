/** @odoo-module **/

import { Component, onMounted, onWillDestroy, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_SEC = 15;
const BODY_CLASS = "o_sn_wsd_w3d_fullscreen";
const BUNDLE = "sn_wsd_report.assets_warehouse_3d";

export class SnWsdWarehouse3DScreenAction extends Component {
    static template = "sn_wsd_report.Warehouse3DScreenAction";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.sceneRoot = useRef("sceneRoot");
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            autoRefresh: true,
            countdown: REFRESH_SEC,
            refreshedAt: null,
        });
        this.sceneApi = null;
        this._dataTimer = null;
        this._tickTimer = null;

        onWillStart(async () => {
            await loadBundle(BUNDLE);
            await this.loadData();
        });
        onMounted(() => {
            document.body.classList.add(BODY_CLASS);
            this.mountScene();
            this.startAutoRefresh();
            this.requestFullscreen();
        });
        onWillDestroy(() => {
            document.body.classList.remove(BODY_CLASS);
            this.stopAutoRefresh();
            this.destroyScene();
        });
    }

    /* ------------------------------------------------------------ 数据 */
    get data() {
        return this.state.data || {};
    }

    get kpis() {
        return this.data.kpis || [];
    }

    get order() {
        return this.data.order || null;
    }

    get stages() {
        return this.data.stages || [];
    }

    get tasks() {
        return this.data.tasks || [];
    }

    get currentTask() {
        return this.data.currentTask || null;
    }

    get warehouse() {
        return this.data.warehouse || {};
    }

    get user() {
        return this.data.user || {};
    }

    get sourceLabel() {
        const meta = this.data.meta || {};
        if (!meta.updated_at) {
            return "";
        }
        const date = new Date(meta.updated_at.endsWith("Z") ? meta.updated_at : `${meta.updated_at}Z`);
        const time = date.toLocaleTimeString("zh-CN", { hour12: false });
        const source = meta.source === "odoo" ? "实盘数据" : "演示数据";
        return `${source} · ${time}`;
    }

    async loadData() {
        try {
            this.state.data = await this.orm.call(
                "sn.wsd.warehouse.3d.screen.service",
                "get_screen_data",
                []
            );
            this.state.error = null;
            this.state.countdown = REFRESH_SEC;
            this.state.refreshedAt = new Date();
            if (this.sceneApi && this.state.data) {
                this.sceneApi.update(this.state.data);
            }
        } catch (error) {
            this.state.error = error.message || "数据加载失败";
            console.error("[仓库3D看板] 取数失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    /* ------------------------------------------------------------ 3D */
    mountScene() {
        const host = this.sceneRoot.el;
        if (!host) {
            return;
        }
        if (!window.SnWarehouse3D) {
            this.state.error = "3D 资源未加载，请刷新页面";
            return;
        }
        this.sceneApi = window.SnWarehouse3D.mount(host, { data: this.state.data });
    }

    destroyScene() {
        if (this.sceneApi) {
            this.sceneApi.destroy();
            this.sceneApi = null;
        }
    }

    resetView() {
        if (this.sceneApi) {
            this.sceneApi.resetView();
        }
    }

    /* ------------------------------------------------------------ 刷新 */
    startAutoRefresh() {
        this.stopAutoRefresh();
        if (!this.state.autoRefresh) {
            return;
        }
        this._tickTimer = setInterval(() => {
            this.state.countdown = this.state.countdown > 0 ? this.state.countdown - 1 : REFRESH_SEC;
        }, 1000);
        this._dataTimer = setInterval(() => this.loadData(), REFRESH_SEC * 1000);
    }

    stopAutoRefresh() {
        if (this._tickTimer) {
            clearInterval(this._tickTimer);
            this._tickTimer = null;
        }
        if (this._dataTimer) {
            clearInterval(this._dataTimer);
            this._dataTimer = null;
        }
    }

    toggleAutoRefresh() {
        this.state.autoRefresh = !this.state.autoRefresh;
        this.state.countdown = REFRESH_SEC;
        this.startAutoRefresh();
    }

    async manualRefresh() {
        await this.loadData();
        if (this.state.autoRefresh) {
            this.startAutoRefresh();
        }
    }

    requestFullscreen() {
        const element = document.documentElement;
        if (!element || document.fullscreenElement || !element.requestFullscreen) {
            return;
        }
        element.requestFullscreen().catch(() => {});
    }

    /* ------------------------------------------------------------ 展示辅助 */
    rowIcon(icon) {
        return {
            loc: "📍",
            box: "📦",
            doc: "📋",
            user: "👤",
            clock: "⏰",
        }[icon] || "•";
    }

    donutStyle(value) {
        const deg = Math.max(0, Math.min(100, value || 0)) * 3.6;
        return `background: conic-gradient(#00e5ff 0 ${deg}deg, rgba(0,229,255,.10) ${deg}deg 360deg);`;
    }

    stageStepClass(step) {
        return step.state === "active" ? "o_w3d_step o_w3d_step_active" : "o_w3d_step";
    }
}

registry.category("actions").add("sn_wsd_warehouse_3d_screen_action", SnWsdWarehouse3DScreenAction);

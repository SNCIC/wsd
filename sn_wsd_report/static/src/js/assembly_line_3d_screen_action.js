/** @odoo-module **/

import { Component, onMounted, onWillDestroy, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_SEC = 15;
const BODY_CLASS = "o_sn_wsd_al3d_fullscreen";
const BUNDLE = "sn_wsd_report.assets_assembly_line_3d";

export class SnWsdAssemblyLine3DScreenAction extends Component {
    static template = "sn_wsd_report.AssemblyLine3DScreenAction";
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

    get areas() {
        return this.data.areas || [];
    }

    get capacityTotal() {
        return this.areas.reduce((n, a) => n + (a.capacity || 0), 0);
    }

    get activeTotal() {
        return this.areas.reduce((n, a) => n + (a.active || 0), 0);
    }

    get product() {
        return this.data.product || null;
    }

    get line() {
        return this.data.line || {};
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
        const real = meta.real_areas || 0;
        const route = meta.route_areas || 0;
        const total = real + route + (meta.estimated_areas || 0);
        const kind = meta.source === "odoo" ? "实盘数据" : "演示数据";
        return `${kind} · ${time} · MES 数据 ${real + route}/${total} 工区（实采 ${real} · 台账 ${route}）· ${meta.test_records || 0} 条过站记录`;
    }

    get shiftLabel() {
        const meta = this.data.meta || {};
        return meta.shift_day ? `${meta.shift_day} 班次` : "当前班次";
    }

    async loadData() {
        try {
            this.state.data = await this.orm.call(
                "sn.wsd.assembly.line.3d.screen.service",
                "get_screen_data",
                []
            );
            this.state.error = null;
            this.state.countdown = REFRESH_SEC;
            if (this.sceneApi && this.state.data) {
                this.sceneApi.update(this.state.data);
            }
        } catch (error) {
            this.state.error = error.message || "数据加载失败";
            console.error("[整机自动线看板] 取数失败", error);
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
        if (!window.SnAssemblyLine3D) {
            this.state.error = "3D 资源未加载，请刷新页面";
            return;
        }
        this.sceneApi = window.SnAssemblyLine3D.mount(host, { data: this.state.data });
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
    stationClass(station) {
        return `o_al3d_station o_al3d_ss_${station.status}`;
    }

    areaClass(area) {
        return `o_al3d_arow o_al3d_ss_${area.status}`;
    }

    stepClass(step) {
        return `o_al3d_step o_al3d_step_${step.state}`;
    }

    donutStyle(value) {
        const deg = Math.max(0, Math.min(100, value || 0)) * 3.6;
        return `background: conic-gradient(#00e5ff 0 ${deg}deg, rgba(0,229,255,.10) ${deg}deg 360deg);`;
    }

    barStyle(percent) {
        return `width:${Math.max(0, Math.min(100, percent || 0))}%`;
    }
}

registry.category("actions").add("sn_wsd_assembly_line_3d_screen_action", SnWsdAssemblyLine3DScreenAction);

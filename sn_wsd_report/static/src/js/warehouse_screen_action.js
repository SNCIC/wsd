/** @odoo-module */

import { Component, onMounted, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_INTERVAL_SEC = 60;
const BODY_FULLSCREEN_CLASS = "o_sn_wsd_warehouse_screen_fullscreen";

export class SnWsdWarehouseScreenAction extends Component {
    static template = "sn_wsd_report.WarehouseScreenAction";
    static components = { Layout };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            data: null,
            autoRefresh: false,
            countdown: REFRESH_INTERVAL_SEC,
            refreshing: false,
        });
        this.filters = useState({
            warehouseId: "",
            categoryId: "",
            dateFrom: "",
            dateTo: "",
        });
        this._refreshTimer = null;
        this._countdownTimer = null;
        onWillStart(async () => {
            await this.loadData();
        });
        onMounted(() => {
            document.body.classList.add(BODY_FULLSCREEN_CLASS);
        });
        onWillDestroy(() => {
            document.body.classList.remove(BODY_FULLSCREEN_CLASS);
            this.stopAutoRefresh();
        });
    }

    get summary() {
        return this.state.data?.summary || {};
    }

    get issueLines() {
        return this.state.data?.issue_lines || [];
    }

    get gainRows() {
        return this.state.data?.gain_rows || [];
    }

    get lossRows() {
        return this.state.data?.loss_rows || [];
    }

    get operationStats() {
        return this.state.data?.operation_stats || [];
    }

    get latestOperations() {
        return this.state.data?.latest_operations || [];
    }

    get warehouses() {
        return this.state.data?.filter_options?.warehouses || [];
    }

    get categories() {
        return this.state.data?.filter_options?.categories || [];
    }

    get filterKwargs() {
        return {
            warehouse_id: this.filters.warehouseId || null,
            category_id: this.filters.categoryId || null,
            date_from: this.filters.dateFrom || null,
            date_to: this.filters.dateTo || null,
        };
    }

    async loadData() {
        this.state.refreshing = true;
        try {
            this.state.data = await this.orm.call(
                "sn.wsd.warehouse.dashboard.service",
                "get_warehouse_screen_data",
                [],
                this.filterKwargs
            );
            this.state.countdown = REFRESH_INTERVAL_SEC;
        } finally {
            this.state.loading = false;
            this.state.refreshing = false;
        }
    }

    async applyFilters() {
        await this.loadData();
    }

    async resetFilters() {
        this.filters.warehouseId = "";
        this.filters.categoryId = "";
        this.filters.dateFrom = "";
        this.filters.dateTo = "";
        await this.loadData();
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        if (!this.state.autoRefresh) {
            return;
        }
        this._countdownTimer = setInterval(() => {
            this.state.countdown = this.state.countdown > 0 ? this.state.countdown - 1 : REFRESH_INTERVAL_SEC;
        }, 1000);
        this._refreshTimer = setInterval(async () => {
            await this.loadData();
        }, REFRESH_INTERVAL_SEC * 1000);
    }

    stopAutoRefresh() {
        if (this._refreshTimer) {
            clearInterval(this._refreshTimer);
            this._refreshTimer = null;
        }
        if (this._countdownTimer) {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        }
    }

    toggleAutoRefresh() {
        this.state.autoRefresh = !this.state.autoRefresh;
        this.state.countdown = REFRESH_INTERVAL_SEC;
        this.startAutoRefresh();
    }

    async manualRefresh() {
        await this.loadData();
        if (this.state.autoRefresh) {
            this.startAutoRefresh();
        }
    }

    opStatClass(code) {
        const stat = this.operationStats.find((item) => item.code === code);
        if (!stat) {
            return "o_op_normal";
        }
        if (stat.active_count > 0 && code === "inventory") {
            return "o_op_warning";
        }
        return stat.active_count > 0 ? "o_op_active" : "o_op_normal";
    }

    stateClass(state) {
        if (state === "done") {
            return "o_state_done";
        }
        if (state === "cancel") {
            return "o_state_cancel";
        }
        if (state === "assigned") {
            return "o_state_ready";
        }
        return "o_state_pending";
    }

    formatNumber(value, digits = 0) {
        const number = Number(value || 0);
        return number.toLocaleString(undefined, {
            maximumFractionDigits: digits,
            minimumFractionDigits: 0,
        });
    }

    formatTime(value) {
        if (!value) {
            return "-";
        }
        return String(value).slice(5, 16).replace("T", " ");
    }
}

registry.category("actions").add("sn_wsd_warehouse_screen_action", SnWsdWarehouseScreenAction);

/** @odoo-module **/
// 工位终端：开工 / 暂停 / 继续 / 完工计时（继承补丁，不改原终端文件）
import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount, useState } from "@odoo/owl";
import { SnWsdShopFloor } from "@sn_wsd_workorder/js/shop_floor";

const STATE_LABEL = { running: "计时中", paused: "已暂停" };

patch(SnWsdShopFloor.prototype, {
    setup() {
        super.setup(...arguments);
        this.snClock = useState({ now: Date.now(), loadedAt: Date.now(), timers: {} });
        let handle = null;
        onMounted(() => {
            handle = setInterval(() => { this.snClock.now = Date.now(); }, 1000);
        });
        onWillUnmount(() => handle && clearInterval(handle));
    },

    applyStationData(data) {
        super.applyStationData(...arguments);
        this.snClock.timers = (data && data.sn_timers) || {};
        this.snClock.loadedAt = Date.now();
    },

    snTimer(order) {
        return order ? this.snClock.timers[String(order.id)] || false : false;
    },

    snTimerStateLabel(order) {
        const t = this.snTimer(order);
        return t ? STATE_LABEL[t.state] || "" : "未开工";
    },

    snElapsed(order) {
        const t = this.snTimer(order);
        let secs = t ? t.seconds : 0;
        if (t && t.state === "running") {
            secs += Math.max(0, Math.floor((this.snClock.now - this.snClock.loadedAt) / 1000));
        }
        const pad = (n) => String(n).padStart(2, "0");
        return `${pad(Math.floor(secs / 3600))}:${pad(Math.floor((secs % 3600) / 60))}:${pad(secs % 60)}`;
    },

    async snTimerAction(order, action) {
        try {
            const data = await this.orm.call("sn.wsd.work.timer", "terminal_timer_action", [
                order.id, this.state.station.workcenterId, action,
            ]);
            this.applyStationData(data);
        } catch (error) {
            this.notification.add(error?.data?.message || error?.message || String(error),
                { type: "danger" });
        }
    },
});

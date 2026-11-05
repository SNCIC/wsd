/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, useState } from "@odoo/owl";

const round4 = (v) => Math.round(v * 10000) / 10000;

/** Normalize weights to ratios summing to exactly 100 (last absorbs). */
export function distributeRatios(weights) {
    const total = weights.reduce((a, b) => a + b, 0);
    const ratios = total <= 0
        ? weights.map(() => 100.0 / weights.length)
        : weights.map((w) => (w / total) * 100.0);
    const result = ratios.slice(0, -1).map(round4);
    result.push(round4(100.0 - result.reduce((a, b) => a + b, 0.0)));
    return result;
}

export class DailyWorkbench extends Component {
    static template = "sn_wsd_piece_rate.DailyWorkbench";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            lines: [],
            teams: [],
            scrapReasons: [],
            filters: { workshop: "", line: "", order: "" },
            workshops: [],
            linesList: [],
            // searchable order picker: allOrders accumulates across
            // snapshots (a filtered reload must not shrink the choices),
            // orderTerm/orderSuggestions drive the type-to-filter dropdown
            allOrders: [],
            orderTerm: "",
            orderSuggestions: [],
            selectedId: null,
            error: "",
            notice: "",
            submitting: false,
            addTerm: "",
            addSuggestions: [],
        });
        this.labels = {
            title: _t("Daily Reporting"),
            submit: _t("Submit Reports"),
            workshop: _t("Workshop"),
            productionLine: _t("Production Line"),
            mesOrder: _t("MES Order"),
            all: _t("All"),
            searchPlaceholder: _t("Type to search..."),
            operation: _t("Operation"),
            reported: _t("Reported"),
            remaining: _t("Remaining"),
            locked: _t("Sequence Locked"),
            unitPrice: _t("Unit Price"),
            newUnitPrice: _t("New Unit Price"),
            allocation: _t("Allocation"),
            qtyOk: _t("OK Quantity"),
            qtyNg: _t("NG Quantity"),
            qtyScrap: _t("Scrap Quantity"),
            scrapReason: _t("Scrap Reason"),
            team: _t("Team"),
            fillFromTeam: _t("Fill From Team"),
            equalSplit: _t("Equal Split"),
            participants: _t("Participants"),
            employee: _t("Employee"),
            employeeCode: _t("Employee Code"),
            ratio: _t("Performance Ratio"),
            ratioLocked: _t("Ratio Locked"),
            ratioTotal: _t("Ratio Total"),
            addParticipant: _t("Add participant..."),
            pickLineHint: _t("Click a row to record its batch below."),
            noLines: _t("No active report-mode orders match the filters."),
            capReached: _t("Ratio capped: the total cannot exceed 100%."),
        };
        this.load();
    }

    get selectedLine() {
        return this.state.lines.find(
            (l) => l.route_operation_id === this.state.selectedId) || null;
    }

    // ------------------------------------------------------------------
    // data
    // ------------------------------------------------------------------

    async load() {
        this.state.loading = true;
        this.state.error = "";
        const f = this.state.filters;
        const data = await this.orm.silent.call(
            "sn.wsd.piece.settlement.generate.wizard", "get_workbench_data", [], {
                workshop_id: f.workshop ? Number(f.workshop) : false,
                production_line_id: f.line ? Number(f.line) : false,
                mes_order_id: f.order ? Number(f.order) : false,
            });
        this.state.lines = data.lines;
        this.state.teams = data.teams;
        this.state.scrapReasons = data.scrap_reasons;
        // distinct picker options from the snapshot (orders already filtered)
        const workshops = new Map();
        const lines = new Map();
        for (const line of data.lines) {
            if (line.workshop) {
                workshops.set(line.workshop, line.workshop);
            }
            if (line.production_line) {
                lines.set(line.production_line, line.production_line);
            }
        }
        this.state.workshops = [...workshops.values()].map((n) => ({
            name: n,
        }));
        this.state.linesList = [...lines.values()].map((n) => ({ name: n }));
        this.mergeOrders(data);
        if (this.state.selectedId
                && !data.lines.some(
                    (l) => l.route_operation_id === this.state.selectedId)) {
            this.state.selectedId = null;
        }
        this.state.loading = false;
    }

    /** Accumulate the order choices across snapshots: once an order has
     * been seen it stays pickable even when the current filter narrows the
     * table down to a single order (recent first). */
    mergeOrders(data) {
        const map = new Map(
            this.state.allOrders.map((o) => [o.id, o.name]));
        for (const line of data.lines) {
            map.set(line.mes_order_id, line.order_name);
        }
        this.state.allOrders = [...map.entries()]
            .map(([id, name]) => ({ id, name }))
            .sort((a, b) => b.id - a.id);
    }

    // ------------------------------------------------------------------
    // searchable order filter (type to filter, click to apply)
    // ------------------------------------------------------------------

    onOrderTerm(ev) {
        this.state.orderTerm = ev.target.value;
        const term = this.state.orderTerm.trim().toLowerCase();
        if (!term) {
            this.state.orderSuggestions = [];
            if (this.state.filters.order) {
                this.state.filters.order = "";
                this.onFilterChange();
            }
            return;
        }
        this.state.orderSuggestions = this.state.allOrders
            .filter((o) => o.name.toLowerCase().includes(term))
            .slice(0, 10);
    }

    pickOrder(order) {
        this.state.filters.order = String(order.id);
        this.state.orderTerm = order.name;
        this.state.orderSuggestions = [];
        this.onFilterChange();
    }

    hideOrderSuggestions() {
        this.state.orderSuggestions = [];
    }

    async onFilterChange() {
        // name-based pickers: keep them loose (server re-filters on reload)
        const f = this.state.filters;
        const data = await this.orm.silent.call(
            "sn.wsd.piece.settlement.generate.wizard",
            "get_workbench_data", [], {
                workshop_id: false,
                production_line_id: false,
                mes_order_id: f.order ? Number(f.order) : false,
            });
        const term = (f.workshop || "").toLowerCase();
        const lineTerm = (f.line || "").toLowerCase();
        const filtered = data.lines.filter((l) =>
            (!term || (l.workshop || "").toLowerCase().includes(term))
            && (!lineTerm
                || (l.production_line || "").toLowerCase()
                    .includes(lineTerm)));
        this.state.lines = filtered;
        this.state.teams = data.teams;
        this.state.scrapReasons = data.scrap_reasons;
        this.mergeOrders(data);
        if (this.state.selectedId
                && !filtered.some(
                    (l) => l.route_operation_id === this.state.selectedId)) {
            this.state.selectedId = null;
        }
    }

    // ------------------------------------------------------------------
    // selection + quantities
    // ------------------------------------------------------------------

    selectLine(line) {
        this.state.selectedId = line.route_operation_id;
        this.state.addTerm = "";
        this.state.addSuggestions = [];
    }

    setQty(line, field, ev) {
        line[field] = parseFloat(ev.target.value) || 0.0;
    }

    setPrice(line, ev) {
        line.x_new_price = parseFloat(ev.target.value) || 0.0;
    }

    // ------------------------------------------------------------------
    // crew: explicit locks, live equal split of the remainder
    // ------------------------------------------------------------------

    ratioTotal(line) {
        return round4(line.participants.reduce(
            (a, p) => a + (p.performance_ratio || 0), 0));
    }

    /** Typing a ratio fixes that row for this action; the OTHER unlocked
     * rows immediately equal-split the remainder (total never exceeds
     * 100 -- the typed value is capped first when needed). */
    onRatioInput(line, participant, ev) {
        let value = parseFloat(ev.target.value) || 0.0;
        const othersLocked = line.participants.reduce(
            (a, p) => (p !== participant && p.x_ratio_locked
                ? a + (p.performance_ratio || 0) : a), 0);
        const cap = round4(100 - othersLocked);
        if (value > cap) {
            value = Math.max(cap, 0);
            this.notify(this.labels.capReached, "warning");
        }
        if (value < 0) {
            value = 0;
        }
        participant.performance_ratio = round4(value);
        this.rebalance(line, [participant]);
    }

    /** Equal-split `100 - sum(locked)` between the unlocked rows,
     * excluding the given fixed rows; last absorbs the remainder. */
    rebalance(line, fixed = []) {
        const lockedSum = line.participants.reduce(
            (a, p) => (p.x_ratio_locked || fixed.includes(p)
                ? a + (p.performance_ratio || 0) : a), 0);
        const auto = line.participants.filter(
            (p) => !p.x_ratio_locked && !fixed.includes(p));
        if (!auto.length) {
            return;
        }
        const remaining = Math.max(100 - lockedSum, 0);
        const share = round4(remaining / auto.length);
        auto.forEach((p, i) => {
            p.performance_ratio = i < auto.length - 1
                ? share
                : round4(100 - lockedSum - share * (auto.length - 1));
        });
    }

    toggleLock(line, participant) {
        participant.x_ratio_locked = !participant.x_ratio_locked;
        this.rebalance(line);
    }

    equalSplit(line) {
        const n = line.participants.length;
        if (!n) {
            return;
        }
        const ratios = distributeRatios(new Array(n).fill(1));
        line.participants.forEach((p, i) => {
            p.x_ratio_locked = false;
            p.performance_ratio = ratios[i];
        });
    }

    fillFromTeam(line) {
        const team = this.state.teams.find((t) => t.id === line.team_id);
        if (!team || !team.members.length) {
            return;
        }
        const ratios = distributeRatios(team.members.map((m) => m.weight));
        line.participants = team.members.map((m, i) => ({
            employee_id: m.employee_id,
            employee_name: m.employee_name,
            employee_code: m.employee_code,
            performance_ratio: ratios[i],
            x_ratio_locked: false,
        }));
    }

    onTeamChange(line, ev) {
        line.team_id = ev.target.value ? Number(ev.target.value) : false;
        line.team_name = (this.state.teams.find(
            (t) => t.id === line.team_id) || {}).name || "";
    }

    removeParticipant(line, participant) {
        line.participants = line.participants.filter(
            (p) => p !== participant);
        this.rebalance(line);
    }

    async onAddTerm(line, ev) {
        this.state.addTerm = ev.target.value;
        if (this.state.addTerm.length < 1) {
            this.state.addSuggestions = [];
            return;
        }
        const results = await this.orm.silent.call(
            "hr.employee", "name_search", [this.state.addTerm], {
                limit: 8,
            });
        this.state.addSuggestions = results.map(([id, name]) => ({
            id, name,
        }));
    }

    addParticipant(line, suggestion) {
        if (!line.participants.some(
                (p) => p.employee_id === suggestion.id)) {
            line.participants.push({
                employee_id: suggestion.id,
                employee_name: suggestion.name,
                employee_code: "",
                performance_ratio: 0.0,
                x_ratio_locked: false,
            });
            this.rebalance(line);
        }
        this.state.addTerm = "";
        this.state.addSuggestions = [];
    }

    // ------------------------------------------------------------------
    // submit
    // ------------------------------------------------------------------

    async submit() {
        if (this.state.submitting) {
            return;
        }
        const batch = this.state.lines.filter(
            (l) => l.qty_ok > 0 || l.qty_ng > 0 || l.qty_scrap > 0);
        if (!batch.length) {
            this.notify(_t("Enter at least one positive quantity."), "warning");
            return;
        }
        this.state.submitting = true;
        this.state.error = "";
        try {
            const count = await this.orm.call(
                "sn.wsd.piece.settlement.generate.wizard",
                "submit_workbench", [batch]);
            this.notification.add(
                _t("%s operation report(s) submitted.",
                    String(count)), { type: "success" });
            await this.load();
        } catch (error) {
            this.state.error = error?.data?.message
                || error?.message || String(error);
        } finally {
            this.state.submitting = false;
        }
    }

    notify(message, type) {
        this.notification.add(message, { type });
    }
}

registry.category("actions").add("sn_wsd_piece_daily_workbench",
    DailyWorkbench);

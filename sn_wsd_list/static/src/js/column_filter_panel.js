/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { Component, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import {
    formatValueLabel,
    isRangeType,
    rawValueKey,
} from "./column_filter_utils";

const PAGE_SIZE = 100;
const APPLY_DELAY = 350;
const SEARCH_DELAY = 300;
// Field types for which the value list can be searched on the server. Other
// types either have few values (selection, boolean) or are filtered through a
// range (numbers, dates).
const SERVER_SEARCH_TYPES = ["char", "text", "many2one"];

function toISODate(date) {
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
}

export class ColumnFilterPanel extends Component {
    static template = "sn_wsd_list.ColumnFilterPanel";
    static props = {
        column: Object,
        field: Object,
        filter: Object,
        resModel: String,
        list: Object,
        isRootList: Boolean,
        getBaseDomain: Function,
        applyFilter: Function,
        clearFilter: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.applyTimer = null;
        this.searchTimer = null;
        // Incremented on each (re)load to discard the responses of previous
        // searches.
        this.loadToken = 0;
        const filter = this.props.filter || {};
        this.state = useState({
            mode: filter.mode === "exclude" ? "exclude" : "include",
            selected: [...(filter.values || [])],
            valueLabels: { ...(filter.valueLabels || {}) },
            empty: Boolean(filter.empty),
            nonEmpty: Boolean(filter.nonEmpty),
            from: filter.from || "",
            to: filter.to || "",
            search: filter.search || "",
            groups: [],
            loading: false,
            hasMore: false,
            offset: 0,
        });
        onWillStart(() => {
            if (!this.isRange) {
                return this.loadValues(true);
            }
            return Promise.resolve();
        });
        onWillDestroy(() => {
            browser.clearTimeout(this.applyTimer);
            browser.clearTimeout(this.searchTimer);
        });
    }

    get labels() {
        return {
            search: _t("Search"),
            empty: _t("(empty)"),
            nonEmpty: _t("(not empty)"),
            emptyHelp: _t("Records without a value for this column"),
            nonEmptyHelp: _t("Records with a value for this column"),
            include: _t("Include"),
            exclude: _t("Exclude"),
            clear: _t("Clear"),
            apply: _t("Apply"),
            loadMore: _t("Load more"),
            noResults: _t("No results"),
            keywordHint: _t("Apply to filter on this keyword"),
            today: _t("Today"),
            thisMonth: _t("This Month"),
            thisYear: _t("This Year"),
        };
    }

    get shouldSearchOnServer() {
        return this.props.isRootList && SERVER_SEARCH_TYPES.includes(this.fieldType);
    }

    getSearchDomain() {
        const search = this.state.search.trim();
        if (!search || !this.shouldSearchOnServer) {
            return [];
        }
        return [[this.props.column.name, "ilike", search]];
    }

    get fieldType() {
        return this.props.field.type;
    }

    get isRange() {
        return isRangeType(this.fieldType);
    }

    get inputType() {
        if (this.fieldType === "date") {
            return "date";
        }
        if (this.fieldType === "datetime") {
            return "datetime-local";
        }
        return "number";
    }

    get showQuickRanges() {
        return this.fieldType === "date" || this.fieldType === "datetime";
    }

    get visibleGroups() {
        const search = this.state.search.trim().toLowerCase();
        const groups = search
            ? this.state.groups.filter((group) =>
                  String(group.label).toLowerCase().includes(search)
              )
            : this.state.groups;
        // Keep the selected values visible even when they are not part of the
        // loaded/search results, so that they can still be unchecked.
        const shownKeys = new Set(groups.map((group) => group.key));
        const missingSelected = this.state.selected
            .filter((key) => !shownKeys.has(key) && key in this.state.valueLabels)
            .map((key) => ({ key, label: this.state.valueLabels[key], count: 0 }));
        return [...missingSelected, ...groups];
    }

    isSelected(key) {
        return this.state.selected.includes(key);
    }

    async loadValues(reset) {
        if (this.state.loading && !reset) {
            return;
        }
        const token = ++this.loadToken;
        if (reset) {
            this.state.offset = 0;
            this.state.groups = [];
        }
        this.state.loading = true;
        try {
            let groups;
            let loadedCount;
            let hasMore = false;
            if (this.props.isRootList) {
                const result = await this.orm.webReadGroup(
                    this.props.resModel,
                    [...this.props.getBaseDomain(), ...this.getSearchDomain()],
                    [this.props.column.name],
                    ["__count"],
                    { limit: PAGE_SIZE, offset: this.state.offset }
                );
                if (token !== this.loadToken) {
                    return; // a more recent search superseded this one
                }
                const rawGroups = result.groups || [];
                groups = this.normalizeGroups(rawGroups);
                loadedCount = rawGroups.length;
                hasMore = loadedCount === PAGE_SIZE;
            } else {
                groups = this.getLocalGroups();
                loadedCount = groups.length;
                hasMore = false;
            }
            this.state.groups = reset ? groups : [...this.state.groups, ...groups];
            this.state.hasMore = hasMore;
            if (this.props.isRootList) {
                this.state.offset += loadedCount;
            }
        } finally {
            if (token === this.loadToken) {
                this.state.loading = false;
            }
        }
    }

    /**
     * Search is applied on the server side when possible: the value list only
     * contains the first page of values, so filtering locally would miss the
     * values that are not loaded yet.
     */
    onSearchInput(ev) {
        this.state.search = ev.target.value;
        browser.clearTimeout(this.searchTimer);
        this.searchTimer = browser.setTimeout(() => {
            if (this.shouldSearchOnServer) {
                this.loadValues(true);
            }
        }, SEARCH_DELAY);
    }

    normalizeGroups(rawGroups) {
        const fieldName = this.props.column.name;
        const groups = [];
        for (const group of rawGroups) {
            const raw = group[fieldName];
            if (raw === false || raw === null || raw === undefined) {
                continue;
            }
            const key = this.fieldType === "many2one" ? raw[0] : raw;
            groups.push({
                key,
                label: formatValueLabel(raw, this.props.field, this.fieldType),
                count: group.__count || 0,
            });
        }
        return groups;
    }

    getLocalGroups() {
        const fieldName = this.props.column.name;
        const counts = new Map();
        const labels = new Map();
        for (const record of this.props.list.records) {
            const value = record.data[fieldName];
            const key = rawValueKey(value, this.fieldType);
            if (key === false || key === null || key === undefined || key === "") {
                continue;
            }
            counts.set(key, (counts.get(key) || 0) + 1);
            if (!labels.has(key)) {
                labels.set(key, formatValueLabel(value, this.props.field, this.fieldType));
            }
        }
        return [...counts.entries()].map(([key, count]) => ({
            key,
            label: labels.get(key),
            count,
        }));
    }

    toggleValue(key, label) {
        const index = this.state.selected.indexOf(key);
        if (index >= 0) {
            this.state.selected.splice(index, 1);
            delete this.state.valueLabels[key];
        } else {
            this.state.selected.push(key);
            this.state.valueLabels[key] = label;
        }
        this.scheduleApply();
    }

    toggleSpecial(kind) {
        this.state[kind] = !this.state[kind];
        this.scheduleApply();
    }

    setRange(key, value) {
        this.state[key] = value;
        this.scheduleApply();
    }

    setMode(mode) {
        this.state.mode = mode;
        this.scheduleApply();
    }

    setQuickRange(kind, ev) {
        ev.stopPropagation();
        const today = new Date();
        let from = today;
        let to = today;
        if (kind === "month") {
            from = new Date(today.getFullYear(), today.getMonth(), 1);
            to = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        } else if (kind === "year") {
            from = new Date(today.getFullYear(), 0, 1);
            to = new Date(today.getFullYear(), 11, 31);
        }
        if (this.fieldType === "datetime") {
            this.state.from = `${toISODate(from)}T00:00`;
            this.state.to = `${toISODate(to)}T23:59`;
        } else {
            this.state.from = toISODate(from);
            this.state.to = toISODate(to);
        }
        this.scheduleApply();
    }

    scheduleApply() {
        browser.clearTimeout(this.applyTimer);
        this.applyTimer = browser.setTimeout(() => this.applyNow(), APPLY_DELAY);
    }

    applyNow() {
        browser.clearTimeout(this.applyTimer);
        this.applyTimer = null;
        this.props.applyFilter({
            mode: this.state.mode,
            values: [...this.state.selected],
            valueLabels: { ...this.state.valueLabels },
            empty: this.state.empty,
            nonEmpty: this.state.nonEmpty,
            from: this.state.from,
            to: this.state.to,
            search: this.state.search.trim(),
        });
    }

    onClose() {
        this.applyNow();
        this.props.close();
    }

    onClear() {
        browser.clearTimeout(this.applyTimer);
        this.applyTimer = null;
        this.props.clearFilter();
        this.props.close();
    }

    onLoadMore() {
        return this.loadValues(false);
    }
}

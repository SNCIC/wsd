/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { SearchModel } from "@web/search/search_model";
import {
    buildFilterDescription,
    buildFilterDomain,
    isEmptyFilter,
} from "./column_filter_utils";

const STATE_PREFIX = "sn_wsd_list.columnFilters";

/**
 * Column filters are stored on the search model and exposed as regular "filter"
 * search items, so that they take part in the search domain, are displayed as
 * facets in the search bar and are saved within favorites.
 */
patch(SearchModel.prototype, {
    setup() {
        super.setup(...arguments);
        this.columnFilters = {};
        this.columnFilterItems = {};
        this._columnFiltersRestored = false;
        // Do not touch the storage before the session filters have been restored,
        // otherwise the initial load would erase them.
        this._columnFiltersReady = false;
    },

    async load(config) {
        await super.load(config);
        this._restoreColumnFilters();
    },

    /**
     * Apply (or replace) the filter of a column.
     *
     * @param {string} fieldName
     * @param {Object} filter
     */
    setColumnFilter(fieldName, filter) {
        if (!filter || isEmptyFilter(filter)) {
            this.clearColumnFilter(fieldName);
            return;
        }
        this._registerColumnFilter(fieldName, filter);
        this._saveColumnFilters();
        this._notify();
    },

    /**
     * Remove the filter of a column.
     *
     * @param {string} fieldName
     */
    clearColumnFilter(fieldName) {
        this._unregisterColumnFilter(fieldName);
        this._saveColumnFilters();
        this._notify();
    },

    /**
     * Domain of the current search, ignoring the filter of the given column.
     * Used to compute the candidate values of that column.
     *
     * @param {string} fieldName
     * @returns {Array}
     */
    getColumnFilterBaseDomain(fieldName) {
        const item = this.columnFilterItems[fieldName];
        if (!item) {
            return this.domain;
        }
        const query = this.query;
        this.query = this.query.filter((elem) => elem.searchItemId !== item.searchItemId);
        this._reset();
        const domain = this.domain;
        this.query = query;
        this._reset();
        return domain;
    },

    _registerColumnFilter(fieldName, filter) {
        const field = this.searchViewFields[fieldName] || {};
        const domain = buildFilterDomain(fieldName, field.type || "char", filter);
        if (!domain) {
            this._unregisterColumnFilter(fieldName);
            return;
        }
        const description = buildFilterDescription(field.string || fieldName, filter);
        let item = this.columnFilterItems[fieldName];
        if (!item) {
            const searchItemId = this.nextId++;
            const groupId = this.nextGroupId++;
            this.searchItems[searchItemId] = {
                id: searchItemId,
                type: "filter",
                description,
                domain: "",
                context: {},
                groupId,
                groupNumber: this.nextGroupNumber++,
                isDefault: false,
            };
            item = this.columnFilterItems[fieldName] = { searchItemId, groupId };
            this.query.push({ searchItemId });
        }
        const searchItem = this.searchItems[item.searchItemId];
        searchItem.description = description;
        searchItem.domain = new Domain(domain).toString();
        this.columnFilters[fieldName] = filter;
    },

    _unregisterColumnFilter(fieldName) {
        const item = this.columnFilterItems[fieldName];
        if (item) {
            this.query = this.query.filter((elem) => elem.searchItemId !== item.searchItemId);
            delete this.searchItems[item.searchItemId];
            delete this.columnFilterItems[fieldName];
        }
        delete this.columnFilters[fieldName];
    },

    get _columnFilterStateKey() {
        const db = session.db || "default";
        const actionId = this.env.config.actionId || "none";
        return `${STATE_PREFIX}.${db}.${actionId}.${this.resModel || "none"}`;
    },

    _saveColumnFilters() {
        if (!this._columnFiltersReady) {
            return;
        }
        try {
            if (Object.keys(this.columnFilters).length) {
                browser.sessionStorage.setItem(
                    this._columnFilterStateKey,
                    JSON.stringify(this.columnFilters)
                );
            } else {
                browser.sessionStorage.removeItem(this._columnFilterStateKey);
            }
        } catch {
            // Ignore storage quota/access errors.
        }
    },

    _restoreColumnFilters() {
        if (this._columnFiltersRestored || !this.resModel) {
            return;
        }
        this._columnFiltersRestored = true;
        let saved = null;
        try {
            saved = JSON.parse(browser.sessionStorage.getItem(this._columnFilterStateKey) || "null");
        } catch {
            saved = null;
        }
        this._columnFiltersReady = true;
        if (!saved || typeof saved !== "object") {
            return;
        }
        let hasFilter = false;
        for (const [fieldName, filter] of Object.entries(saved)) {
            if (!(fieldName in this.searchViewFields) || isEmptyFilter(filter)) {
                continue;
            }
            this._registerColumnFilter(fieldName, filter);
            hasFilter = hasFilter || Boolean(this.columnFilterItems[fieldName]);
        }
        if (hasFilter) {
            this._reset();
            this.trigger("update");
        }
    },

    /**
     * Drop column filters whose facet has been removed from the search bar.
     */
    _pruneColumnFilters() {
        for (const fieldName of Object.keys(this.columnFilters)) {
            const item = this.columnFilterItems[fieldName];
            const isActive =
                item && this.query.some((elem) => elem.searchItemId === item.searchItemId);
            if (!isActive) {
                delete this.columnFilters[fieldName];
                if (item) {
                    delete this.searchItems[item.searchItemId];
                    delete this.columnFilterItems[fieldName];
                }
            }
        }
    },

    async _notify() {
        this._pruneColumnFilters();
        this._saveColumnFilters();
        return super._notify(...arguments);
    },
});

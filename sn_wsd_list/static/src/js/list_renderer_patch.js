/** @odoo-module **/

import { onMounted, onPatched, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { usePopover } from "@web/core/popover/popover_hook";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ColumnFilterPanel } from "./column_filter_panel";
import {
    cloneFilter,
    isEmptyFilter,
    isFilterableColumn,
    matchFilterValue,
    newFilter,
} from "./column_filter_utils";

/**
 * The filter button is injected in the header cells of every ListRenderer
 * (including the sub classes defined by other modules, which have their own
 * template), so it is done at the DOM level instead of through a template
 * inheritance.
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        // Client side filters of x2many sub lists, keyed by field name.
        this.subListFilters = useState({});
        this.columnFilterPopover = usePopover(ColumnFilterPanel, {
            position: "bottom-start",
            popoverClass: "o_column_filter_popover",
            closeOnClickAway: true,
        });
        onMounted(() => this.mountColumnFilters());
        onPatched(() => this.mountColumnFilters());
        onWillUnmount(() => this.columnFilterPopover.close());
    },

    get isRootList() {
        return this.props.list.model.root === this.props.list;
    },

    /**
     * @param {Object} column
     * @returns {boolean} whether a filter button must be displayed on the column
     */
    canFilterColumn(column) {
        if (!isFilterableColumn(column, this.fields)) {
            return false;
        }
        // x2many sub lists are filtered client side, which is not supported
        // when the rows are grouped.
        return this.isRootList || !this.props.list.isGrouped;
    },

    getColumnFilter(fieldName) {
        if (this.isRootList) {
            return this.env.searchModel.columnFilters[fieldName];
        }
        return this.subListFilters[fieldName];
    },

    getColumnFilterBaseDomain(fieldName) {
        if (this.isRootList) {
            return this.env.searchModel.getColumnFilterBaseDomain(fieldName);
        }
        return [];
    },

    async applyColumnFilter(fieldName, filter) {
        if (this.isRootList) {
            const canLeave = await this.props.list.leaveEditMode();
            if (!canLeave) {
                return;
            }
            this.env.searchModel.setColumnFilter(fieldName, filter);
            return;
        }
        if (!filter || isEmptyFilter(filter)) {
            this.clearSubListFilter(fieldName);
            return;
        }
        this.subListFilters[fieldName] = filter;
    },

    clearColumnFilter(fieldName) {
        if (this.isRootList) {
            this.env.searchModel.clearColumnFilter(fieldName);
            return;
        }
        this.clearSubListFilter(fieldName);
    },

    setSubListFilter(fieldName, filter) {
        if (!filter || isEmptyFilter(filter)) {
            this.clearSubListFilter(fieldName);
            return;
        }
        this.subListFilters[fieldName] = filter;
    },

    clearSubListFilter(fieldName) {
        if (fieldName in this.subListFilters) {
            delete this.subListFilters[fieldName];
        }
    },

    /**
     * Inject (or refresh) the filter buttons in the header cells.
     */
    mountColumnFilters() {
        const table = this.tableRef && this.tableRef.el;
        if (!table) {
            return;
        }
        for (const th of table.querySelectorAll("thead th[data-name]")) {
            const fieldName = th.dataset.name;
            const column = this.columns && this.columns.find((col) => col.name === fieldName);
            if (!column || !this.canFilterColumn(column)) {
                continue;
            }
            th.classList.add("o_column_filterable");
            let button = th.querySelector(".o_column_filter_button");
            if (!button) {
                // Absolute positioned on the header cell itself, on the left of the
                // sort icon, to avoid overlapping it.
                button = document.createElement("button");
                button.type = "button";
                button.className = "o_column_filter_button btn btn-sm btn-link p-0";
                button.setAttribute("aria-label", _t("Filter"));
                button.innerHTML = '<i class="fa fa-filter"/>';
                button.addEventListener("mousedown", (ev) => ev.stopPropagation());
                button.addEventListener("pointerup", (ev) => ev.stopPropagation());
                button.addEventListener("click", (ev) => {
                    ev.stopPropagation();
                    ev.preventDefault();
                    this.toggleColumnFilterPopover(button, column);
                });
                th.appendChild(button);
            }
            button.classList.toggle(
                "o_column_filter_active",
                Boolean(this.getColumnFilter(fieldName))
            );
        }
    },

    toggleColumnFilterPopover(button, column) {
        if (this.columnFilterPopover.isOpen) {
            this.columnFilterPopover.close();
            return;
        }
        const fieldName = column.name;
        this.columnFilterPopover.open(button, {
            column,
            field: this.fields[fieldName],
            filter: cloneFilter(this.getColumnFilter(fieldName) || newFilter()),
            resModel: this.props.list.resModel,
            list: this.props.list,
            isRootList: this.isRootList,
            getBaseDomain: () => this.getColumnFilterBaseDomain(fieldName),
            applyFilter: (filter) => this.applyColumnFilter(fieldName, filter),
            clearFilter: () => this.clearColumnFilter(fieldName),
            close: () => this.columnFilterPopover.close(),
        });
    },

    /**
     * Records rendered by the list, with the sub list filters applied.
     * Root lists are filtered server side through the search model.
     */
    get filteredRecords() {
        const records = this.props.list.records;
        const filters = this.subListFilters;
        const fieldNames = Object.keys(filters || {});
        if (!fieldNames.length) {
            return records;
        }
        return records.filter((record) =>
            fieldNames.every((fieldName) => {
                const field = this.fields[fieldName];
                return (
                    field && matchFilterValue(record.data[fieldName], field.type, filters[fieldName])
                );
            })
        );
    },
});

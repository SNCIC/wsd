/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { ListRenderer } from "@web/views/list/list_renderer";
import { session } from "@web/session";
import { onMounted, onPatched, useExternalListener } from "@odoo/owl";

const STORAGE_PREFIX = "atliis.list_column_widths";
const STORAGE_VERSION = 1;

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        this._atliisColumnWidthStorageKey = this._atliisGetColumnWidthStorageKey();
        this._atliisColumnResizeInProgress = false;

        const originalStartResize = this.columnWidths.onStartResize.bind(this.columnWidths);
        this.columnWidths.onStartResize = (ev) => {
            this._atliisColumnResizeInProgress = true;
            originalStartResize(ev);
        };

        const originalResetWidths = this.columnWidths.resetWidths.bind(this.columnWidths);
        this.columnWidths.resetWidths = () => {
            this._atliisClearStoredColumnWidths();
            originalResetWidths();
        };

        const saveAfterResizeStop = (ev) => {
            if (!this._atliisColumnResizeInProgress) {
                return;
            }
            // Ignore the initial left-click pointerdown event that started resize.
            if (ev.type === "pointerdown" && ev.button === 0) {
                return;
            }
            browser.setTimeout(() => {
                this._atliisColumnResizeInProgress = false;
                this._atliisStoreColumnWidths();
            });
        };

        useExternalListener(window, "pointerup", saveAfterResizeStop);
        useExternalListener(window, "pointerdown", saveAfterResizeStop);
        useExternalListener(window, "keydown", saveAfterResizeStop);

        const restoreStoredWidths = () => {
            if (this._atliisColumnResizeInProgress) {
                return;
            }
            this._atliisRestoreColumnWidths();
        };

        onMounted(() => {
            browser.setTimeout(restoreStoredWidths);
        });
        onPatched(() => browser.setTimeout(restoreStoredWidths));
    },

    _atliisGetColumnWidthStorageKey() {
        const dbName = session.db || "default_db";
        return `${STORAGE_PREFIX}.${dbName}.${user.userId}.${this.createViewKey()}`;
    },

    _atliisBuildColumnsHash(headersLength) {
        return `${this.columns.map((column) => column.id).join("/")}/${headersLength}`;
    },

    _atliisGetHeaderElements() {
        const table = this.tableRef?.el;
        if (!table) {
            return null;
        }
        const headers = [...table.querySelectorAll("thead th")];
        if (!headers.length) {
            return null;
        }
        return headers;
    },

    _atliisStoreColumnWidths() {
        const headers = this._atliisGetHeaderElements();
        if (!headers) {
            return;
        }
        const table = this.tableRef.el;
        const payload = {
            version: STORAGE_VERSION,
            hash: this._atliisBuildColumnsHash(headers.length),
            widths: headers.map((th) => Math.floor(th.getBoundingClientRect().width)),
            tableWidth: table.style.width || null,
        };
        try {
            browser.localStorage.setItem(this._atliisColumnWidthStorageKey, JSON.stringify(payload));
        } catch {
            // Ignore storage quota/access errors.
        }
    },

    _atliisReadStoredColumnWidths() {
        try {
            const rawValue = browser.localStorage.getItem(this._atliisColumnWidthStorageKey);
            if (!rawValue) {
                return null;
            }
            const payload = JSON.parse(rawValue);
            if (
                !payload ||
                payload.version !== STORAGE_VERSION ||
                !Array.isArray(payload.widths) ||
                !payload.widths.length ||
                payload.widths.some((value) => !Number.isFinite(value) || value <= 0)
            ) {
                return null;
            }
            return payload;
        } catch {
            return null;
        }
    },

    _atliisRestoreColumnWidths() {
        const headers = this._atliisGetHeaderElements();
        if (!headers) {
            return false;
        }
        const payload = this._atliisReadStoredColumnWidths();
        if (!payload) {
            return false;
        }
        if (payload.widths.length !== headers.length) {
            return false;
        }
        if (payload.hash !== this._atliisBuildColumnsHash(headers.length)) {
            return false;
        }

        const table = this.tableRef.el;
        table.style.tableLayout = "fixed";
        headers.forEach((th, index) => {
            th.style.width = `${Math.floor(payload.widths[index])}px`;
        });
        if (payload.tableWidth) {
            table.style.width = payload.tableWidth;
        }
        return true;
    },

    _atliisClearStoredColumnWidths() {
        try {
            browser.localStorage.removeItem(this._atliisColumnWidthStorageKey);
        } catch {
            // Ignore storage access errors.
        }
    },
});

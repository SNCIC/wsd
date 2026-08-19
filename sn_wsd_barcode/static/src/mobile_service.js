import { EventBus } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { uniqueId } from "@web/core/utils/functions";

export const mobileService = {
    timeBetweenReadsInMs: 100,
    idInterval: null,
    start() {
        const methods = this._getNativeMethods();
        const bus = new EventBus();
        return {
            bus,
            enableReader: () => this.enableReader(bus, methods),
            stopReader: () => this.stopReader(),
        };
    },
    _getNativeMethods() {
        if (typeof window.OdooDeviceUtility === "undefined") {
            return {};
        }
        const deviceUtility = window.OdooDeviceUtility;
        const deferreds = {};
        window.odoo = window.odoo || {};
        const previousNativeNotify = window.odoo.native_notify;
        window.odoo.native_notify = function (id, result) {
            if (!deferreds[id]) {
                previousNativeNotify?.(id, result);
                return;
            }
            if (result.success) {
                deferreds[id].resolve(result);
            } else {
                deferreds[id].reject(result);
            }
            delete deferreds[id];
        };
        function nativeInvoke(name, args = {}) {
            const id = uniqueId();
            deviceUtility.execute(name, JSON.stringify(args), id);
            return new Promise((resolve, reject) => {
                deferreds[id] = { resolve, reject };
            });
        }
        const methods = {};
        for (const plugin of JSON.parse(deviceUtility.list_plugins())) {
            methods[plugin.name] = (args) => nativeInvoke(plugin.action, args);
        }
        return methods;
    },
    enableReader(bus, methods) {
        if (!methods.enableReader || !methods.getReaderData) {
            return;
        }
        methods.enableReader().catch((error) => console.error(error));
        if (this.idInterval) {
            return;
        }
        this.idInterval = setInterval(async () => {
            try {
                const value = await methods.getReaderData();
                if (value.success && value.data.length > 0) {
                    bus.trigger("mobile_reader_scanned", { data: value.data });
                }
            } catch (error) {
                console.error(error);
            }
        }, this.timeBetweenReadsInMs);
    },
    stopReader() {
        if (this.idInterval) {
            clearInterval(this.idInterval);
            this.idInterval = null;
        }
    },
};

// Key must differ from web_mobile's "mobile" service: both live in
// web.assets_backend and a duplicate key crashes the webclient at boot.
registry.category("services").add("sn_wsd_barcode_mobile", mobileService);

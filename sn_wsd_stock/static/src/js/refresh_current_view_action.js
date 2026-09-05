import { registry } from "@web/core/registry";

async function refreshCurrentView(_env, _action, options) {
    await options.onClose?.();
}

registry.category("actions").add(
    "sn_wsd_stock.refresh_current_view",
    refreshCurrentView,
);

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const PRODUCTION_OPERATION_TYPES = [
    {
        key: "smt",
        label: _t("SMT"),
        description: _t("Surface mount operations"),
    },
    {
        key: "dip",
        label: _t("DIP"),
        description: _t("Through-hole operations"),
    },
    {
        key: "pallet_binding",
        label: _t("Pallet Binding"),
        description: _t("Bind meter cartons to a pallet"),
    },
];

export class ProductionMenu extends Component {
    static props = { ...standardActionServiceProps };
    static template = "sn_wsd_barcode.ProductionMenu";

    setup() {
        this.action = useService("action");
    }

    get title() {
        return _t("Production Operations");
    }

    get backLabel() {
        return _t("Back");
    }

    get operationTypes() {
        return PRODUCTION_OPERATION_TYPES;
    }

    goBack() {
        if (this.env.config.breadcrumbs.length > 1) {
            this.env.config.historyBack();
        } else {
            this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_action_main_menu");
        }
    }

    openOperationType(operationType) {
        if (operationType.key === "pallet_binding") {
            return this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_pallet_binding_action");
        }
        this.action.doAction("sn_wsd_barcode.sn_wsd_barcode_workshop_client_action", {
            additionalContext: {
                operation_mode: operationType.key,
            },
        });
    }
}

registry.category("actions").add("sn_wsd_barcode_production_menu", ProductionMenu);

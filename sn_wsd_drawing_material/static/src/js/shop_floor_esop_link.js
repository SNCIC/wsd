/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { SnWsdShopFloor } from "@sn_wsd_workorder/js/shop_floor";

// the shop floor console and the ESOP page are both fullscreen actions,
// so the app menu is never visible once either is open: give operators a
// one-click hop from the console header to the ESOP page
patch(SnWsdShopFloor.prototype, {
    get esopLabel() {
        return _t("ESOP Documents");
    },
    openEsop() {
        this.action.doAction("sn_wsd_drawing_material.action_sn_wsd_esop_screen");
    },
});

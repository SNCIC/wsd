import { patch } from "@web/core/utils/patch";
import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";

patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        this.state.showOptions.costInfo = false;
        this.state.showOptions.costPrecision = 0;
    },

    async getBomData() {
        const bomData = await super.getBomData();
        this.state.showOptions.costInfo = bomData["has_cost_info"];
        // Unit prices follow the price decimal precision, not the decimals of
        // the currency: a component priced 0.00089 must not be shown as 0.00.
        this.state.showOptions.costPrecision = bomData["sn_cost_precision"];
        return bomData;
    },
});

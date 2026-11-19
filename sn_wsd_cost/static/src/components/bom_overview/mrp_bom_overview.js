import { patch } from "@web/core/utils/patch";
import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";

patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        this.state.showOptions.costInfo = false;
    },

    async getBomData() {
        const bomData = await super.getBomData();
        this.state.showOptions.costInfo = bomData["has_cost_info"];
        return bomData;
    },
});

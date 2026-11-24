import { patch } from "@web/core/utils/patch";
import { BomOverviewComponent } from "@mrp/components/bom_overview/mrp_bom_overview";

patch(BomOverviewComponent.prototype, {
    setup() {
        super.setup();
        // The BoM version and ECO columns of the overview stay hidden.
        this.state.showOptions.ecos = false;
    },
});

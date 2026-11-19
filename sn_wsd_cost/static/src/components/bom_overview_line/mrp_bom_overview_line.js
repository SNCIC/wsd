import { patch } from "@web/core/utils/patch";
import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";

patch(BomOverviewLine.prototype, {
    //---- Getters ----

    get showCostInfo() {
        return this.props.showOptions.costInfo;
    },
});

patch(BomOverviewLine, {
    props: {
        ...BomOverviewLine.props,
        showOptions: {
            type: Object,
            shape: {
                ...BomOverviewLine.props.showOptions.shape,
                costInfo: Boolean,
            },
        },
    },
});

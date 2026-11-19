import { patch } from "@web/core/utils/patch";
import { BomOverviewSpecialLine } from "@mrp/components/bom_overview_special_line/mrp_bom_overview_special_line";

patch(BomOverviewSpecialLine.prototype, {
    //---- Getters ----

    get showCostInfo() {
        return this.props.showOptions.costInfo;
    },
});

patch(BomOverviewSpecialLine, {
    props: {
        ...BomOverviewSpecialLine.props,
        showOptions: {
            type: Object,
            shape: {
                ...BomOverviewSpecialLine.props.showOptions.shape,
                costInfo: Boolean,
            },
        },
    },
});

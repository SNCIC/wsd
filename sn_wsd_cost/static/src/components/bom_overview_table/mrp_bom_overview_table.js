import { patch } from "@web/core/utils/patch";
import { BomOverviewTable } from "@mrp/components/bom_overview_table/mrp_bom_overview_table";

patch(BomOverviewTable.prototype, {
    //---- Getters ----

    get showCostInfo() {
        return this.props.showOptions.costInfo;
    },
});

patch(BomOverviewTable, {
    props: {
        ...BomOverviewTable.props,
        showOptions: {
            type: Object,
            shape: {
                ...BomOverviewTable.props.showOptions.shape,
                costInfo: Boolean,
            },
        },
    },
});

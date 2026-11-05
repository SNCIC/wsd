import { patch } from "@web/core/utils/patch";
import { BomOverviewSpecialLine } from "@mrp/components/bom_overview_special_line/mrp_bom_overview_special_line";

patch(BomOverviewSpecialLine.prototype, {
    //---- Getters ----

    get showSpecification() {
        return this.props.showOptions.specification;
    },
});

patch(BomOverviewSpecialLine, {
    props: {
        ...BomOverviewSpecialLine.props,
        showOptions: {
            type: Object,
            shape: {
                ...BomOverviewSpecialLine.props.showOptions.shape,
                specification: Boolean,
            },
        },
    },
});

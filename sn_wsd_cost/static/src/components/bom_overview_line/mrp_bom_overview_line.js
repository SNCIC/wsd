import { patch } from "@web/core/utils/patch";
import { formatMonetary } from "@web/views/fields/formatters";
import { BomOverviewLine } from "@mrp/components/bom_overview_line/mrp_bom_overview_line";

patch(BomOverviewLine.prototype, {
    //---- Handlers ----

    formatUnitCost(value) {
        // `digits` overrides the decimals of the currency and `trailingZeros`
        // hides the zeros right of the last significant digit, the way the
        // `hide_trailing_zeros` option of the float field behaves.
        return formatMonetary(value, {
            currencyId: this.data.currency_id,
            digits: [16, this.props.showOptions.costPrecision],
            trailingZeros: false,
        });
    },

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
                costPrecision: Number,
            },
        },
    },
});

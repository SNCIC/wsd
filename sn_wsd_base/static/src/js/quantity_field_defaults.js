/** @odoo-module **/

import { registry } from "@web/core/registry";
import { floatField } from "@web/views/fields/float/float_field";
import { monetaryField } from "@web/views/fields/monetary/monetary_field";
import { formatFloat, formatMonetary } from "@web/views/fields/formatters";

const QUANTITY_FIELD_PATTERNS = [
    /^qty(?:_|$)/,
    /(?:^|_)qty(?:_|$)/,
    /(?:^|_)quantity(?:_|$)/,
    /(?:^|_)quantities(?:_|$)/,
    /(?:^|_)product_qty(?:_|$)/,
    /(?:^|_)product_uom_qty(?:_|$)/,
    /(?:^|_)quantity_done(?:_|$)/,
    /(?:^|_)quantity_available(?:_|$)/,
    /(?:^|_)quantity_in_progress(?:_|$)/,
    /(?:^|_)quantity_to_order(?:_|$)/,
    /(?:^|_)reserved_quantity(?:_|$)/,
    /(?:^|_)available_quantity(?:_|$)/,
    /(?:^|_)forecast(?:_|$)/,
    /(?:^|_)free_qty(?:_|$)/,
    /(?:^|_)incoming_qty(?:_|$)/,
    /(?:^|_)outgoing_qty(?:_|$)/,
    /(?:^|_)virtual_available(?:_|$)/,
];

function isQuantityField(fieldName) {
    return QUANTITY_FIELD_PATTERNS.some((pattern) => pattern.test(fieldName));
}

function applyQuantityDefault(fieldComponent) {
    const originalExtractProps = fieldComponent.extractProps;
    fieldComponent.extractProps = function (fieldInfo, dynamicInfo) {
        const props = originalExtractProps.call(this, fieldInfo, dynamicInfo);
        if (fieldInfo.options.hide_trailing_zeros === undefined) {
            props.trailingZeros = !isQuantityField(fieldInfo.name);
        }
        return props;
    };
}

applyQuantityDefault(floatField);
applyQuantityDefault(monetaryField);

function applyQuantityFormatter(formatter) {
    const originalFormatter = formatter;
    const originalExtractOptions = formatter.extractOptions;
    const quantityFormatter = (value, options = {}) => {
        const formatterOptions = { ...options };
        if (
            formatterOptions.trailingZeros === undefined &&
            formatterOptions.hide_trailing_zeros === undefined &&
            formatterOptions.isQuantityField
        ) {
            formatterOptions.trailingZeros = false;
        }
        return originalFormatter(value, formatterOptions);
    };
    quantityFormatter.extractOptions = (fieldInfo) => {
        const options = originalExtractOptions
            ? originalExtractOptions(fieldInfo)
            : { ...fieldInfo.options };
        const isQuantity = isQuantityField(fieldInfo.name);
        if (fieldInfo.options.hide_trailing_zeros === undefined && isQuantity) {
            options.trailingZeros = false;
        }
        options.isQuantityField = isQuantity;
        return options;
    };
    return quantityFormatter;
}

const formatters = registry.category("formatters");
formatters.add("float", applyQuantityFormatter(formatFloat), { force: true });
formatters.add("monetary", applyQuantityFormatter(formatMonetary), { force: true });

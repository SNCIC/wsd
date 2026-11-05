/** @odoo-module **/

import { registry } from "@web/core/registry";
import { floatField } from "@web/views/fields/float/float_field";
import { monetaryField } from "@web/views/fields/monetary/monetary_field";
import { formatFloat, formatMonetary } from "@web/views/fields/formatters";

function applyDefaultTrailingZeros(fieldComponent) {
    const originalExtractProps = fieldComponent.extractProps;
    fieldComponent.extractProps = function (fieldInfo, dynamicInfo) {
        const props = originalExtractProps.call(this, fieldInfo, dynamicInfo);
        if (fieldInfo.options.hide_trailing_zeros === undefined) {
            props.trailingZeros = false;
        }
        return props;
    };
}

applyDefaultTrailingZeros(floatField);
applyDefaultTrailingZeros(monetaryField);

function applyDefaultFormatterTrailingZeros(formatter) {
    const originalFormatter = formatter;
    const originalExtractOptions = formatter.extractOptions;
    const defaultFormatter = (value, options = {}) => {
        const formatterOptions = { ...options };
        if (
            formatterOptions.trailingZeros === undefined &&
            formatterOptions.hide_trailing_zeros === undefined
        ) {
            formatterOptions.trailingZeros = false;
        }
        return originalFormatter(value, formatterOptions);
    };
    defaultFormatter.extractOptions = (fieldInfo) => {
        const options = originalExtractOptions
            ? originalExtractOptions(fieldInfo)
            : { ...fieldInfo.options };
        if (fieldInfo.options.hide_trailing_zeros === undefined) {
            options.trailingZeros = false;
        }
        return options;
    };
    return defaultFormatter;
}

const formatters = registry.category("formatters");
formatters.add("float", applyDefaultFormatterTrailingZeros(formatFloat), { force: true });
formatters.add("monetary", applyDefaultFormatterTrailingZeros(formatMonetary), { force: true });

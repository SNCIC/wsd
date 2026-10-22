/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

// Field types that can be filtered from a list view header.
export const FILTERABLE_TYPES = new Set([
    "char",
    "text",
    "integer",
    "float",
    "monetary",
    "selection",
    "many2one",
    "boolean",
    "date",
    "datetime",
]);

// Field types filtered with a "from / to" range instead of a value list.
export const RANGE_TYPES = new Set(["integer", "float", "monetary", "date", "datetime"]);

// Field types that can be filtered with a keyword ("contains") instead of a
// list of values.
export const KEYWORD_TYPES = new Set(["char", "text", "many2one"]);

export function newFilter() {
    return {
        mode: "include",
        values: [],
        valueLabels: {},
        empty: false,
        nonEmpty: false,
        from: "",
        to: "",
        search: "",
    };
}

export function cloneFilter(filter) {
    return JSON.parse(JSON.stringify(filter || newFilter()));
}

export function isEmptyFilter(filter) {
    if (!filter) {
        return true;
    }
    return !(
        filter.empty ||
        filter.nonEmpty ||
        (filter.values && filter.values.length) ||
        filter.from ||
        filter.to ||
        (filter.search && filter.search.trim())
    );
}

export function isRangeType(fieldType) {
    return RANGE_TYPES.has(fieldType);
}

export function isExcludeMode(filter) {
    return Boolean(filter) && filter.mode === "exclude";
}

/**
 * @param {Object} column column description of the list arch
 * @param {Object} fields fields description of the list model
 * @returns {boolean} whether a filter button should be displayed on the column
 */
export function isFilterableColumn(column, fields) {
    if (!column || column.type !== "field" || column.aggregate) {
        return false;
    }
    const fieldName = column.name;
    if (!fieldName || fieldName.includes(".")) {
        return false;
    }
    if (["handle", "button"].includes(column.widget)) {
        return false;
    }
    const field = fields[fieldName];
    if (!field || !FILTERABLE_TYPES.has(field.type)) {
        return false;
    }
    // Only stored (sortable) fields can be grouped server side.
    if (field.sortable === false) {
        return false;
    }
    return true;
}

export function normalizeRangeValue(value, fieldType, isEnd) {
    if (!value) {
        return false;
    }
    if (["integer", "float", "monetary"].includes(fieldType)) {
        const number = Number(value);
        return Number.isFinite(number) ? number : false;
    }
    const raw = String(value).trim().replace("T", " ");
    if (fieldType === "date") {
        return raw.slice(0, 10);
    }
    const parts = raw.split(" ");
    if (parts.length === 1) {
        return isEnd ? `${raw} 23:59:59` : `${raw} 00:00:00`;
    }
    const chunks = parts[1].split(":");
    while (chunks.length < 3) {
        chunks.push(isEnd ? "59" : "00");
    }
    return `${parts[0]} ${chunks.slice(0, 3).join(":")}`;
}

function orDomains(leafs) {
    if (!leafs.length) {
        return null;
    }
    if (leafs.length === 1) {
        return [leafs[0]];
    }
    const domain = [];
    for (let i = 1; i < leafs.length; i++) {
        domain.push("|");
    }
    domain.push(...leafs);
    return domain;
}

/**
 * Combine domain expressions with a "AND". The result is a flat domain (prefix
 * notation), as nested domains are not supported by the ORM.
 */
function andDomains(domains) {
    if (!domains.length) {
        return null;
    }
    if (domains.length === 1) {
        return domains[0];
    }
    const domain = [];
    for (let i = 1; i < domains.length; i++) {
        domain.push("&");
    }
    for (const subDomain of domains) {
        domain.push(...subDomain);
    }
    return domain;
}

/**
 * Build the domain leafs matching a column filter.
 *
 * @param {string} fieldName
 * @param {string} fieldType
 * @param {Object} filter
 * @returns {Array|null} domain
 */
export function buildFilterDomain(fieldName, fieldType, filter) {
    if (!filter) {
        return null;
    }
    const exclude = isExcludeMode(filter);
    const domains = [];
    if (isRangeType(fieldType)) {
        const from = normalizeRangeValue(filter.from, fieldType, false);
        const to = normalizeRangeValue(filter.to, fieldType, true);
        if (from) {
            domains.push([[fieldName, exclude ? "<" : ">=", from]]);
        }
        if (to) {
            domains.push([[fieldName, exclude ? ">" : "<=", to]]);
        }
    }
    const values = (filter.values || []).filter(
        (value) => value !== false && value !== null && value !== undefined
    );
    const keyword = (filter.search || "").trim();
    // When nothing is checked, the keyword itself filters the records.
    const useKeyword =
        Boolean(keyword) &&
        KEYWORD_TYPES.has(fieldType) &&
        !values.length &&
        !filter.empty &&
        !filter.nonEmpty;
    if (useKeyword) {
        if (exclude) {
            // Keep the empty values: they do not contain the keyword.
            domains.push(["|", [fieldName, "=", false], [fieldName, "not ilike", keyword]]);
        } else {
            domains.push([[fieldName, "ilike", keyword]]);
        }
    }
    if (exclude) {
        if (filter.empty) {
            domains.push([[fieldName, "!=", false]]);
        }
        if (filter.nonEmpty) {
            domains.push([[fieldName, "=", false]]);
        }
        if (values.length) {
            // Keep empty values: "not in" does not match NULL in SQL.
            domains.push(["|", [fieldName, "=", false], [fieldName, "not in", values]]);
        }
    } else {
        const leafs = [];
        if (filter.empty) {
            leafs.push([fieldName, "=", false]);
        }
        if (filter.nonEmpty) {
            leafs.push([fieldName, "!=", false]);
        }
        if (values.length) {
            leafs.push([fieldName, "in", values]);
        }
        const domain = orDomains(leafs);
        if (domain) {
            domains.push(domain);
        }
    }
    return andDomains(domains);
}

/**
 * Human readable description of a filter, used as search facet label.
 */
export function buildFilterDescription(fieldLabel, filter) {
    const parts = [];
    if (filter.empty) {
        parts.push(_t("(empty)"));
    }
    if (filter.nonEmpty) {
        parts.push(_t("(not empty)"));
    }
    const labels = (filter.values || []).map((value) => {
        const label = filter.valueLabels && filter.valueLabels[value];
        return label === undefined ? String(value) : label;
    });
    if (labels.length) {
        const visible = labels.slice(0, 3).join(", ");
        parts.push(labels.length > 3 ? `${visible}…` : visible);
    }
    if (filter.from || filter.to) {
        parts.push(`${filter.from || "…"} ~ ${filter.to || "…"}`);
    }
    const keyword = (filter.search || "").trim();
    if (keyword && !parts.length) {
        parts.push(keyword);
    }
    const description = parts.join(", ") || _t("(all)");
    return isExcludeMode(filter) ? `${fieldLabel} ≠ ${description}` : `${fieldLabel}: ${description}`;
}

/**
 * Local (client side) evaluation of a filter, used by x2many sub lists.
 */
export function matchFilterValue(value, fieldType, filter) {
    if (!filter) {
        return true;
    }
    const exclude = isExcludeMode(filter);
    const raw = fieldType === "many2one" ? value && value.id : value;
    const isNil = raw === false || raw === null || raw === undefined || raw === "";
    if (isRangeType(fieldType) && (filter.from || filter.to)) {
        if (isNil) {
            return false;
        }
        const isDate = fieldType === "date" || fieldType === "datetime";
        const comparable = isDate ? String(raw) : Number(raw);
        const from = normalizeRangeValue(filter.from, fieldType, false);
        const to = normalizeRangeValue(filter.to, fieldType, true);
        let inRange = true;
        if (from) {
            inRange = inRange && comparable >= (isDate ? from : Number(from));
        }
        if (to) {
            inRange = inRange && comparable <= (isDate ? to : Number(to));
        }
        return exclude ? !inRange : inRange;
    }
    const values = filter.values || [];
    const keyword = (filter.search || "").trim();
    if (
        keyword &&
        KEYWORD_TYPES.has(fieldType) &&
        !values.length &&
        !filter.empty &&
        !filter.nonEmpty
    ) {
        if (isNil) {
            return exclude;
        }
        const match = String(raw).toLowerCase().includes(keyword.toLowerCase());
        return exclude ? !match : match;
    }
    if (exclude) {
        if (filter.empty) {
            return !isNil;
        }
        if (filter.nonEmpty) {
            return isNil;
        }
        return isNil || !values.includes(raw);
    }
    if (!filter.empty && !filter.nonEmpty && !values.length) {
        return true;
    }
    if (filter.empty && isNil) {
        return true;
    }
    if (filter.nonEmpty && !isNil) {
        return true;
    }
    return !isNil && values.includes(raw);
}

export function formatValueLabel(value, field, fieldType) {
    if (fieldType === "many2one") {
        return Array.isArray(value) ? value[1] : String(value);
    }
    if (fieldType === "selection") {
        const option = (field.selection || []).find(([key]) => key === value);
        return option ? option[1] : String(value);
    }
    if (fieldType === "boolean") {
        return value ? _t("Yes") : _t("No");
    }
    if (value === false || value === null || value === undefined) {
        return _t("(empty)");
    }
    return String(value);
}

export function rawValueKey(value, fieldType) {
    if (fieldType === "many2one") {
        return value && value.id;
    }
    return value;
}

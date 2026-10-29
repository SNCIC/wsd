import { onWillRender } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";

/**
 * List whose repeated document information is printed once per document.
 *
 * The Kingdee detail lists write the header of a document once and leave the
 * cells of its other lines blank. The list keeps one cell per line, so the
 * columns stay aligned, and hides the content of the repeated ones, which
 * reads the same way.
 *
 * The document the lines are merged on and the fields carrying its
 * information are given in the context of the action opening the list:
 *
 *     {'sn_merged_cells_key': 'picking_id',
 *      'sn_merged_cells_fields': ['reference', 'sn_picking_date']}
 *
 * An action without that context keeps the purchase request detail behaviour
 * (merged per request on the header fields of the request), which is what the
 * views written before the configuration existed expect.
 */
const DEFAULT_MERGED_KEY_FIELD = "request_id";
const DEFAULT_MERGED_FIELD_NAMES = ["request_id", "date_required", "requested_by", "description"];
const MERGED_CELL_CLASS = "o_sn_wsd_merged_cell";

export class SnWsdMergedCellsListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.flatRecordsCache = null;
        this.mergeConfigCache = null;
        onWillRender(() => {
            this.flatRecordsCache = null;
            this.mergeConfigCache = null;
        });
    }

    /**
     * The merge configuration is read on render, not in setup(): the search
     * model is filled asynchronously (its action context is applied when the
     * search view loads), so reading it in setup() can miss the context and
     * silently fall back to the purchase request defaults, which never match
     * any other list and leave every cell visible.
     */
    get mergeConfig() {
        if (!this.mergeConfigCache) {
            this.mergeConfigCache = this.readMergeConfig();
        }
        return this.mergeConfigCache;
    }

    readMergeConfig() {
        const sources = [
            this.env.searchModel && this.env.searchModel.context,
            this.props.list && this.props.list.context,
        ];
        for (const source of sources) {
            if (!source || !source.sn_merged_cells_key) {
                continue;
            }
            const fieldNames = source.sn_merged_cells_fields;
            return {
                keyField: source.sn_merged_cells_key,
                fieldNames: Array.isArray(fieldNames)
                    ? fieldNames
                    : typeof fieldNames === "string"
                      ? fieldNames
                            .split(",")
                            .map((name) => name.trim())
                            .filter(Boolean)
                      : DEFAULT_MERGED_FIELD_NAMES,
            };
        }
        return {
            keyField: DEFAULT_MERGED_KEY_FIELD,
            fieldNames: DEFAULT_MERGED_FIELD_NAMES,
        };
    }

    getCellClass(column, record) {
        const classes = super.getCellClass(column, record);
        if (
            !this.mergeConfig.fieldNames.includes(column.name) ||
            this.isFirstLineOfDocument(record)
        ) {
            return classes;
        }
        return `${classes} ${MERGED_CELL_CLASS}`;
    }

    /**
     * Whether the line is the first one of its document, hence the one
     * carrying the header information.
     *
     * The header fields belong to the document, not to the line, so they are
     * printed once per document rather than once per distinct value: two
     * documents sharing the same vendor still print it on the first line of
     * each. The lines are compared in the order they are displayed in, so
     * sorting the list differently can only merge lines that really sit next
     * to each other. A line being edited keeps every value visible, so its
     * fields stay editable.
     */
    isFirstLineOfDocument(record) {
        if (record.isInEdition) {
            return true;
        }
        const records = this.flatRecords;
        const index = records.indexOf(record);
        if (index <= 0) {
            return true;
        }
        const keyField = this.mergeConfig.keyField;
        const document = this.cellValue(record, keyField);
        if (document === false || document === null || document === undefined) {
            return true;
        }
        return this.cellValue(records[index - 1], keyField) !== document;
    }

    /**
     * Value the cells of a field are compared on: a relational field carries
     * its record, so its identifier is what makes two cells equal.
     */
    cellValue(record, fieldName) {
        const value = record.data[fieldName];
        return value && typeof value === "object" ? value.id : value;
    }

    /**
     * Records in the order they are displayed, the group headers left out.
     */
    get flatRecords() {
        if (!this.flatRecordsCache) {
            const records = [];
            const collect = (list) => {
                if (!list) {
                    return;
                }
                if (list.groups && list.groups.length) {
                    for (const group of list.groups) {
                        collect(group.list);
                    }
                } else if (list.records) {
                    records.push(...list.records);
                }
            };
            collect(this.props.list);
            this.flatRecordsCache = records;
        }
        return this.flatRecordsCache;
    }
}

export const snWsdMergedCellsListView = Object.assign({}, listView, {
    Renderer: SnWsdMergedCellsListRenderer,
});

registry.category("views").add("sn_wsd_merged_cells_list", snWsdMergedCellsListView);

import { onWillRender } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";

/**
 * Fields whose value is printed on the first line of their request only.
 *
 * The Kingdee lists write the header information of a purchase request once
 * and leave the cells of its other lines blank. The list keeps one cell per
 * line, so the columns stay aligned, and hides the content of the repeated
 * ones, which reads the same way.
 */
const MERGED_FIELD_NAMES = ["request_id", "date_required", "requested_by", "description"];

export class SnWsdMergedCellsListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.flatRecordsCache = null;
        onWillRender(() => {
            this.flatRecordsCache = null;
        });
    }

    getCellClass(column, record) {
        const classes = super.getCellClass(column, record);
        if (!MERGED_FIELD_NAMES.includes(column.name) || this.isFirstLineOfRequest(record)) {
            return classes;
        }
        return `${classes} o_sn_wsd_merged_cell`;
    }

    /**
     * Whether the line is the first one of its purchase request, hence the one
     * carrying the header information.
     *
     * The header fields belong to the request, not to the line, so they are
     * printed once per request rather than once per distinct value: two
     * requests sharing the same requester still print it on the first line of
     * each. The lines are compared in the order they are displayed in, so
     * sorting the list differently can only merge lines that really sit next to
     * each other. A line being edited keeps every value visible, so its fields
     * stay editable.
     */
    isFirstLineOfRequest(record) {
        if (record.isInEdition) {
            return true;
        }
        const records = this.flatRecords;
        const index = records.indexOf(record);
        if (index <= 0) {
            return true;
        }
        const request = this.cellValue(record, "request_id");
        if (request === false || request === null || request === undefined) {
            return true;
        }
        return this.cellValue(records[index - 1], "request_id") !== request;
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

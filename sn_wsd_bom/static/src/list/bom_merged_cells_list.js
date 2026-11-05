import { onWillRender } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";

/**
 * Fields of the parent BOM whose value is printed on the first line of that
 * BOM only.
 *
 * The Kingdee BOM detail list writes the header of a BOM once and leaves the
 * cells of its other component lines blank. The list keeps one cell per line,
 * so the columns stay aligned, and hides the content of the repeated ones,
 * which reads the same way.
 */
const MERGED_FIELD_NAMES = [
    "bom_code",
    "bom_version",
    "parent_product_code",
    "parent_product_name",
    "bom_active",
    "parent_material_specification",
];

/** Field the lines are grouped on: they are merged per BOM. */
const MERGED_KEY_FIELD = "bom_id";

export class SnWsdBomMergedCellsListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.flatRecordsCache = null;
        onWillRender(() => {
            this.flatRecordsCache = null;
        });
    }

    getCellClass(column, record) {
        const classes = super.getCellClass(column, record);
        if (!MERGED_FIELD_NAMES.includes(column.name) || this.isFirstLineOfBom(record)) {
            return classes;
        }
        return `${classes} o_sn_wsd_bom_merged_cell`;
    }

    /**
     * Whether the line is the first one of its BOM, hence the one carrying the
     * header information.
     *
     * The lines are compared in the order they are displayed in, so sorting
     * the list differently can only merge lines that really sit next to each
     * other. A line being edited keeps every value visible, so its fields stay
     * editable.
     */
    isFirstLineOfBom(record) {
        if (record.isInEdition) {
            return true;
        }
        const records = this.flatRecords;
        const index = records.indexOf(record);
        if (index <= 0) {
            return true;
        }
        const bom = this.cellValue(record, MERGED_KEY_FIELD);
        if (bom === false || bom === null || bom === undefined) {
            return true;
        }
        return this.cellValue(records[index - 1], MERGED_KEY_FIELD) !== bom;
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

export const snWsdBomMergedCellsListView = Object.assign({}, listView, {
    Renderer: SnWsdBomMergedCellsListRenderer,
});

registry.category("views").add("sn_wsd_bom_merged_cells_list", snWsdBomMergedCellsListView);

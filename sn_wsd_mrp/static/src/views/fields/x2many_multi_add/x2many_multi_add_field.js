/** @odoo-module **/
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { useOwnedDialogs } from "@web/core/utils/hooks";
import { Domain } from "@web/core/domain";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * Generic x2many widget that turns the list "Add a line" into a multi-select
 * picker (Odoo's built-in SelectCreateDialog: search box + table + checkboxes).
 *
 * On One2many it opens a dialog on the source model and creates one row per
 * picked record (relying on onchanges to fill defaults such as employee code
 * and to rebalance ratios). On Many2many it falls back to the native behaviour
 * (which already opens a multi-select dialog).
 *
 * Usage in a view:
 *   <field name="member_ids" widget="sn_wsd_x2many_multi_add"
 *          options="{'multi_add_model': 'hr.employee',
 *                    'multi_add_field': 'employee_id',
 *                    'multi_add_domain': '[("company_id", "=", company_id)]'}"/>
 */
export class X2ManyMultiAddField extends X2ManyField {
    static props = {
        ...X2ManyField.props,
        multiAddModel: { type: String, optional: true },
        multiAddField: { type: String, optional: true },
        multiAddDomain: { type: String, optional: true },
    };

    setup() {
        super.setup();
        this.addDialog = useOwnedDialogs();
    }

    /**
     * Extract a database id from a many2one value whatever shape the relational
     * model hands us (record datapoint, [id, name] tuple, raw id, ...).
     */
    _m2oToId(value) {
        if (value == null) {
            return false;
        }
        if (typeof value === "number") {
            return value;
        }
        if (Array.isArray(value)) {
            return value[0] || false;
        }
        if (value.resId !== undefined) {
            return value.resId;
        }
        if (value.id !== undefined) {
            return value.id;
        }
        return false;
    }

    async onAdd(params = {}) {
        // Many2many already opens a multi-select dialog natively.
        if (this.isMany2Many) {
            return super.onAdd(...arguments);
        }
        const field = this.props.multiAddField;
        const context = Object.assign({}, this.props.context, params.context);

        // Evaluate the option domain (may reference parent fields) + exclude the
        // source records already present in the list.
        const baseDomain = new Domain(this.props.multiAddDomain || "[]").toList(
            this.props.record.evalContext
        );
        const usedIds = this.list.records
            .map((record) => this._m2oToId(record.data[field]))
            .filter((id) => id !== false);
        const domain = usedIds.length
            ? [...baseDomain, ["id", "not in", usedIds]]
            : baseDomain;

        this.addDialog(SelectCreateDialog, {
            title: _t("Add: %s", this.props.string),
            resModel: this.props.multiAddModel,
            domain,
            context,
            multiSelect: true,
            noCreate: true,
            onSelected: async (resIds) => {
                if (!resIds || !resIds.length) {
                    return;
                }
                // Create one row per picked record. Using addNewRecord with a
                // default_<field> context guarantees the related onchanges fire
                // (auto-fill employee code, rebalance performance ratios, ...).
                for (const id of resIds) {
                    await this.list.addNewRecord({
                        context: Object.assign({}, context, {
                            ["default_" + field]: id,
                        }),
                        position: "bottom",
                        mode: "readonly",
                    });
                }
                // Persist the parent so the freshly added rows become real
                // (non-abandonable) records instead of virtual drafts that the
                // editable list would discard as soon as one is edited and left.
                await this.props.record.save();
            },
        });
    }
}

export const x2ManyMultiAddField = {
    ...x2ManyField,
    component: X2ManyMultiAddField,
    supportedOptions: [
        ...(x2ManyField.supportedOptions || []),
        { name: "multi_add_model", type: "string" },
        { name: "multi_add_field", type: "string" },
        { name: "multi_add_domain", type: "string" },
    ],
    extractProps: (fieldInfo, dynamicInfo) => {
        const props = x2ManyField.extractProps(fieldInfo, dynamicInfo);
        const options = fieldInfo.options || {};
        props.multiAddModel = options.multi_add_model;
        props.multiAddField = options.multi_add_field;
        props.multiAddDomain = options.multi_add_domain;
        return props;
    },
};

registry.category("fields").add("sn_wsd_x2many_multi_add", x2ManyMultiAddField);

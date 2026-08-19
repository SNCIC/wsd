import { FloatField, floatField } from '@web/views/fields/float/float_field';
import { registry } from '@web/core/registry';

export class MrpPlmUpdateQty extends FloatField {
    static template = "sn_wsd_plm.UpdateQty";
}

export const mrpPlmUpdateQty = {
    ...floatField,
    component: MrpPlmUpdateQty,
    displayName: "MRP PLM Update Quantity",
};

registry.category("fields").add("plm_upd_qty", mrpPlmUpdateQty);

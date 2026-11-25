# -*- coding: utf-8 -*-
"""Manufacturing orders pushed to ``PRD_MO``.

The account models a production order as a **tree**: ``FTreeEntity`` holds the
product to produce, and its children are the co-products and the by-products. The
MES produces one product per order, so the tree has a single row - the main product
(``FProductType`` 1).

Sixteen values are mandatory. Three of them are decisions worth writing down:

``FPPBOMType``
    ``2`` (main product only) is the default of the mapping row: the MES explodes
    its own bill of materials and issues the components itself, so the account must
    not expand a second one. Switch it to ``1`` only if the account is meant to own
    the material list.
``FCreateType`` / ``FReqType``
    ``1`` (manual entry) and ``2`` (independent demand): the order comes from the
    MES plan, not from a Kingdee MRP run.
``FScheduleStatus`` / ``FFirstInspectStatus``
    ``1`` (not scheduled) and ``B`` (first inspection pending): the account's
    scheduling and first-article control stay untouched until the shop floor tells
    them otherwise.

A material issue, a material return and a finished goods receipt point at this
order by its **Kingdee number** (``FMoBillNo``): the Odoo name means nothing to the
account. The three transfers therefore require this order to be pushed first and say
so with an explicit error.
"""

from odoo import _, models


class MrpProduction(models.Model):
    """A manufacturing order of the MES, pushed as ``PRD_MO``."""

    _name = "mrp.production"
    _inherit = ["mrp.production", "sn.wsd.kingdee.bill.mixin"]

    _kingdee_bill_kind_default = "production_order"

    def _kingdee_product_uom(self):
        self.ensure_one()
        return getattr(self, "product_uom_id", False) or getattr(self, "product_uom", False)

    def _kingdee_bill_qty_amount(self):
        self.ensure_one()
        return self.product_qty or 0.0, 0.0

    def _kingdee_bill_parts(self, kind, map_row, account):
        header = {"FBillNo": self._kingdee_number()}
        self._kd_put(header, "FDate", self._kd_date(self.date_start))
        self._kd_put(header, "FBillType", self._kd_ref(map_row.bill_type_number))
        self._kd_put(header, "FPrdOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FOwnerTypeId", self._kd_owner_type(account))
        self._kd_put(header, "FOwnerId", self._kd_ref(self._kd_org("create")))
        header["FPPBOMType"] = (map_row.production_bom_type or "2").strip()
        self._kd_put(header, "FDescription", self._kd_note_text())
        entry = {}
        self._kd_put(entry, "FMaterialId",
                     self._kd_ref(self._kd_product_number(self.product_id)))
        entry["FQty"] = self.product_qty or 0.0
        uom = self._kingdee_product_uom()
        self._kd_put(entry, "FUnitId", self._kd_ref(self._kd_uom_number(uom)))
        self._kd_put(entry, "FBaseUnitId", self._kd_ref(
            self._kd_uom_number(self.product_id.uom_id)))
        entry["FProductType"] = "1"
        self._kd_put(entry, "FPlanStartDate", self._kd_datetime(self.date_start))
        self._kd_put(entry, "FPlanFinishDate",
                     self._kd_datetime(self.date_finished or self.date_deadline))
        self._kd_put(entry, "FStockInOrgId", self._kd_ref(self._kd_org("create")))
        entry["FCreateType"] = "1"
        entry["FReqType"] = "2"
        entry["FScheduleStatus"] = "1"
        entry["FFirstInspectStatus"] = "B"
        entry["FFirstQCControlType"] = "0"
        header["FTreeEntity"] = [entry]
        return header

    def _kingdee_bill_required_settings(self):
        return [
            (_("product"), self._kd_product_number(self.product_id)),
        ]

    def action_confirm(self):
        """Push the order to Kingdee as soon as the plan releases it."""
        result = super().action_confirm()
        self.filtered(lambda mo: mo.state == "confirmed")._kingdee_auto_push()
        return result

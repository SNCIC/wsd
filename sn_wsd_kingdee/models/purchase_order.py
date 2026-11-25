# -*- coding: utf-8 -*-
"""Purchase orders pushed to ``PUR_PurchaseOrder``.

The account requires twelve values on a standard purchase order and four of them
are its own data: the purchase organization, the supplier number, the bill type
(``CGDD01_SYS`` standard) and the business type (``CG`` standard). The three
entities of the object are used as the account expects them:

``FBillHead``
    flat fields (date, organization, supplier, bill type, business type);
``FPOOrderFinance``
    the settlement currency and the pricing point, one per document;
``FPOOrderEntry``
    one row per order line, with the three units the account insists on (purchase,
    pricing and stock unit), the tax rate and the amount.

The tax rate is computed from the taxes of the Odoo line, so an account that books
the purchase tax from the line rate gets the same figure as the order.
"""

from odoo import _, models


class PurchaseOrder(models.Model):
    """A purchase order of the MES, pushed as ``PUR_PurchaseOrder``."""

    _name = "purchase.order"
    _inherit = ["purchase.order", "sn.wsd.kingdee.bill.mixin"]

    _kingdee_bill_kind_default = "purchase_order"

    # ------------------------------------------------------------------
    # Values of the document
    # ------------------------------------------------------------------
    def _kingdee_bill_qty_amount(self):
        self.ensure_one()
        quantity = sum(self.order_line.mapped("product_qty"))
        amount = sum(self.order_line.mapped("price_subtotal"))
        return quantity, amount

    def _kingdee_tax_rate(self, line):
        """Tax rate in percent of an order line (0 when it carries no tax)."""
        rate = 0.0
        for tax in line.tax_ids:
            if tax.amount_type == "percent":
                rate += tax.amount
        return rate

    def _kingdee_bill_parts(self, kind, map_row, account):
        header = {"FBillNo": self._kingdee_number()}
        self._kd_put(header, "FDate", self._kd_date(self.date_order or self.date_approve))
        self._kd_put(header, "FPurchaseOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FBillTypeID", self._kd_ref(map_row.bill_type_number))
        self._kd_put(header, "FBusinessType", (map_row.business_type or "").strip())
        self._kd_put(header, "FSupplierId", self._kd_ref(
            self._kd_partner_number(self.partner_id, "supplier")))
        header["FPOOrderFinance"] = {
            "FSettleCurrId": self._kd_ref(self._kd_currency_number(self.currency_id)),
            "FPriceTimePoint": "1",
        }
        entries = []
        for line in self.order_line:
            if not line.product_qty:
                continue
            entry = {}
            self._kd_put(entry, "FMaterialId",
                         self._kd_ref(self._kd_product_number(line.product_id)))
            entry["FQty"] = line.product_qty
            uom_number = self._kd_uom_number(line.product_uom_id)
            self._kd_put(entry, "FUnitId", self._kd_ref(uom_number))
            self._kd_put(entry, "FPriceUnitId", self._kd_ref(uom_number))
            self._kd_put(entry, "FStockUnitID", self._kd_ref(uom_number))
            self._kd_put(entry, "FBaseUnitId", self._kd_ref(
                self._kd_uom_number(line.product_id.uom_id)))
            self._kd_put(entry, "FEntrySettleOrgId", self._kd_ref(self._kd_org("create")))
            entry["FPrice"] = line.price_unit
            rate = self._kingdee_tax_rate(line)
            if rate:
                entry["FEntryTaxRate"] = rate
                entry["FTaxPrice"] = round(line.price_unit * (1 + rate / 100.0), 6)
            entry["FEntryAmount"] = line.price_subtotal
            entry["FAllAmount"] = line.price_total
            self._kd_put(entry, "FDeliveryDate", self._kd_date(
                line.date_planned or self.date_order))
            entry["FEntryNote"] = self._kd_note_text()
            entries.append(entry)
        self._kd_put(header, "FPOOrderEntry", entries)
        return header

    def _kingdee_bill_required_settings(self):
        return [
            (_("supplier"), self.partner_id and self._kd_partner_number(
                self.partner_id, "supplier")),
        ]

    # ------------------------------------------------------------------
    # Business events
    # ------------------------------------------------------------------
    def button_confirm(self):
        """Push the order to Kingdee once it is confirmed."""
        result = super().button_confirm()
        self.filtered(lambda order: order.state == "purchase")._kingdee_auto_push()
        return result

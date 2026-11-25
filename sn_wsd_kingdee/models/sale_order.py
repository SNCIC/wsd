# -*- coding: utf-8 -*-
"""Sales orders pushed to ``SAL_SaleOrder``.

The account requires sixteen values, and four of them are not obvious:

``FSalerId``
    a **BD_Saler** number, not a user: the salesman of a sales order is a master
    record of the account, so it comes from the employee linked to the order's
    salesperson, then from the account default.
``FDeliveryDate``
    the requested date of the line. Odoo keeps it on the line in this database
    (``sn_delivery_date``), with the delivery date of the order then the order date
    as fallbacks - the same chain the printed order uses.
``FReserveType`` / ``FOUTLMTUNIT``
    ``1`` (weak reservation) and ``SAL`` (over-delivery controlled on the sales
    unit): the two values a standard order of this account carries.
``FSettleOrgIds``
    the settlement organization of the line, which is the organization itself.

``FSalOrderTrace`` (logistics number) is left out on purpose: it is mandatory in
the metadata, but the whole entity can be omitted (measured on ``BD_Customer``:
a mandatory field of an entity that is not sent is not enforced). It is written
only when Odoo has a tracking number to give.
"""

from odoo import _, models


class SaleOrder(models.Model):
    """A sales order of the MES, pushed as ``SAL_SaleOrder``."""

    _name = "sale.order"
    _inherit = ["sale.order", "sn.wsd.kingdee.bill.mixin"]

    _kingdee_bill_kind_default = "sale_order"

    def _kingdee_bill_qty_amount(self):
        self.ensure_one()
        quantity = sum(self.order_line.mapped("product_uom_qty"))
        amount = sum(self.order_line.mapped("price_subtotal"))
        return quantity, amount

    def _kingdee_tax_rate(self, line):
        rate = 0.0
        for tax in line.tax_ids:
            if tax.amount_type == "percent":
                rate += tax.amount
        return rate

    def _kingdee_delivery_date(self, line):
        """Requested date of a line, the way the printed order reads it."""
        date = getattr(line, "sn_delivery_date", False) or self.commitment_date \
            or self.date_order
        return date

    def _kingdee_bill_parts(self, kind, map_row, account):
        header = {"FBillNo": self._kingdee_number()}
        self._kd_put(header, "FDate", self._kd_date(self.date_order))
        self._kd_put(header, "FSaleOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FBillTypeID", self._kd_ref(map_row.bill_type_number))
        self._kd_put(header, "FCustId", self._kd_ref(
            self._kd_partner_number(self.partner_id, "customer")))
        self._kd_put(header, "FSalerId", self._kd_ref(self._kd_employee_number(
            getattr(self.user_id, "employee_id", False), "salesman")))
        self._kd_put(header, "FNote", self._kd_note_text())
        header["FSaleOrderFinance"] = {
            "FSettleCurrId": self._kd_ref(self._kd_currency_number(self.currency_id)),
        }
        entries = []
        for line in self.order_line:
            if not line.product_uom_qty or line.display_type:
                continue
            entry = {}
            self._kd_put(entry, "FMaterialId",
                         self._kd_ref(self._kd_product_number(line.product_id)))
            entry["FQty"] = line.product_uom_qty
            uom_number = self._kd_uom_number(line.product_uom_id)
            self._kd_put(entry, "FUnitID", self._kd_ref(uom_number))
            self._kd_put(entry, "FPriceUnitId", self._kd_ref(uom_number))
            self._kd_put(entry, "FStockUnitID", self._kd_ref(uom_number))
            self._kd_put(entry, "FBaseUnitId", self._kd_ref(
                self._kd_uom_number(line.product_id.uom_id)))
            self._kd_put(entry, "FSettleOrgIds", self._kd_ref(self._kd_org("create")))
            self._kd_put(entry, "FDeliveryDate",
                         self._kd_datetime(self._kingdee_delivery_date(line)))
            entry["FReserveType"] = "1"
            entry["FOUTLMTUNIT"] = "SAL"
            entry["FPrice"] = line.price_unit
            rate = self._kingdee_tax_rate(line)
            if rate:
                entry["FEntryTaxRate"] = rate
                entry["FTaxPrice"] = round(line.price_unit * (1 + rate / 100.0), 6)
            entry["FEntryAmount"] = line.price_subtotal
            entry["FEntryNote"] = self._kd_note_text()
            entries.append(entry)
        self._kd_put(header, "FSaleOrderEntry", entries)
        return header

    def _kingdee_bill_required_settings(self):
        return [
            (_("customer"), self.partner_id and self._kd_partner_number(
                self.partner_id, "customer")),
            (_("salesman"), self._kd_employee_number(
                getattr(self.user_id, "employee_id", False), "salesman")),
        ]

    def action_confirm(self):
        """Push the order to Kingdee once it is confirmed."""
        result = super().action_confirm()
        self.filtered(lambda order: order.state == "sale")._kingdee_auto_push()
        return result

# -*- coding: utf-8 -*-
"""Transfers pushed to Kingdee: purchase receipt, vendor return, other receipt and
delivery, direct transfer, and the four production transfers.

**The kind of a transfer is read on its operation type**, never on the code or the
name: this database shares the ``incoming``, ``outgoing`` and ``internal`` codes
between the standard operations, the other operations, the vendor return and the
four MES operations. The operation type is compared with the types of its warehouse,
which is the only authoritative table (``sn_wsd_stock.models.stock_move.
_get_sn_operation_kind()`` reaches the same conclusion).

**A three step reception is three transfers** (receipt, quality control, storage).
Only the storage transfer is pushed as ``STK_InStock``: it is the one carrying the
final location and the batch a purchase receipt needs. That is what the mapping row
of the ``receipt`` kind says (``store_type_id``) and it is a data decision, not a
code one.

**The quantity is read on the move lines, one line per batch**, because a receipt of
a tracked product splits its quantity over several batches and a document whose
lines do not add up is refused by the audit of the account. The quantity field
differs per object (``FRealQty`` received, ``FQty`` other receipt, ``FRMREALQTY``
return, ``FActualQty`` material issue) and is centralised in
``kingdee_bill_mixin.QTY_FIELDS``.
"""

from odoo import _, models
from odoo.exceptions import UserError

# Warehouse field of the operation type of each kind, and the order they are tested
# in. The explicit kinds come first: an other receipt is also an incoming transfer
# and a vendor return is also an outgoing one, so the standard types must be tested
# last or they would swallow them.
KIND_BY_WAREHOUSE_FIELD = (
    ("other_in_type_id", "other_in"),
    ("other_out_type_id", "other_out"),
    ("sn_unstored_return_type_id", "vendor_return"),
    ("picking_type_issue_id", "mes_issue"),
    ("picking_type_over_pick_id", "mes_over_pick"),
    ("picking_type_return_id", "mes_return"),
    ("picking_type_receipt_id", "mes_fg_receipt"),
    ("store_type_id", "receipt"),
    ("int_type_id", "internal_transfer"),
    ("out_type_id", "delivery"),
    # The receipt and quality control steps of a three step reception are never
    # pushed: they carry no final location and no batch. They are listed so the
    # reason is explicit instead of "no mapping found".
    ("in_type_id", "receipt_step"),
    ("qc_type_id", "receipt_step"),
)


class StockPicking(models.Model):
    """A transfer of the MES, pushed as the Kingdee document of its operation."""

    _name = "stock.picking"
    _inherit = ["stock.picking", "sn.wsd.kingdee.bill.mixin"]

    # ------------------------------------------------------------------
    # Kind of the document
    # ------------------------------------------------------------------
    def _kingdee_picking_kind(self):
        """Business kind of the transfer, read on its operation type."""
        self.ensure_one()
        picking_type = self.picking_type_id
        warehouse = picking_type.warehouse_id
        if not warehouse:
            return False
        kind = False
        for field_name, candidate in KIND_BY_WAREHOUSE_FIELD:
            operation_type = getattr(warehouse, field_name, False)
            if operation_type and operation_type == picking_type:
                kind = candidate
                break
        if not kind:
            return False
        if kind == "receipt_step":
            return False
        # A material issue covers the over-pick of the same operation type when the
        # transfer says so, and a delivery of a return is the sales return.
        if kind == "mes_issue" and getattr(self, "x_is_over_pick", False):
            return "mes_over_pick"
        if kind == "delivery" and self.return_id:
            return "sale_return"
        return kind

    def _kingdee_bill_kind(self):
        return self._kingdee_picking_kind()

    def _kingdee_other_operation_code(self):
        """Code of the other operation type of the transfer, if it has one."""
        self.ensure_one()
        for field_name in ("sn_issue_type_id", "sn_receive_type_id"):
            record = getattr(self, field_name, False)
            if record:
                return (record.code or "").strip()
        return ""

    def _kingdee_bill_map(self):
        """Mapping row of this kind, narrowed on the other operation type.

        One kind may have several rows: another receipt of the R&D products and
        another receipt of the scrap recovery share ``STK_MISCELLANEOUS`` but not
        the business type of their lines. The row naming the code wins, the row
        without code is the fallback.
        """
        self.ensure_one()
        kind = self._kingdee_bill_kind()
        if not kind:
            raise UserError(_(
                "%s is not a transfer this integration pushes to Kingdee: its "
                "operation type is neither a storage step, a vendor return, another "
                "operation, a direct transfer nor a production transfer.",
            ) % self.display_name)
        rows = self.env["sn.wsd.kingdee.bill.map"].search([
            ("kind", "=", kind), ("model_name", "=", self._name), ("active", "=", True),
        ])
        if not rows:
            raise UserError(_(
                "No active Kingdee mapping for the document kind %(kind)s.",
            ) % {"kind": kind})
        code = self._kingdee_other_operation_code()
        exact = rows.filtered(lambda row: row.other_operation_code == code) if code \
            else rows.browse()
        generic = rows.filtered(lambda row: not row.other_operation_code)
        return (exact or generic or rows)[:1]

    # ------------------------------------------------------------------
    # Lines
    # ------------------------------------------------------------------
    def _kingdee_move_lines(self):
        """One row per product and batch, aggregated on the done move lines.

        The stock status is read on the batch, so two batches of the same product
        held in different states stay two lines: merging them would hide a frozen
        batch inside an available one.
        """
        self.ensure_one()
        rows = {}
        for line in self.move_line_ids:
            quantity = line.quantity or 0.0
            if not quantity:
                continue
            lot = line.lot_id
            product = line.product_id
            key = (product.id, lot.id)
            row = rows.get(key)
            if not row:
                move = line.move_id
                price = getattr(move, "price_unit", 0.0) or 0.0
                row = rows[key] = {
                    "product": product,
                    "lot": lot,
                    "quantity": 0.0,
                    "uom": line.product_uom_id or product.uom_id,
                    "price": price,
                    "note": (getattr(move, "reference", "") or move.origin or ""),
                }
            row["quantity"] += quantity
        return [row for row in rows.values() if row["product"]]

    def _kingdee_entry(self, row, qty_key="FQty", material_key="FMaterialId",
                       uom_key="FUnitID", lot_key="FLot"):
        """Common entry of a stock document, keyed the way the object expects it."""
        self.ensure_one()
        entry = {}
        self._kd_put(entry, material_key,
                     self._kd_ref(self._kd_product_number(row["product"])))
        self._kd_put(entry, qty_key, row["quantity"])
        self._kd_put(entry, uom_key, self._kd_ref(self._kd_uom_number(row["uom"])))
        self._kd_put(entry, lot_key, self._kd_ref(self._kd_lot_number(row["lot"])))
        return entry

    def _kingdee_bill_qty_amount(self):
        """Quantity and amount of the transfer, for the read-back comparison."""
        self.ensure_one()
        quantity = sum(self.move_line_ids.mapped("quantity"))
        amount = 0.0
        for row in self._kingdee_move_lines():
            amount += row["quantity"] * (row["price"] or 0.0)
        return quantity, amount

    # ------------------------------------------------------------------
    # Payload parts
    # ------------------------------------------------------------------
    def _kingdee_bill_parts(self, kind, map_row, account):
        builder = getattr(self, "_kingdee_parts_%s" % kind, None)
        if not builder:
            raise UserError(_("The document kind %s is not implemented.") % kind)
        return builder(map_row, account)

    def _kd_document_employee(self):
        """Employee who handled the transfer, read on the document itself."""
        self.ensure_one()
        for field_name in ("sn_receive_employee_id", "sn_issue_employee_id"):
            employee = getattr(self, field_name, False)
            if employee:
                return employee
        user = self.create_uid
        employee = getattr(user, "employee_id", False)
        if employee:
            return employee
        employees = getattr(user, "employee_ids", False)
        return employees[:1] if employees else self.env["hr.employee"]

    def _kd_header_common(self, map_row, account, org_field="FStockOrgId",
                          date_field="FDate", type_field="FBillTypeID"):
        """Header shared by the stock documents: number, date, organization, type."""
        header = {}
        self._kd_put(header, date_field, self._kd_date(self.scheduled_date or self.date_done))
        self._kd_put(header, org_field, self._kd_ref(self._kd_org("create")))
        self._kd_put(header, type_field, self._kd_ref(map_row.bill_type_number))
        return header

    # ---- purchase receipt -------------------------------------------------
    def _kingdee_parts_receipt(self, map_row, account):
        """``STK_InStock`` of the storage transfer of a three step reception."""
        header = self._kd_header_common(map_row, account)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        self._kd_put(header, "FOwnerTypeIdHead", owner_type)
        self._kd_put(header, "FOwnerIdHead", owner)
        self._kd_put(header, "FPurchaseOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FBusinessType", (map_row.business_type or "").strip())
        if self.partner_id:
            self._kd_put(header, "FSupplierId", self._kd_ref(
                self._kd_partner_number(self.partner_id, "supplier")))
        self._kd_put(header, "FStockerId", self._kd_ref(
            self._kd_employee_number(self._kd_document_employee(), "stocker")))
        header["FInStockFin"] = {
            "FSettleOrgId": self._kd_ref(self._kd_org("create")),
            "FSettleCurrId": self._kd_ref(self._kd_currency_number()),
            "FPriceTimePoint": "1",
        }
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FRealQty")
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_dest_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            self._kd_put(entry, "FBaseUnitID", self._kd_ref(
                self._kd_uom_number(row["product"].uom_id)))
            self._kd_put(entry, "FPriceUnitID", self._kd_ref(self._kd_uom_number(row["uom"])))
            self._kd_put(entry, "FRemainInStockUnitId",
                         self._kd_ref(self._kd_uom_number(row["uom"])))
            self._kd_put(entry, "FOwnerTypeId", owner_type)
            self._kd_put(entry, "FOwnerId", owner)
            self._kd_put(entry, "FKeeperTypeId", self._kd_owner_type(account, keeper=True))
            self._kd_put(entry, "FKeeperId", owner)
            if row["price"]:
                entry["FPrice"] = row["price"]
            self._kd_put(entry, "FNote", row["note"] or self._kd_note_text())
            entries.append(entry)
        self._kd_put(header, "FInStockEntry", entries)
        return header

    # ---- vendor return ----------------------------------------------------
    def _kingdee_parts_vendor_return(self, map_row, account):
        """``PUR_MRB``: goods sent back to the supplier."""
        header = self._kd_header_common(map_row, account)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        self._kd_put(header, "FOwnerTypeIdHead", owner_type)
        self._kd_put(header, "FOwnerIdHead", owner)
        self._kd_put(header, "FPurchaseOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FRequireOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FBusinessType", (map_row.business_type or "").strip())
        # A return before the goods are stored is a quality return, after storage a
        # stock return: the two paths of the Odoo return operation.
        header["FMRTYPE"] = "A" if self.location_id.usage != "internal" else "B"
        header["FMRMODE"] = "A"
        if self.partner_id:
            self._kd_put(header, "FSupplierID", self._kd_ref(
                self._kd_partner_number(self.partner_id, "supplier")))
        self._kd_put(header, "FSTOCKERID", self._kd_ref(
            self._kd_employee_number(self._kd_document_employee(), "stocker")))
        header["FPURMRBFIN"] = {
            "FSettleOrgId": self._kd_ref(self._kd_org("create")),
            "FSettleCurrId": self._kd_ref(self._kd_currency_number()),
            "FPRICETIMEPOINT": "1",
        }
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FRMREALQTY",
                                        material_key="FMATERIALID")
            self._kd_put(entry, "FSTOCKID",
                         self._kd_ref(self._kd_stock_number(self.location_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            self._kd_put(entry, "FPriceUnitID", self._kd_ref(self._kd_uom_number(row["uom"])))
            self._kd_put(entry, "FCarryUnitId", self._kd_ref(self._kd_uom_number(row["uom"])))
            self._kd_put(entry, "FOWNERTYPEID", owner_type)
            self._kd_put(entry, "FOWNERID", owner)
            if row["price"]:
                entry["FPrice"] = row["price"]
            entries.append(entry)
        self._kd_put(header, "FPURMRBENTRY", entries)
        return header

    # ---- other receipt ----------------------------------------------------
    def _kingdee_parts_other_in(self, map_row, account):
        """``STK_MISCELLANEOUS``: goods entering the stock without an order."""
        header = self._kd_header_common(map_row, account)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        employee = self._kd_document_employee()
        self._kd_put(header, "FOwnerTypeIdHead", owner_type)
        self._kd_put(header, "FStockDirect", "GENERAL")
        self._kd_put(header, "FDEPTID", self._kd_ref(
            self._kd_department_number(getattr(self, "sn_receive_department_id", False))))
        self._kd_put(header, "FACCEPTANCE", self._kd_ref(
            self._kd_employee_number(employee)))
        self._kd_put(header, "FSTOCKERID", self._kd_ref(
            self._kd_employee_number(employee, "stocker")))
        # The business type of this object is a custom field of the account
        # (F_QNBG_Combo) whose fifteen values match the operation types of Odoo.
        business_type = (map_row.other_operation_types or {}).get(
            self._kingdee_other_operation_code())
        if not business_type:
            raise UserError(_(
                "%(document)s has no other operation type or the mapping has no "
                "business type for it: configure the operation type of the transfer.",
            ) % {"document": self.display_name})
        header["F_QNBG_Combo"] = business_type
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FQty", material_key="FMATERIALID",
                                        uom_key="FUnitID", lot_key="FLot")
            self._kd_put(entry, "FSTOCKID",
                         self._kd_ref(self._kd_stock_number(self.location_dest_id)))
            self._kd_put(entry, "FSTOCKSTATUSID",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            self._kd_put(entry, "FOWNERTYPEID", owner_type)
            self._kd_put(entry, "FOWNERID", owner)
            self._kd_put(entry, "FKEEPERTYPEID", self._kd_owner_type(account, keeper=True))
            self._kd_put(entry, "FKEEPERID", owner)
            self._kd_put(entry, "FEntryNote", row["note"] or self._kd_note_text())
            entries.append(entry)
        self._kd_put(header, "FEntity", entries)
        return header

    # ---- other delivery ---------------------------------------------------
    def _kingdee_parts_other_out(self, map_row, account):
        """``STK_MisDelivery``: goods leaving the stock without an order."""
        header = self._kd_header_common(map_row, account)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        employee = self._kd_document_employee()
        self._kd_put(header, "FOwnerTypeIdHead", owner_type)
        self._kd_put(header, "FStockDirect", "GENERAL")
        self._kd_put(header, "FDeptId", self._kd_ref(
            self._kd_department_number(getattr(self, "sn_issue_department_id", False))))
        self._kd_put(header, "FPickerId", self._kd_ref(self._kd_employee_number(employee)))
        self._kd_put(header, "FStockerId", self._kd_ref(
            self._kd_employee_number(employee, "stocker")))
        business_type = (map_row.other_operation_types or {}).get(
            self._kingdee_other_operation_code())
        if not business_type:
            raise UserError(_(
                "%s has no other operation type or the mapping has no business type "
                "for it.",) % self.display_name)
        header["FBizType"] = business_type
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FQty", material_key="FMaterialId",
                                        uom_key="FUnitID")
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            self._kd_put(entry, "FBaseUnitId", self._kd_ref(
                self._kd_uom_number(row["product"].uom_id)))
            self._kd_put(entry, "FOwnerTypeId", owner_type)
            self._kd_put(entry, "FOwnerId", owner)
            self._kd_put(entry, "FKeeperTypeId", self._kd_owner_type(account, keeper=True))
            self._kd_put(entry, "FKeeperId", owner)
            self._kd_put(entry, "FEntryNote", row["note"] or self._kd_note_text())
            entries.append(entry)
        self._kd_put(header, "FEntity", entries)
        return header

    # ---- direct transfer --------------------------------------------------
    def _kingdee_parts_internal_transfer(self, map_row, account):
        """``STK_TransferDirect``: goods moving between two warehouses."""
        header = self._kd_header_common(map_row, account)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        self._kd_put(header, "FStockOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FStockOutOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FOwnerTypeIdHead", owner_type)
        self._kd_put(header, "FOwnerTypeOutIdHead", owner_type)
        header["FTransferBizType"] = (map_row.transfer_biz_type or "InnerOrgTransfer").strip()
        header["FTransferDirect"] = (map_row.transfer_direct or "GENERAL").strip()
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FQty", material_key="FMaterialId",
                                        uom_key="FUnitID")
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_dest_id)))
            self._kd_put(entry, "FStockOutId",
                         self._kd_ref(self._kd_stock_number(self.location_id)))
            self._kd_put(entry, "FBaseUnitId", self._kd_ref(
                self._kd_uom_number(row["product"].uom_id)))
            for type_key, id_key in (
                    ("FOwnerTypeId", "FOwnerId"),
                    ("FOwnerTypeOutId", "FOwnerOutId"),
                    ("FKeeperTypeId", "FKeeperId"),
                    ("FKeeperTypeOutId", "FKeeperOutId")):
                keeper = "Keeper" in type_key
                entry[type_key] = self._kd_owner_type(account, keeper=keeper)
                entry[id_key] = owner
            self._kd_put(entry, "FNoteEntry", row["note"] or self._kd_note_text())
            entries.append(entry)
        self._kd_put(header, "FBillEntry", entries)
        return header

    # ---- production transfers ---------------------------------------------
    def _kd_production(self):
        """Manufacturing order behind a production transfer, if any."""
        self.ensure_one()
        mes_order = getattr(self, "x_mes_order_id", False)
        if mes_order:
            return mes_order.production_id
        return self.env["mrp.production"]

    def _kd_mo_number(self, production):
        """Kingdee number of the manufacturing order, which must already be pushed.

        A material issue points at the Kingdee production order by its number: the
        Odoo one means nothing to the account and the audit of the account would
        refuse the line. Pushing a transfer whose order is not in the account is
        therefore refused here, with the reason, instead of failing later.
        """
        if not production:
            raise UserError(_(
                "%s has no manufacturing order: a production transfer can only be "
                "pushed once its order is identified.",) % self.display_name)
        number = (production.kingdee_number or "").strip()
        if not number:
            raise UserError(_(
                "The manufacturing order %(order)s is not in Kingdee yet: push it "
                "before its transfers.",
            ) % {"order": production.name})
        return number

    def _kd_production_header(self, map_row, account, org_field="FPrdOrgId"):
        """Header of a production transfer: date, production and stock organization."""
        header = {}
        self._kd_put(header, "FDate", self._kd_date(self.date_done or self.scheduled_date))
        self._kd_put(header, org_field, self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FStockOrgId", self._kd_ref(self._kd_org("create")))
        self._kd_put(header, "FBillType", self._kd_ref(map_row.bill_type_number))
        return header

    def _kingdee_parts_mes_issue(self, map_row, account):
        """``PRD_PickMtrl``: components issued to a manufacturing order."""
        production = self._kd_production()
        header = self._kd_production_header(map_row, account)
        header["FDescription"] = self._kd_note_text()
        self._kd_put(header, "FOwnerId0", self._kd_owner(account))
        self._kd_put(header, "FPickerId", self._kd_ref(
            self._kd_employee_number(self._kd_document_employee())))
        self._kd_put(header, "FSTOCKERID", self._kd_ref(
            self._kd_employee_number(self._kd_document_employee(), "stocker")))
        mo_number = self._kd_mo_number(production)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FActualQty",
                                        material_key="FMaterialId", uom_key="FUnitID")
            entry["FAppQty"] = row["quantity"]
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            self._kd_put(entry, "FBaseUnitId", self._kd_ref(
                self._kd_uom_number(row["product"].uom_id)))
            self._kd_put(entry, "FStockUnitId", self._kd_ref(self._kd_uom_number(row["uom"])))
            entry["FMoBillNo"] = mo_number
            self._kd_put(entry, "FOwnerTypeId", owner_type)
            self._kd_put(entry, "FOwnerId", owner)
            self._kd_put(entry, "FKeeperTypeId", self._kd_owner_type(account, keeper=True))
            self._kd_put(entry, "FKeeperId", owner)
            self._kd_put(entry, "FParentOwnerTypeId", owner_type)
            self._kd_put(entry, "FParentOwnerId", owner)
            entries.append(entry)
        self._kd_put(header, "FEntity", entries)
        return header

    def _kingdee_parts_mes_over_pick(self, map_row, account):
        """The over-pick is a material issue of the same object."""
        return self._kingdee_parts_mes_issue(map_row, account)

    def _kingdee_parts_mes_return(self, map_row, account):
        """``PRD_ReturnMtrl``: unused components sent back to the stock."""
        production = self._kd_production()
        header = self._kd_production_header(map_row, account)
        header["FDescription"] = self._kd_note_text()
        employee = self._kd_document_employee()
        self._kd_put(header, "FSTOCKERID", self._kd_ref(
            self._kd_employee_number(employee, "stocker")))
        self._kd_put(header, "FReturnerId", self._kd_ref(self._kd_employee_number(employee)))
        mo_number = self._kd_mo_number(production)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FQty", material_key="FMaterialId",
                                        uom_key="FUnitID")
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_dest_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            self._kd_put(entry, "FBaseUnitId", self._kd_ref(
                self._kd_uom_number(row["product"].uom_id)))
            # 1 良品退料: MES returns the components it did not consume.
            entry["FReturnType"] = "1"
            entry["FSrcBillType"] = "PRD_PickMtrl"
            entry["FMoBillNo"] = mo_number
            self._kd_put(entry, "FOwnerTypeId", owner_type)
            self._kd_put(entry, "FOwnerId", owner)
            self._kd_put(entry, "FKeeperTypeId", self._kd_owner_type(account, keeper=True))
            self._kd_put(entry, "FKeeperId", owner)
            self._kd_put(entry, "FParentOwnerTypeId", owner_type)
            self._kd_put(entry, "FParentOwnerId", owner)
            entries.append(entry)
        self._kd_put(header, "FEntity", entries)
        return header

    def _kingdee_parts_mes_fg_receipt(self, map_row, account):
        """``PRD_INSTOCK``: finished goods entering the stock."""
        production = self._kd_production()
        header = self._kd_production_header(map_row, account)
        header["FDescription"] = self._kd_note_text()
        self._kd_put(header, "FOwnerId0", self._kd_owner(account))
        self._kd_put(header, "FSTOCKERID", self._kd_ref(
            self._kd_employee_number(self._kd_document_employee(), "stocker")))
        mo_number = self._kd_mo_number(production)
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FRealQty",
                                        material_key="FMaterialId", uom_key="FUnitID")
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_dest_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            self._kd_put(entry, "FBaseUnitId", self._kd_ref(
                self._kd_uom_number(row["product"].uom_id)))
            # 1 合格品入库: a finished good is booked as good until the quality
            # department holds its batch.
            entry["FInStockType"] = "1"
            entry["FMoBillNo"] = mo_number
            self._kd_put(entry, "FOwnerTypeId", owner_type)
            self._kd_put(entry, "FOwnerId", owner)
            self._kd_put(entry, "FKeeperTypeId", self._kd_owner_type(account, keeper=True))
            self._kd_put(entry, "FKeeperId", owner)
            entries.append(entry)
        self._kd_put(header, "FEntity", entries)
        return header

    # ---- sales delivery and return ----------------------------------------
    def _kingdee_parts_delivery(self, map_row, account):
        """``SAL_OUTSTOCK``: goods shipped to a customer.

        The entity keys of this object differ from the sales order ones
        (``SubHeadEntity`` and ``FEntity``), which is why each object keeps its own
        builder instead of a shared one with a renaming table.
        """
        header = self._kd_header_common(map_row, account, org_field="FSaleOrgId")
        self._kd_put(header, "FStockOrgId", self._kd_ref(self._kd_org("create")))
        sale = self.sale_id
        partner = sale.partner_id if sale else self.partner_id
        self._kd_put(header, "FCustomerID", self._kd_ref(
            self._kd_partner_number(partner, "customer")))
        self._kd_put(header, "FSaleDeptID", self._kd_ref(self._kd_sales_department_number()))
        self._kd_put(header, "FSalesManID", self._kd_ref(self._kd_employee_number(
            getattr(getattr(sale, "user_id", False), "employee_id", False), "salesman")))
        header["SubHeadEntity"] = {
            "FSettleOrgID": self._kd_ref(self._kd_org("create")),
            "FSettleCurrID": self._kd_ref(self._kd_currency_number(
                sale.currency_id if sale else None)),
        }
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FRealQty",
                                        material_key="FMaterialID", uom_key="FUnitID")
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            entry["FOwnerTypeID"] = owner_type
            entry["FOwnerID"] = owner
            self._kd_put(entry, "FEntrynote", row["note"] or self._kd_note_text())
            entries.append(entry)
        self._kd_put(header, "FEntity", entries)
        return header

    def _kingdee_parts_sale_return(self, map_row, account):
        """``SAL_RETURNSTOCK``: goods coming back from a customer."""
        header = self._kd_header_common(map_row, account, org_field="FSaleOrgId")
        self._kd_put(header, "FStockOrgId", self._kd_ref(self._kd_org("create")))
        sale = self.sale_id
        source = self.return_id
        partner = (sale.partner_id if sale else False) or self.partner_id
        if not partner and source:
            partner = source.partner_id
        self._kd_put(header, "FRetcustId", self._kd_ref(
            self._kd_partner_number(partner, "customer")))
        header["SubHeadEntity"] = {
            "FSettleOrgId": self._kd_ref(self._kd_org("create")),
            "FSettleCurrId": self._kd_ref(self._kd_currency_number(
                sale.currency_id if sale else None)),
        }
        return_type = (map_row.return_type_number or "").strip()
        if not return_type:
            raise UserError(_(
                "Configure the return type of the sales return mapping: the account "
                "requires one on every line (FReturnType).",
            ))
        owner = self._kd_owner(account)
        owner_type = self._kd_owner_type(account)
        entries = []
        for row in self._kingdee_move_lines():
            entry = self._kingdee_entry(row, qty_key="FRealQty",
                                        material_key="FMaterialId", uom_key="FUnitID")
            self._kd_put(entry, "FStockId",
                         self._kd_ref(self._kd_stock_number(self.location_dest_id)))
            self._kd_put(entry, "FStockStatusId",
                         self._kd_ref(self._kd_stock_status(row["lot"])))
            entry["FReturnType"] = self._kd_ref(return_type)
            entry["FDeliveryDate"] = self._kd_datetime(
                self.date_done or self.scheduled_date)
            self._kd_put(entry, "FOwnerTypeId", owner_type)
            self._kd_put(entry, "FOwnerId", owner)
            self._kd_put(entry, "FNote", row["note"] or self._kd_note_text())
            entries.append(entry)
        self._kd_put(header, "FEntity", entries)
        return header

    # ------------------------------------------------------------------
    # Business events
    # ------------------------------------------------------------------
    def _kingdee_bill_required_settings(self):
        """Account values the kind cannot be accepted without."""
        self.ensure_one()
        kind = self._kingdee_bill_kind()
        employee = self._kd_document_employee()
        checks = []
        if kind in ("other_in", "other_out", "mes_return"):
            checks.extend([
                (_("department"), self._kd_department_number(
                    getattr(self, "sn_issue_department_id", False)
                    or getattr(self, "sn_receive_department_id", False))),
                (_("handling employee"), self._kd_employee_number(employee)),
                (_("warehouse keeper"), self._kd_employee_number(employee, "stocker")),
            ])
        if kind in ("other_in", "other_out"):
            checks.append((_("other operation type"),
                           self._kingdee_other_operation_code()))
        if kind in ("receipt", "vendor_return"):
            checks.append((_("supplier"), self.partner_id and self._kd_partner_number(
                self.partner_id, "supplier")))
        if kind == "delivery":
            checks.extend([
                (_("sales department"), self._kd_sales_department_number()),
                (_("salesman"), self._kd_employee_number(
                    getattr(getattr(self.sale_id, "user_id", False), "employee_id", False),
                    "salesman")),
            ])
        if kind == "sale_return":
            checks.append((_("return type"),
                           self._kingdee_bill_map().return_type_number))
        if kind in ("mes_issue", "mes_over_pick", "mes_return", "mes_fg_receipt"):
            production = self._kd_production()
            checks.append((_("manufacturing order in Kingdee"),
                           production and production.kingdee_number))
        return checks

    def button_validate(self):
        """Push the transfer to Kingdee once it is done."""
        result = super().button_validate()
        if self.state == "done":
            self._kingdee_auto_push()
        return result

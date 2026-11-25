# -*- coding: utf-8 -*-
"""One row per kind of document the account receives.

The anchor of a stock document is its **operation type**, never its code or its
name: several operation types of this database share the codes ``incoming``,
``outgoing`` and ``internal`` (other receipts, vendor returns, quality control,
storage and the four MES operations), so a code cannot tell them apart - the same
conclusion ``sn_wsd_stock.models.stock_move._get_sn_operation_kind()`` reaches.

Each row therefore names

* the business kind (the Odoo side of the mapping, e.g. ``receipt``),
* the operation type **field of the warehouse** it is about (``store_type_id`` for
  the storage transfer of a three step reception, ``other_in_type_id`` for another
  receipt), resolved at runtime,
* the Kingdee object (``form_id``) and its bill type (``bill_type_number``).

Bill types are account data and were read from this account's ``BOS_BillType``
(``RKD01_SYS`` standard purchase receipt, ``CGDD01_SYS`` standard purchase order,
``ZJDB01_SYS`` direct transfer, ...). They are stored on the row so that a change of
numbering rule is a data change, not a code change.

A kind that is not matched by any active row is simply not pushed: the document
stays ``not_synced`` and the reason is reported when someone asks for a push.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Odoo model the kind is read from.
BILL_MODEL_SELECTION = [
    ("stock.picking", "Transfer"),
    ("purchase.order", "Purchase Order"),
    ("sale.order", "Sales Order"),
    ("mrp.production", "Manufacturing Order"),
]

# Business kinds, and what the default payload of each one needs. ``form_id``,
# ``bill_type`` and ``picking_type_field`` are the values read from this account on
# 2026-11-25; they are the defaults of a freshly created row, not hard coded ones.
BILL_KINDS = [
    ("purchase_order", "Purchase Order · PUR_PurchaseOrder"),
    ("receipt", "Purchase Receipt · STK_InStock"),
    ("vendor_return", "Purchase Return · PUR_MRB"),
    ("sale_order", "Sales Order · SAL_SaleOrder"),
    ("delivery", "Sales Delivery · SAL_OUTSTOCK"),
    ("sale_return", "Sales Return · SAL_RETURNSTOCK"),
    ("other_in", "Other Receipt · STK_MISCELLANEOUS"),
    ("other_out", "Other Delivery · STK_MisDelivery"),
    ("internal_transfer", "Direct Transfer · STK_TransferDirect"),
    ("production_order", "Production Order · PRD_MO"),
    ("mes_issue", "Material Issue · PRD_PickMtrl"),
    ("mes_over_pick", "Material Over-pick · PRD_PickMtrl"),
    ("mes_return", "Material Return · PRD_ReturnMtrl"),
    ("mes_fg_receipt", "Finished Goods Receipt · PRD_INSTOCK"),
]

BILL_KIND_DEFAULTS = {
    "purchase_order": {
        "model_name": "purchase.order", "form_id": "PUR_PurchaseOrder",
        "bill_type_number": "CGDD01_SYS", "business_type": "CG",
        "auto_audit": True,
    },
    "receipt": {
        "model_name": "stock.picking", "picking_type_field": "store_type_id",
        "form_id": "STK_InStock", "bill_type_number": "RKD01_SYS",
        "business_type": "CG", "auto_audit": True,
    },
    "vendor_return": {
        "model_name": "stock.picking",
        "picking_type_field": "sn_unstored_return_type_id",
        "form_id": "PUR_MRB", "bill_type_number": "TLD01_SYS",
        "business_type": "CG", "auto_audit": True,
    },
    "sale_order": {
        "model_name": "sale.order", "form_id": "SAL_SaleOrder",
        "bill_type_number": "XSDD01_SYS", "auto_audit": True,
    },
    "delivery": {
        "model_name": "stock.picking", "picking_type_field": "out_type_id",
        "form_id": "SAL_OUTSTOCK", "bill_type_number": "XSCKD01_SYS",
        "auto_audit": True,
    },
    "sale_return": {
        "model_name": "stock.picking", "picking_type_field": "out_type_id",
        "form_id": "SAL_RETURNSTOCK", "bill_type_number": "XSTHD01_SYS",
        "auto_audit": True,
    },
    "other_in": {
        "model_name": "stock.picking", "picking_type_field": "other_in_type_id",
        "form_id": "STK_MISCELLANEOUS", "bill_type_number": "QTRKD01_SYS",
        "auto_audit": True,
    },
    "other_out": {
        "model_name": "stock.picking", "picking_type_field": "other_out_type_id",
        "form_id": "STK_MisDelivery", "bill_type_number": "QTCKD01_SYS",
        "auto_audit": True,
    },
    "internal_transfer": {
        "model_name": "stock.picking", "picking_type_field": "int_type_id",
        "form_id": "STK_TransferDirect", "bill_type_number": "ZJDB01_SYS",
        "auto_audit": True,
    },
    "production_order": {
        "model_name": "mrp.production", "form_id": "PRD_MO",
        "bill_type_number": "SCDD03_SYS", "auto_audit": True,
    },
    "mes_issue": {
        "model_name": "stock.picking", "picking_type_field": "picking_type_issue_id",
        "form_id": "PRD_PickMtrl", "bill_type_number": "SCLLD01_SYS",
        "auto_audit": True,
    },
    "mes_over_pick": {
        "model_name": "stock.picking", "picking_type_field": "picking_type_over_pick_id",
        "form_id": "PRD_PickMtrl", "bill_type_number": "SCLLD01_SYS",
        "auto_audit": True,
    },
    "mes_return": {
        "model_name": "stock.picking", "picking_type_field": "picking_type_return_id",
        "form_id": "PRD_ReturnMtrl", "bill_type_number": "SCTLD01_SYS",
        "auto_audit": True,
    },
    "mes_fg_receipt": {
        "model_name": "stock.picking", "picking_type_field": "picking_type_receipt_id",
        "form_id": "PRD_INSTOCK", "bill_type_number": "SCRKD02_SYS",
        "auto_audit": True,
    },
}

# Other operation type (sn.wsd.stock.other.operation.type.code) -> the 业务类型
# selection of STK_MISCELLANEOUS.F_QNBG_Combo and STK_MisDelivery.FBizType. Both
# fields share the same fifteen values of this account, read from its metadata on
# 2026-11-25. The mapping is stored on the row so the account can change it.
DEFAULT_OPERATION_TYPES = {
    "MEA": "9",   # 计量误差调整
    "CSW": "B",   # 代码互换
    "ASS": "C",   # 售后服务
    "RPS": "3",   # 返修表
    "SPS": "5",   # 备表
    "OSI": "1",   # 办公用品领用
    "RDI": "6",   # 研发领用
    "RDP": "D",   # 研发产品
    "RDS": "E",   # 研发废料
    "SCS": "8",   # 废料销售
    "SCP": "7",   # 报废产品
    "SRR": "2",   # 报废残值收回
    "CSP": "0",   # 客户样品
}


class SnWsdKingdeeBillMap(models.Model):
    """One document kind of the account, and how an Odoo document reaches it."""

    _name = "sn.wsd.kingdee.bill.map"
    _description = "Kingdee Bill Mapping"
    _order = "model_name, sequence, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(string="Document", required=True, translate=True)
    model_name = fields.Selection(
        BILL_MODEL_SELECTION, string="Odoo Model", required=True, index=True,
    )
    kind = fields.Selection(
        BILL_KINDS, string="Kind", required=True, index=True,
        help="Business kind of the document. For a transfer it is read from the "
             "operation type of its warehouse, which is what tells a purchase "
             "receipt from a production receipt.",
    )
    picking_type_field = fields.Char(
        string="Warehouse Operation Field",
        help="Field of stock.warehouse holding the operation type of this kind, e.g. "
             "store_type_id for the storage transfer of a three step reception. The "
             "type is compared at runtime: several types share the incoming, "
             "outgoing and internal codes, so a code cannot tell them apart.",
    )
    other_operation_code = fields.Char(
        string="Other Operation Type",
        help="Restricts the kind to the transfers whose other operation type carries "
             "this code, e.g. RDP for the R&D products receipt. Empty matches every "
             "other operation type.",
    )
    form_id = fields.Char(string="Kingdee Object", required=True)
    bill_type_number = fields.Char(
        string="Bill Type", required=True,
        help="Number of the BOS_BillType of this account, e.g. RKD01_SYS for a "
             "standard purchase receipt or CGDD01_SYS for a standard purchase order.",
    )
    note_field = fields.Char(
        string="Note Field",
        help="Kingdee field receiving the Odoo document number, which is what lets a "
             "double entry month be reconciled line by line. Empty when the object "
             "has no free text header field: purchase orders and purchase receipts "
             "only carry a line note.",
    )
    business_type = fields.Char(
        string="Business Type",
        help="FBusinessType of the object (CG standard purchase, ...). Empty when the "
             "object has none.",
    )
    transfer_biz_type = fields.Char(
        string="Transfer Business Type",
        help="FTransferBizType of a transfer, InnerOrgTransfer for a transfer inside "
             "the organization.",
    )
    transfer_direct = fields.Char(
        string="Transfer Direction",
        help="FTransferDirect, GENERAL for a normal transfer.",
    )
    return_type_number = fields.Char(
        string="Return Type",
        help="BOS_ASSISTANTDATA_SELECT number of the FReturnType of a sales return.",
    )
    production_bom_type = fields.Char(
        string="BOM Expansion", default="2",
        help="FPPBOMType of a production order: 2 for the main product only, 1 to "
             "expand the bill of materials.",
    )
    other_operation_types = fields.Json(
        string="Operation Type to Business Type",
        default=lambda self: dict(DEFAULT_OPERATION_TYPES),
        help="Mapping of an other operation type code (RDP, SCS, ...) to the 业务类型 "
             "selection of the other receipt and other delivery.",
    )
    auto_push = fields.Boolean(
        string="Push When Done", default=True,
        help="Push the document as soon as it is done. Off: only a manual push or the "
             "scheduled action sends it.",
    )
    auto_audit = fields.Boolean(
        string="Submit and Audit", default=True,
        help="Run Submit then Audit after Save: an audited document is what moves the "
             "stock and the cost of the account.",
    )
    verify_readback = fields.Boolean(
        string="Verify Read-back", default=True,
        help="Read the document back after the audit and compare its number, status "
             "and amount with what was sent. This is the evidence the acceptance "
             "criteria of the migration ask for.",
    )
    save_options = fields.Json(
        string="Save Options",
        help="Extra parameters merged into the Save request, e.g. "
             "{\"IsAutoAdjustField\": \"True\"} for an account that recomputes the "
             "amounts of a document.",
    )
    fixed_values = fields.Json(
        string="Fixed Values",
        help="Extra Kingdee fields written on every document of this kind, keyed by "
             "field name, e.g. {\"FOwnerTypeId\": \"BD_OwnerOrg\"}. A reference is "
             "given as {\"FNumber\": \"100\"}.",
    )
    pending_count = fields.Integer(string="Pending", compute="_compute_counts")
    failed_count = fields.Integer(string="Failed", compute="_compute_counts")

    @api.onchange("kind")
    def _onchange_kind(self):
        defaults = BILL_KIND_DEFAULTS.get(self.kind, {})
        for key, value in defaults.items():
            setattr(self, key, value)
        if not self.name and self.kind:
            self.name = dict(BILL_KINDS)[self.kind]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            defaults = BILL_KIND_DEFAULTS.get(vals.get("kind"), {})
            for key, value in defaults.items():
                vals.setdefault(key, value)
            if vals.get("kind") and not vals.get("name"):
                vals["name"] = dict(BILL_KINDS)[vals["kind"]]
        return super().create(vals_list)

    @api.constrains("form_id", "kind")
    def _check_kind(self):
        for row in self:
            if row.form_id and row.kind:
                expected = BILL_KIND_DEFAULTS.get(row.kind, {}).get("form_id")
                if expected and expected != row.form_id:
                    raise ValidationError(_(
                        "%(kind)s is sent to %(expected)s, not to %(form)s.",
                    ) % {
                        "kind": dict(BILL_KINDS).get(row.kind),
                        "expected": expected,
                        "form": row.form_id,
                    })

    @api.depends("form_id", "kind")
    def _compute_counts(self):
        """Pending and failed documents of this row.

        Counted on the pending states only, which is the set an operator acts on and
        a bounded search: counting the pushed documents of a kind would walk the
        whole transfer table on every render of the console.
        """
        for row in self:
            row.pending_count = 0
            row.failed_count = 0
            model = self.env.get(row.model_name or "")
            if model is None or "kingdee_sync_state" not in model._fields:
                continue
            records = model.search([
                ("kingdee_sync_state", "in", ("not_synced", "error")),
            ], limit=2000)
            mine = records.filtered(lambda record: self._belongs(record, row))
            row.pending_count = len(mine)
            row.failed_count = len(mine.filtered(
                lambda record: record.kingdee_sync_state == "error"))

    @staticmethod
    def _belongs(record, row):
        """Whether ``record`` is a document of ``row`` (never raising)."""
        try:
            return record._kingdee_bill_map().id == row.id
        except Exception:  # noqa: BLE001 - a document without mapping is not ours
            return False

    def _pending_documents(self, limit=100):
        """Pending documents of this row that are due, oldest first."""
        self.ensure_one()
        model = self.env[self.model_name]
        now = fields.Datetime.now()
        records = model.search([
            ("kingdee_sync_state", "in", ("not_synced", "error")),
            "|", ("kingdee_next_retry_at", "=", False),
            ("kingdee_next_retry_at", "<=", now),
        ], limit=limit, order="kingdee_next_retry_at asc, id asc")
        return records.filtered(lambda record: self._belongs(record, self))

    def _push_pending(self, limit=100):
        """Push what this row may push now; return the number of successes."""
        self.ensure_one()
        records = self._pending_documents(limit=limit)
        if not records:
            return 0
        summary = records._kingdee_push_records()
        return summary["success"]

    def action_push_pending(self):
        """Push the pending documents of this row (button of the console)."""
        self.ensure_one()
        records = self._pending_documents()
        if not records:
            return self.env["sn.wsd.kingdee.sync.mixin"]._kingdee_notify(
                _("Kingdee"), _("%s: nothing to push.") % self.name)
        summary = records._kingdee_push_records()
        return records._kingdee_push_notification(summary)

    @api.model
    def _cron_push_pending_bills(self):
        """Scheduled retry of every document kind that pushes automatically."""
        total = 0
        for row in self.search([("active", "=", True), ("auto_push", "=", True)]):
            try:
                total += row._push_pending()
            except Exception:  # noqa: BLE001 - one kind must not stop the others
                _logger.exception("Scheduled Kingdee push failed for %s", row.name)
        return total

    @api.model
    def _for_kind(self, kind, model_name=None):
        """Active row of ``kind`` (optionally narrowed on the Odoo model)."""
        domain = [("kind", "=", kind), ("active", "=", True)]
        if model_name:
            domain.append(("model_name", "=", model_name))
        return self.search(domain, limit=1)

    def action_open_documents(self):
        """List the documents of this kind, so a count is never a dead end."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": self.model_name,
            "view_mode": "list,form",
            "domain": self.env[self.model_name]._kingdee_target_domain(self.form_id),
            "context": {"search_default_kingdee_pending": 1},
        }

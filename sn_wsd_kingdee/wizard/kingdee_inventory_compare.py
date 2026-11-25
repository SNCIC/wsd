# -*- coding: utf-8 -*-
"""Stock alignment and opening stock between the account and Odoo.

One tool, two jobs of the migration plan:

* **Opening stock** (29 November): the account is the source of truth of the stock
  on 28 November, so Odoo is set to it before the first document is pushed.
* **Alignment** (5, 12 and 18 December): the same comparison run every week, with
  the differences cleared one by one and a signed baseline at the end.

The comparison is made on the only key the two systems share: **material, warehouse
and batch**, with the stock status kept as a fourth key so a frozen batch is not
counted as available. The account side is read from ``STK_Inventory`` (the current
stock), the Odoo side from ``stock.quant`` on the internal locations.

Two facts to keep in mind when running it:

* ``STK_Inventory`` is a **current** picture: the opening stock must be read on the
  day of the closing, not rebuilt later.
* Applying a difference books an **inventory adjustment** in Odoo (a move of its
  own, flagged ``is_inventory``), never a silent update of a quant: the trace of who
  changed what stays in the stock ledger.
"""

import base64
import io
import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

INVENTORY_FORM_ID = "STK_Inventory"

# Keys of a stock row, in the query notation of BillQuery.
INVENTORY_FIELDS = (
    "FStockId.FNumber",
    "FMaterialId.FNumber",
    "FLot.FNumber",
    "FQty",
    "FBaseQty",
    "FStockStatusId.FNumber",
)


class SnWsdKingdeeInventoryCompare(models.TransientModel):
    """Compare the stock of the account with the stock of Odoo."""

    _name = "sn.wsd.kingdee.inventory.compare"
    _description = "Kingdee Stock Alignment"
    _order = "id desc"

    date = fields.Date(
        string="Stock Date", required=True, default=fields.Date.context_today,
        help="Date the comparison refers to. The account only holds its current "
             "stock: an opening stock has to be read on the day of the closing.",
    )
    warehouse_numbers = fields.Char(
        string="Warehouses",
        help="Comma separated Kingdee warehouse numbers to compare. Empty compares "
             "every warehouse of the account.",
    )
    only_differences = fields.Boolean(string="Differences Only", default=True)
    loaded_at = fields.Datetime(string="Loaded", readonly=True)
    line_ids = fields.One2many(
        "sn.wsd.kingdee.inventory.compare.line", "compare_id", string="Lines",
        readonly=True,
    )
    line_count = fields.Integer(compute="_compute_counts")
    difference_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids")
    def _compute_counts(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)
            wizard.difference_count = len(
                wizard.line_ids.filtered(lambda line: line.state != "match"))

    # ------------------------------------------------------------------
    # Reading both sides
    # ------------------------------------------------------------------
    def _kingdee_rows(self):
        """Current stock of the account, as ``{key: quantity}``."""
        self.ensure_one()
        client = self.env["sn.wsd.kingdee.client"]
        field_keys = list(INVENTORY_FIELDS)
        filter_string = ""
        numbers = [number.strip() for number in (self.warehouse_numbers or "").split(",")
                   if number.strip()]
        if numbers:
            quoted = ", ".join("'%s'" % number for number in numbers)
            filter_string = "FStockId.FNumber in (%s)" % quoted
        rows = {}
        for values in client.iter_bill_query(
                INVENTORY_FORM_ID, field_keys, filter_string=filter_string):
            key = (
                (values.get("FMaterialId.FNumber") or "").strip(),
                (values.get("FStockId.FNumber") or "").strip(),
                (values.get("FLot.FNumber") or "").strip(),
                (values.get("FStockStatusId.FNumber") or "").strip(),
            )
            if not key[0]:
                continue
            try:
                quantity = float(values.get("FQty") or 0.0)
            except (TypeError, ValueError):
                quantity = 0.0
            rows[key] = rows.get(key, 0.0) + quantity
        return rows

    def _odoo_rows(self):
        """Stock of Odoo on the same key, read on the internal locations."""
        self.ensure_one()
        Quant = self.env["stock.quant"].with_context(active_test=False)
        quants = Quant.search([("location_id.usage", "=", "internal")])
        account = self.env["sn.wsd.kingdee.account"]._for_company(self.env.company)
        bill_mixin = self.env["sn.wsd.kingdee.bill.mixin"]
        rows = {}
        cache = {}
        for quant in quants:
            quantity = quant.quantity
            if not quantity:
                continue
            product = quant.product_id
            material = (product.kingdee_number or product.default_code or "").strip()
            if not material:
                continue
            location = quant.location_id
            warehouse = cache.get(location.id)
            if warehouse is None:
                warehouse = cache[location.id] = bill_mixin._kd_stock_number(location)
            lot = quant.lot_id
            status = account._stock_status_for(lot) if account else "KCZT01_SYS"
            key = (material, warehouse, lot.name if lot else "", status)
            rows[key] = rows.get(key, 0.0) + quantity
        return rows

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_load(self):
        """Read both sides and store the comparison lines."""
        self.ensure_one()
        kingdee_rows = self._kingdee_rows()
        odoo_rows = self._odoo_rows()
        self.line_ids.unlink()
        Line = self.env["sn.wsd.kingdee.inventory.compare.line"]
        product_model = self.env["product.product"]
        location_model = self.env["stock.location"]
        keys = set(kingdee_rows) | set(odoo_rows)
        values_list = []
        for key in sorted(keys):
            material, warehouse, lot_name, status = key
            kingdee_qty = kingdee_rows.get(key, 0.0)
            odoo_qty = odoo_rows.get(key, 0.0)
            if abs(kingdee_qty - odoo_qty) < 1e-6:
                state = "match"
            elif not odoo_qty:
                state = "kingdee_only"
            elif not kingdee_qty:
                state = "odoo_only"
            else:
                state = "differs"
            if self.only_differences and state == "match":
                continue
            product = product_model.search(
                ["|", ("kingdee_number", "=", material), ("default_code", "=", material)],
                limit=1)
            location = location_model.search([
                ("kingdee_number", "=", warehouse), ("usage", "=", "internal")], limit=1)
            lot = self.env["stock.lot"]
            if product and lot_name:
                lot = lot.search([("name", "=", lot_name), ("product_id", "=", product.id)],
                                 limit=1)
            values_list.append({
                "compare_id": self.id,
                "material_number": material,
                "warehouse_number": warehouse,
                "lot_number": lot_name,
                "status_number": status,
                "kingdee_qty": kingdee_qty,
                "odoo_qty": odoo_qty,
                "difference": kingdee_qty - odoo_qty,
                "state": state,
                "product_id": product.id,
                "location_id": location.id,
                "lot_id": lot.id,
            })
        if values_list:
            Line.create(values_list)
        self.write({"loaded_at": fields.Datetime.now()})
        return self._reopen()

    def _reopen(self):
        """Keep the same wizard open after a button."""
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_apply(self):
        """Set the Odoo stock to the stock of the account, line by line.

        This is the opening stock of the migration and the weekly alignment: the
        account is the reference, so the quantity of Odoo is brought to it. Each line
        books an inventory adjustment of its own, and a line whose material or
        location is unknown in Odoo is reported, never guessed.
        """
        self.ensure_one()
        applied, refused = 0, []
        for line in self.line_ids.filtered(lambda row: row.state != "match"):
            if not line.product_id or not line.location_id:
                refused.append(line.material_number or _("(no material)"))
                continue
            try:
                with self.env.cr.savepoint():
                    line._apply_difference()
                applied += 1
            except Exception as err:  # noqa: BLE001 - reported line by line
                _logger.warning("Stock alignment failed for %s: %s",
                                line.material_number, err)
                refused.append("%s (%s)" % (line.material_number, err))
        message = _("%(count)s line(s) aligned on the stock of Kingdee.") % {"count": applied}
        if refused:
            message += "\n" + _("Not applied: %s") % ", ".join(refused[:10])
        self.line_ids.filtered(lambda row: row.state != "match").write({"applied": True})
        return self.env["sn.wsd.kingdee.sync.mixin"]._kingdee_notify(
            _("Kingdee"), message,
            kind="danger" if refused else "success", sticky=bool(refused))

    def action_export(self):
        """Download the comparison as a workbook, for the signature of the baseline."""
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:  # pragma: no cover - Odoo ships the dependency
            raise UserError(_("The xlsxwriter library is not installed."))
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        sheet = workbook.add_worksheet("Kingdee stock")
        headers = [_("Material"), _("Warehouse"), _("Batch"), _("Stock Status"),
                   _("Kingdee Quantity"), _("Odoo Quantity"), _("Difference"), _("State")]
        bold = workbook.add_format({"bold": True})
        for column, header in enumerate(headers):
            sheet.write(0, column, header, bold)
        for row_index, line in enumerate(self.line_ids, start=1):
            sheet.write(row_index, 0, line.material_number)
            sheet.write(row_index, 1, line.warehouse_number)
            sheet.write(row_index, 2, line.lot_number)
            sheet.write(row_index, 3, line.status_number)
            sheet.write_number(row_index, 4, line.kingdee_qty)
            sheet.write_number(row_index, 5, line.odoo_qty)
            sheet.write_number(row_index, 6, line.difference)
            sheet.write(row_index, 7, line.state)
        workbook.close()
        attachment = self.env["ir.attachment"].create({
            "name": "kingdee-stock-%s.xlsx" % (str(self.date) if self.date else "today"),
            "datas": base64.b64encode(buffer.getvalue()),
            "res_model": self._name,
            "res_id": self.id,
        })
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }


class SnWsdKingdeeInventoryCompareLine(models.TransientModel):
    """One material, warehouse and batch of the comparison."""

    _name = "sn.wsd.kingdee.inventory.compare.line"
    _description = "Kingdee Stock Comparison Line"
    _order = "state, material_number, warehouse_number"

    compare_id = fields.Many2one("sn.wsd.kingdee.inventory.compare", required=True,
                                 ondelete="cascade")
    material_number = fields.Char(string="Material")
    warehouse_number = fields.Char(string="Warehouse")
    lot_number = fields.Char(string="Batch")
    status_number = fields.Char(string="Stock Status")
    kingdee_qty = fields.Float(string="Kingdee Quantity", digits=(16, 4))
    odoo_qty = fields.Float(string="Odoo Quantity", digits=(16, 4))
    difference = fields.Float(string="Difference", digits=(16, 4))
    state = fields.Selection([
        ("match", "Match"),
        ("kingdee_only", "Only in Kingdee"),
        ("odoo_only", "Only in Odoo"),
        ("differs", "Quantity Differs"),
    ], string="State")
    product_id = fields.Many2one("product.product", string="Product")
    location_id = fields.Many2one("stock.location", string="Location")
    lot_id = fields.Many2one("stock.lot", string="Lot")
    applied = fields.Boolean(string="Aligned", readonly=True)

    def _apply_difference(self):
        """Bring the quant of this line to the quantity of the account."""
        self.ensure_one()
        if not self.product_id or not self.location_id:
            raise UserError(_("The material or the warehouse is unknown in Odoo."))
        quant = self.env["stock.quant"].search([
            ("product_id", "=", self.product_id.id),
            ("location_id", "=", self.location_id.id),
            ("lot_id", "=", self.lot_id.id or False),
        ], limit=1)
        if not quant:
            quant = self.env["stock.quant"].create({
                "product_id": self.product_id.id,
                "location_id": self.location_id.id,
                "lot_id": self.lot_id.id or False,
            })
        quant.inventory_quantity = self.kingdee_qty
        quant.action_apply_inventory()
        return True

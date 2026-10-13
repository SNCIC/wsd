# -*- coding: utf-8 -*-
"""The synchronization console: one row per target, grouped by business module.

The console is the single entry point of the integration. A target is declared by
one data record (``data/kingdee_sync_targets.xml``) naming an Odoo model and a
direction; the button of the row dispatches to the method that model exposes for
that direction (``SYNC_METHODS`` below). Adding an entity - a sale order, a stock
receipt - is therefore one data record, one method and one line here, never a new
view, menu or wizard.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# (direction, Odoo model) -> method of that model. Every method takes
# (filter_string, limit, dry_run) and returns an action (a notification).
SYNC_METHODS = {
    ("in", "product.template"): "_kingdee_import_materials",
    ("out", "product.template"): "_kingdee_push_materials",
    ("in", "res.partner"): "_kingdee_import_partners",
    ("out", "res.partner"): "_kingdee_push_partners",
}

SYNC_DIRECTION_SELECTION = [
    ("in", "Kingdee to Odoo"),
    ("out", "Odoo to Kingdee"),
]

# Business modules, the way the console groups the targets. They follow the Kingdee
# subsystems so the console keeps matching the ERP once orders and stock land.
SYNC_MODULE_SELECTION = [
    ("base", "Master Data"),
    ("sale", "Sales"),
    ("purchase", "Purchase"),
    ("stock", "Inventory"),
    ("mrp", "Manufacturing"),
]


class SnWsdKingdeeSyncTarget(models.Model):
    """One entity to synchronize, in one direction."""

    _name = "sn.wsd.kingdee.sync.target"
    _description = "Kingdee Synchronization Target"
    _order = "module, sequence, id"

    name = fields.Char(string="Entity", required=True, translate=True)
    module = fields.Selection(
        SYNC_MODULE_SELECTION, string="Module", required=True, index=True,
        help="Business module the console groups this target under.",
    )
    direction = fields.Selection(
        SYNC_DIRECTION_SELECTION, string="Direction", required=True, index=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "ir.model", string="Odoo Model", required=True, ondelete="cascade",
        help="Model the synchronization reads from or writes to.",
    )
    model_name = fields.Char(related="model_id.model", string="Model Name")
    form_id = fields.Char(
        string="Kingdee Object",
        help="Kingdee form id of the business object, e.g. BD_MATERIAL.",
    )
    sync_filter = fields.Char(
        string="Kingdee Filter",
        help="Optional Kingdee FilterString used by a Kingdee to Odoo run, e.g. "
             "\"FDocumentStatus = 'C'\" to read the audited records only.",
    )
    sync_limit = fields.Integer(
        string="Batch Limit", default=0,
        help="Highest number of records one run handles. 0 uses the limit of the "
             "synchronization itself.",
    )
    linked_count = fields.Integer(
        string="Linked Records", compute="_compute_counts",
        help="Records already carrying a Kingdee number.",
    )
    pending_count = fields.Integer(
        string="Pending", compute="_compute_counts",
        help="Records that still have to be sent to Kingdee (never saved, or whose "
             "last attempt failed).",
    )
    last_sync_at = fields.Datetime(string="Last Call", compute="_compute_last_sync_at")

    @api.depends("model_id", "direction")
    def _compute_counts(self):
        for target in self:
            target.linked_count = 0
            target.pending_count = 0
            model_name = target.model_id.model
            if not model_name or model_name not in self.env:
                continue
            model = self.env[model_name]
            if "kingdee_number" not in model._fields:
                continue
            target.linked_count = model.search_count([("kingdee_number", "!=", False)])
            if "kingdee_sync_state" in model._fields:
                target.pending_count = model.search_count(
                    [("kingdee_sync_state", "in", ("not_synced", "error"))])

    @api.depends("form_id", "direction")
    def _compute_last_sync_at(self):
        log = self.env["sn.wsd.kingdee.sync.log"]
        for target in self:
            target.last_sync_at = False
            if not target.form_id:
                continue
            last = log.search([
                ("form_id", "=", target.form_id),
                ("direction", "=", target.direction),
            ], order="id desc", limit=1)
            target.last_sync_at = last.create_date

    def action_sync(self):
        """Run this synchronization now, with the options stored on the row."""
        self.ensure_one()
        return self._kingdee_run_target()

    def action_preview(self):
        """Read Kingdee and report what a run would do, writing nothing."""
        self.ensure_one()
        if self.direction != "in":
            raise UserError(_(
                "Only a Kingdee to Odoo target can be previewed: the other direction "
                "writes to Kingdee."
            ))
        return self._kingdee_run_target(dry_run=True)

    def _kingdee_run_target(self, dry_run=False):
        """Dispatch to the method the target's model exposes for this direction."""
        self.ensure_one()
        method_name = SYNC_METHODS.get((self.direction, self.model_id.model))
        if not method_name:
            raise UserError(_(
                "%(entity)s is declared in the synchronization console but its "
                "%(direction)s run is not implemented yet."
            ) % {
                "entity": self.name,
                "direction": dict(SYNC_DIRECTION_SELECTION)[self.direction],
            })
        handler = getattr(self.env[self.model_id.model], method_name)
        return handler(
            filter_string=self.sync_filter or "",
            limit=self.sync_limit or 0,
            dry_run=dry_run,
        )

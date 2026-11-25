# -*- coding: utf-8 -*-
"""Daily push report of the migration.

The plan of the go-live asks for one figure every evening: the **push success rate
of each department**, and the list of the documents that failed. Both are read from
``sn.wsd.kingdee.sync.log``, which is the only record of what was really sent: a
document says its own state, but the log says how many calls it took and which one
failed.

One row per day, one line per document kind, grouped by the module of the mapping
(``purchase``, ``sale``, ``stock``, ``mrp``) - the departments of the plan. A run is
idempotent: regenerating a day replaces its lines, so the report can be rebuilt once
the failures of the evening are solved.
"""

import logging
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Module of a document kind: the grouping the daily report and the plan use.
KIND_MODULE = {
    "purchase_order": "purchase",
    "receipt": "purchase",
    "vendor_return": "purchase",
    "sale_order": "sale",
    "delivery": "sale",
    "sale_return": "sale",
    "other_in": "stock",
    "other_out": "stock",
    "internal_transfer": "stock",
    "production_order": "mrp",
    "mes_issue": "mrp",
    "mes_over_pick": "mrp",
    "mes_return": "mrp",
    "mes_fg_receipt": "mrp",
}

MODULE_SELECTION = [
    ("purchase", "Purchase"),
    ("sale", "Sales"),
    ("stock", "Inventory"),
    ("mrp", "Manufacturing"),
    ("base", "Master Data"),
]


class SnWsdKingdeePushDaily(models.Model):
    """Push statistics of one day."""

    _name = "sn.wsd.kingdee.push.daily"
    _description = "Kingdee Push Daily Report"
    _order = "date desc, id desc"

    date = fields.Date(string="Date", required=True, index=True,
                       default=fields.Date.context_today)
    line_ids = fields.One2many("sn.wsd.kingdee.push.daily.line", "daily_id",
                               string="Lines", readonly=True)
    note = fields.Text(string="Summary", readonly=True)
    pushed = fields.Integer(compute="_compute_totals")
    failed = fields.Integer(compute="_compute_totals")
    success_rate = fields.Float(string="Success Rate (%)", compute="_compute_totals")

    _date_uniq = models.Constraint("UNIQUE(date)", "One report per day.")

    @api.depends("line_ids.pushed", "line_ids.failed")
    def _compute_totals(self):
        for daily in self:
            pushed = sum(daily.line_ids.mapped("pushed"))
            failed = sum(daily.line_ids.mapped("failed"))
            total = pushed + failed
            daily.pushed = pushed
            daily.failed = failed
            daily.success_rate = (100.0 * pushed / total) if total else 0.0

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    @api.model
    def _cron_generate_daily(self):
        """Build yesterday's report: the plan checks it at 17:00, the run is nightly."""
        self._generate(fields.Date.context_today(self) - timedelta(days=1))
        return True

    def action_generate_today(self):
        """Build (or rebuild) the report of today, from the button of the list."""
        today = fields.Date.context_today(self)
        daily = self._generate(today)
        return {
            "type": "ir.actions.act_window",
            "name": _("Push Report"),
            "res_model": self._name,
            "res_id": daily.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def _generate(self, date=None):
        """(Re)build the report of ``date`` from the sync log."""
        date = date or fields.Date.context_today(self)
        start = datetime.combine(date, time.min)
        end = datetime.combine(date, time.max)
        log = self.env["sn.wsd.kingdee.sync.log"]
        maps = self.env["sn.wsd.kingdee.bill.map"].search([("active", "=", True)])
        form_kind = {}
        for row in maps:
            form_kind.setdefault(row.form_id, row.kind)
        stats = {}
        if form_kind:
            groups = log._read_group(
                [("form_id", "in", list(form_kind)),
                 ("create_date", ">=", start), ("create_date", "<=", end),
                 ("api_name", "in", ("Save", "SaveFail"))],
                ["form_id", "state"], ["__count"],
            )
            for form_id, state, count in groups:
                key = (form_id, state)
                stats[key] = stats.get(key, 0) + count
        daily = self.search([("date", "=", date)], limit=1)
        if not daily:
            daily = self.create({"date": date})
        daily.line_ids.unlink()
        summary_lines = []
        for form_id in sorted(form_kind):
            pushed = stats.get((form_id, "success"), 0)
            failed = stats.get((form_id, "error"), 0)
            if not pushed and not failed:
                continue
            kind = form_kind[form_id]
            self.env["sn.wsd.kingdee.push.daily.line"].create({
                "daily_id": daily.id,
                "module": KIND_MODULE.get(kind, "base"),
                "kind": kind,
                "form_id": form_id,
                "pushed": pushed,
                "failed": failed,
            })
            summary_lines.append("%s: %s / %s" % (form_id, pushed, pushed + failed))
        daily.note = _("Calls of the day per document: %s") % (
            "; ".join(summary_lines) or _("nothing pushed"))
        return daily


class SnWsdKingdeePushDailyLine(models.Model):
    """One document kind of a daily report."""

    _name = "sn.wsd.kingdee.push.daily.line"
    _description = "Kingdee Push Daily Line"
    _order = "module, kind, id"

    daily_id = fields.Many2one("sn.wsd.kingdee.push.daily", required=True,
                               ondelete="cascade", index=True)
    date = fields.Date(related="daily_id.date", store=True, index=True)
    module = fields.Selection(MODULE_SELECTION, string="Module", required=True)
    kind = fields.Char(string="Kind")
    form_id = fields.Char(string="Kingdee Object")
    pushed = fields.Integer(string="Pushed")
    failed = fields.Integer(string="Failed")
    success_rate = fields.Float(string="Success Rate (%)", compute="_compute_rate")

    @api.depends("pushed", "failed")
    def _compute_rate(self):
        for line in self:
            total = line.pushed + line.failed
            line.success_rate = (100.0 * line.pushed / total) if total else 0.0

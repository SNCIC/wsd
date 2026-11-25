# -*- coding: utf-8 -*-
"""Receivable conditions of the account on ``account.payment.term`` (BD_RecCondition).

The account keeps its receivable conditions as **instalment schemes**: each line
carries a rate, a prepaid flag and a due-date algorithm (end of month, fixed day,
days after a reference date). An Odoo term is a percentage / days line. Measured
on the account (2026-11-25), the eight conditions are:

===========  ==================================  ==============================
Kingdee      Meaning                             Odoo term
===========  ==================================  ==============================
``001``      票后1个月 (1 month after invoice)   100% / 30 days
``002``      票后2个月                           100% / 60 days
``003``      票后3个月                           100% / 90 days
``004``      100%预收 (paid before delivery)     100% / 0 days
``005``      发货后45天收款                      100% / 45 days
``006``      预收30%，发货后45天收款             30% / 0 + 70% / 45
``007``      预收50%，发货前收齐                 50% / 0 + 50% / 0
``SKTJ04_SYS`` 多到期日（按金额）                 not expressible (see below)
===========  ==================================  ==============================

Two things follow from the table:

* seven conditions **are** expressible, and this account already carries a term
  of the same name for each of them. The import therefore **claims a term by its
  name** and stores the Kingdee number on it, instead of creating a second term:
  the Odoo terms an accountant maintains stay the ones in use.
* the amount-based condition (``SKTJ04_SYS``: 20 000 / 50 000 / the rest) cannot
  be expressed: Odoo requires the percent lines of a term to add up to 100%, so
  an amount scheme has no equivalent. It is reported and skipped rather than
  replaced by a term that would age the receivable wrongly.

Two boundaries of the conversion, both kept explicit:

* Odoo counts days, the account counts months: a month is taken as 30 days.
* Odoo counts from the invoice date, the account can count from the order, the
  delivery or the invoice date (``FAccountTimeJudge``): the condition is created
  as "days after the invoice date", which is the date an Odoo receivable starts
  from. A condition that ages from the delivery date is therefore an
  approximation, and its Kingdee name says so ("发货后45天收款").
"""

import logging

from odoo import Command, _, api, fields, models

from .kingdee_client import REC_CONDITION_FORM_ID

_logger = logging.getLogger(__name__)

# Fields read from Kingdee (BD_RecCondition). The header holds the due-date
# reference (FAccountTimeJudge: 2 order date, 1 receivable date, 3 delivery date,
# 4 invoice date) and the amount/percent switch; the entry (FPayRecCondtionEntry,
# read through its bare FieldKeys) holds one line per instalment.
KINGDEE_TERM_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
    "FAccountTimeJudge",
    "FISINSTALLMENT",
    "FRate",
    "FISPREPAID",
    "FODConfirmMethod",
    "FODMonth",
    "FODDay",
    "FISMONTHEND",
    "FODDayToEndMonth",
    "FAmount",
)

# Days one month of the account stands for in an Odoo term. Odoo counts days only,
# the account counts months, so a month is converted, never dropped.
DAYS_PER_MONTH = 30


class AccountPaymentTerm(models.Model):
    """A payment term of Odoo, kept in step with the conditions of the account."""

    _name = "account.payment.term"
    _inherit = ["account.payment.term", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = REC_CONDITION_FORM_ID
    _kingdee_query_fields = KINGDEE_TERM_FIELDS
    # No Odoo field mirrors the number of a condition: it lives on kingdee_number
    # and an existing term is claimed through its name (see _kingdee_import_term).
    _kingdee_number_field = None

    kingdee_number = fields.Char(
        string="Kingdee Number",
        copy=False,
        index=True,
        help="Number (FNumber) of the Kingdee receivable (BD_RecCondition) or "
             "payment (BD_PaymentCondition) condition this term stands for. Filled "
             "in by the Kingdee import, which claims a term by its number first and "
             "by its name second.",
    )

    _kingdee_number_unique = models.Constraint(
        "UNIQUE(kingdee_number)",
        "The Kingdee condition number must be unique.",
    )

    # ------------------------------------------------------------------
    # Conversion: one Kingdee instalment -> one Odoo term line
    # ------------------------------------------------------------------
    def _kingdee_term_days(self, data):
        """Days of credit of one Kingdee instalment, from the date it counts from.

        A prepaid instalment is due before delivery: 0 days. Otherwise the account
        carries days (``FODDay``) or months (``FODMonth``); a month becomes
        ``DAYS_PER_MONTH`` days because an Odoo line counts days only.
        """
        if (data.get("FISPREPAID") or "").strip() in ("True", "true", "1"):
            return 0
        days = int(float(data.get("FODDay") or 0.0))
        if days:
            return days
        months = int(float(data.get("FODMonth") or 0.0))
        return months * DAYS_PER_MONTH

    def _kingdee_term_line_values(self, data):
        """Odoo line of one Kingdee instalment."""
        return {
            "value": "percent",
            "value_amount": float(data.get("FRate") or 0.0),
            "nb_days": self._kingdee_term_days(data),
            "delay_type": "days_after",
        }

    def _kingdee_term_lines(self, lines):
        """Lines of a term, completed so the percentages add up to 100.

        The account fills ``FRate`` only on an instalment scheme: a condition of a
        single line (``100%预收``, ``票后1个月``) carries no rate at all and means
        the whole invoice. The remainder of an incomplete scheme goes on the last
        line, which is where the account puts it too.
        """
        values = [self._kingdee_term_line_values(line) for line in lines]
        if not values:
            return [{"value": "percent", "value_amount": 100.0, "nb_days": 0,
                     "delay_type": "days_after"}]
        total = sum(line["value_amount"] for line in values)
        if not total:
            values[0]["value_amount"] = 100.0
        elif total < 100.0:
            values[-1]["value_amount"] += 100.0 - total
        return values

    def _kingdee_is_amount_based(self, lines):
        """Whether the condition splits the invoice by amount, not by percentage."""
        return any(float(line.get("FAmount") or 0.0) > 0.0 for line in lines)

    # ------------------------------------------------------------------
    # Inbound: one condition (all of its instalments)
    # ------------------------------------------------------------------
    def _kingdee_link_number(self, number):
        """Store the Kingdee number on a term claimed by name, tolerating a clash.

        Two Odoo terms may carry the same name while the account conditions have
        unique numbers: a name that is already linked to another number is left
        alone instead of failing the run.
        """
        try:
            with self.env.cr.savepoint():
                self.write({"kingdee_number": number})
        except Exception as err:  # noqa: BLE001 - reported, the term is still used
            _logger.warning(
                "Kingdee condition %s cannot be stored on term %s: %s",
                number, self.display_name, err,
            )

    def _kingdee_import_term(self, number, lines, dry_run=False):
        """Create or claim the Odoo term of one condition.

        Returns ``"created"``, ``"updated"`` or ``"skipped"``, the counters an
        import reports. A term already linked to the number, or carrying the name
        of the condition, is claimed: its lines are **not** rewritten, because an
        accountant maintains them (the account only says what the term stands for).
        """
        name = (lines[0].get("FName") or "").strip() or number
        term = self.search([("kingdee_number", "=", number)], limit=1)
        if not term and name:
            # A term of the same name that is not linked yet is the one the
            # condition stands for: a name already linked to another number is
            # left alone, otherwise a second condition would steal the term.
            term = self.search(
                [("name", "=", name), ("kingdee_number", "=", False)], limit=1)
        if not term and name:
            term = self.search([("name", "=", name)], limit=1)
        if term:
            if (term.kingdee_number or "").strip() != number:
                term._kingdee_link_number(number)
            return "updated"
        if self._kingdee_is_amount_based(lines):
            _logger.info(
                "Kingdee condition %s (%s) splits the invoice by amount: an Odoo "
                "term cannot express it, it is left to the accountant.",
                number, name,
            )
            return "skipped"
        if dry_run:
            return "created"
        self.create({
            "name": name,
            "kingdee_number": number,
            "line_ids": [Command.create(line) for line in self._kingdee_term_lines(lines)],
        })
        return "created"

    @api.model
    def _kingdee_import_terms(self, filter_string="", limit=0, dry_run=False, **_ignored):
        """Read the receivable conditions and create or claim the matching terms.

        ``BillQuery`` answers one row per **instalment**, so the rows are grouped by
        condition before anything is written: ``006`` is two rows and one term.
        """
        client = self.env["sn.wsd.kingdee.client"]
        rows = client.iter_bill_query(
            REC_CONDITION_FORM_ID,
            ",".join(KINGDEE_TERM_FIELDS),
            filter_string=(filter_string or "").strip(),
            order_string="FNumber",
        )
        groups = {}
        for row in rows:
            data = {
                key: self._kingdee_text(self._kingdee_row_value(row, key))
                for key in KINGDEE_TERM_FIELDS
            }
            number = (data.get("FNumber") or "").strip()
            if number:
                groups.setdefault(number, []).append(data)

        summary = {"read": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0,
                   "errors": []}
        for number, lines in groups.items():
            if limit and summary["read"] >= limit:
                break
            summary["read"] += 1
            try:
                with self.env.cr.savepoint():
                    outcome = self._kingdee_import_term(number, lines, dry_run=dry_run)
            except Exception as err:  # noqa: BLE001 - reported, the run must go on
                summary["failed"] += 1
                _logger.warning(
                    "Kingdee import failed for condition %s: %s", number, err,
                )
                if len(summary["errors"]) < 5:
                    summary["errors"].append(_("%(number)s: %(message)s") % {
                        "number": number, "message": err,
                    })
                continue
            summary[outcome] += 1
        return self._kingdee_import_notification(
            summary, dry_run=dry_run, entity=_("Receivable Conditions"))

# -*- coding: utf-8 -*-
"""Kingdee unit of measure synchronization for ``uom.uom`` (BD_UNIT).

Inbound only: the account owns its unit list (28 fields, 3 mandatory: ``FName``,
``FUnitGroupId`` 所属组别 and ``FRoundType`` 舍入类型), and a unit created in Odoo would
have to be audited in Kingdee before a material could reference it.

**Why there is no unit group in Odoo.** Odoo 19 dropped the unit *category*: a unit
either stands alone (``relative_factor`` 1) or is defined against a reference unit
(``relative_uom_id`` + ``relative_factor``, "Contains"). That is exactly what a
Kingdee unit group expresses — the group's base unit is the reference and the others
convert to it — so the import rebuilds the chain instead of inventing categories.

**The chain needs two walks.** The account returns a unit and the unit it converts to
in one answer, but not always in an order where the reference comes first (measured:
``019`` V is the base of group ``UG016`` and ``020`` mV converts to it, 1 mV = 1/1000 V).
A unit is therefore created standing alone (Odoo's default and a valid state) and a
second walk links the conversions, once every unit exists.

**Adoption.** A unit Odoo already has is adopted when its name is the unit's name
(``FName``): the name identifies a unit in Odoo, the number (``001``) in Kingdee — the
same rule the currency import follows with the ISO code. This account happens to name
its unit ``m`` while Odoo already has an ``m``, and both mean the metre.
"""

import logging

from odoo import _, api, models

from .kingdee_client import UOM_FORM_ID

_logger = logging.getLogger(__name__)

# Fields read from Kingdee (fields_master.csv, BD_UNIT). ``FName``, ``FUnitGroupId``
# and ``FRoundType`` are the three the account marks mandatory; the conversion lives
# in the ``SubHeadEntity`` of the form and is answered as plain fields of the row.
#
# ``FPrecision`` (小数精度) is **not** read: Odoo 19 computes a unit's rounding from
# ``decimal.precision`` ("Product Unit"), so there is nothing to write it to, and
# ``FRoundType`` is a rounding *mode* (1=四舍五入 …), not a rounding increment.
# ``FIsBaseUnit`` is not read either: a unit that converts to itself is the base of
# its group, which the two unit fields below already say.
KINGDEE_UNIT_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
    "FCurrentUnitId.FNumber",
    "FDestUnitId.FNumber",
    "FConvertNumerator",
    "FConvertDenominator",
)


class UomUom(models.Model):
    """A unit of the account, kept in step with BD_UNIT."""

    _inherit = ["uom.uom", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = UOM_FORM_ID
    _kingdee_query_fields = KINGDEE_UNIT_FIELDS
    # Nothing in Odoo mirrors the Kingdee number of a unit: it is stored on
    # kingdee_number and an existing unit is adopted through its name.
    _kingdee_number_field = None

    def _kingdee_adopt_domain(self, data, number):
        """Adopt the unit Odoo already has, by its name."""
        name = (data or {}).get("FName") or ""
        if not name:
            return []
        return [("name", "=", name)]

    # ------------------------------------------------------------------
    # The conversion chain
    # ------------------------------------------------------------------
    def _kingdee_conversion_ratio(self, data):
        """Ratio of the row against ``FDestUnitId``, or None when it stands alone.

        The account expresses ``1 <current unit> = numerator / denominator
        <destination unit>`` (measured: 1 mV = 1/1000 V), which is Odoo's
        ``relative_factor`` of the unit against its reference. A unit that converts
        to itself is the base unit of its group: it stands alone.
        """
        current = self._kingdee_text(self._kingdee_row_value(data, "FCurrentUnitId.FNumber"))
        dest = self._kingdee_text(self._kingdee_row_value(data, "FDestUnitId.FNumber"))
        if not dest or dest == current:
            return None
        try:
            numerator = float(self._kingdee_text(
                self._kingdee_row_value(data, "FConvertNumerator")) or 0)
            denominator = float(self._kingdee_text(
                self._kingdee_row_value(data, "FConvertDenominator")) or 0)
        except (TypeError, ValueError):
            return None
        if not numerator or not denominator:
            return None
        return numerator / denominator

    @api.model
    def _kingdee_link_units(self, rows, summary):
        """Link every unit to the one it converts to, once all of them exist.

        Runs after :meth:`_kingdee_import_row_list`, so a unit whose reference appears
        later in the answer is linked too.

        **The import only ever adds a conversion, it never takes one apart.** The
        account states what converts to what; it does not state that a unit is
        unrelated to the ones Odoo already groups it with. Odoo ships 82 units of its
        own — this account's ``只``, ``V``, ``mV`` and ``A`` are among them, ``mV``
        already converting to ``V`` — and clearing the reference of "a unit that
        converts to itself" would silently change how quantities convert between
        units Odoo relates today. An adopted unit therefore keeps its own family, a
        created one keeps Odoo's default (it stands alone, factor 1).

        Returns how many units were linked and reports a write it cannot do through
        ``summary``, like any other row.
        """
        linked = 0
        for row in rows:
            ratio = self._kingdee_conversion_ratio(row)
            if ratio is None:
                # The account says this unit converts to itself: nothing to add.
                continue
            number = self._kingdee_text(self._kingdee_row_value(row, "FNumber"))
            unit = self.search([("kingdee_number", "=", number)], limit=1)
            if not unit:
                continue
            dest = self._kingdee_text(self._kingdee_row_value(row, "FDestUnitId.FNumber"))
            reference = self.search([
                ("kingdee_number", "=", dest), ("id", "!=", unit.id),
            ], limit=1)
            if not reference:
                # The unit it converts to is not in Odoo: nothing is guessed, the unit
                # keeps standing alone and a later run links it.
                continue
            if (unit.relative_uom_id.id == reference.id
                    and abs(unit.relative_factor - ratio) < 1e-9):
                continue
            try:
                with self.env.cr.savepoint():
                    unit.write({"relative_uom_id": reference.id,
                                "relative_factor": ratio})
            except Exception as err:  # noqa: BLE001 - reported, the run must go on
                summary["failed"] += 1
                _logger.warning("Kingdee unit conversion failed for %s: %s", number, err)
                if len(summary["errors"]) < 5:
                    summary["errors"].append(_("%(number)s: %(message)s") % {
                        "number": number or "?", "message": err})
                continue
            linked += 1
        return linked

    # ------------------------------------------------------------------
    # Synchronization entries (called by the sync console)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_import_units(self, filter_string="", limit=0, update_existing=True,
                              create_missing=True, include_disabled=False,
                              dry_run=False):
        """Read the Kingdee units and create or update the matching Odoo ones."""
        client = self.env["sn.wsd.kingdee.client"]
        # Read once, walk twice: the units are a small catalogue and the conversion
        # chain can only be resolved once every unit exists.
        rows = list(client.iter_bill_query(
            self._kingdee_form(UOM_FORM_ID),
            ",".join(self._kingdee_query_fields_for(UOM_FORM_ID)),
            filter_string=(filter_string or "").strip(),
            order_string="FNumber",
        ))
        summary = self._kingdee_import_row_list(
            rows,
            limit=limit,
            update_existing=update_existing,
            create_missing=create_missing,
            include_disabled=include_disabled,
            dry_run=dry_run,
            form_id=UOM_FORM_ID,
        )
        if not dry_run:
            walked = rows[:limit] if limit else rows
            linked = self._kingdee_link_units(walked, summary)
            summary["linked"] = linked
            _logger.info("Kingdee unit conversions linked: %d", linked)
        return self._kingdee_import_notification(
            summary, dry_run=dry_run, entity=_("Units of Measure"))

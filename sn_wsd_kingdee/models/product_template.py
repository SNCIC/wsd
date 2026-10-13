# -*- coding: utf-8 -*-

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .kingdee_client import MATERIAL_FORM_ID

_logger = logging.getLogger(__name__)

# The Kingdee form id and every default (material type, category, unit, ...) come
# from kingdee_client: this module keeps no copy of them.

# Material fields whose value is fixed for this account. They were read from the
# account's own materials (BD_MATERIAL, 2026-10-13) instead of relying on the
# WebAPI defaults, so a pushed material matches the account's standard settings.
# FCurrencyId is a base data reference and uses the {"FNumber": ...} form; the
# others are plain codes (see the BD_MATERIAL metadata of the field index).
MATERIAL_PRESET_FIELDS = {
    "FUnitConvertDir": "1",                  # 换算方式
    "FCurrencyId": {"FNumber": "PRE001"},    # 币别（人民币）
    "FSNManageType": "1",                    # 业务范围
    "FSNGenerateTime": "1",                  # 序列号生成时机
    "FQuotaType": "1",                       # 配额方式
    "FReserveType": "1",                     # 预留类型
    "FPlanningStrategy": "1",                # 计划策略
    "FCheckLeadTimeType": "1",               # 检验提前期单位
    "FPlanOffsetTimeType": "1",              # 计划偏移时间单位
    "FFixLeadTimeType": "1",                 # 固定提前期单位
    "FVarLeadTimeType": "1",                 # 变动提前期单位
    "FOrderPolicy": "0",                     # 订货策略
    "FOrderIntervalTimeType": "3",           # 订货间隔时间单位
    "FIssueType": "1",                       # 发料方式
    "FOverControlMode": "3",                 # 超发控制方式
    "FStandHourUnitId": "3600",              # 工时单位（秒）
    "FBackFlushType": "1",                   # 倒冲类型
    "FFirstQCControlType": "0",              # 首检方式
    "FFeatureItem": "1",                     # 特征件
    "FSuite": "0",                           # 套件
}

# Entity each material field belongs to, taken from the BD_MATERIAL metadata
# (entityKey). The Kingdee WebAPI resolves a field through its entity, so the
# group fields must be nested under this key — sending them flat fails with
# "寻找实体上 <X> 对应的属性描述符失败，实体不存在此属性". Header fields have no
# entity and stay flat. Verified on the account: FErpClsID only saves nested.
MATERIAL_FIELD_ENTITY = {
    "FCategoryID": "SubHeadEntity",
    "FErpClsID": "SubHeadEntity",
    "FBaseUnitId": "SubHeadEntity",
    "FFeatureItem": "SubHeadEntity",
    "FSuite": "SubHeadEntity",
    "FUnitConvertDir": "SubHeadEntity1",
    "FCurrencyId": "SubHeadEntity1",
    "FSNManageType": "SubHeadEntity1",
    "FSNGenerateTime": "SubHeadEntity1",
    "FStoreUnitID": "SubHeadEntity1",
    "FSaleUnitId": "SubHeadEntity2",
    "FSalePriceUnitId": "SubHeadEntity2",
    "FQuotaType": "SubHeadEntity3",
    "FPurchaseUnitId": "SubHeadEntity3",
    "FPurchasePriceUnitId": "SubHeadEntity3",
    "FReserveType": "SubHeadEntity4",
    "FPlanningStrategy": "SubHeadEntity4",
    "FCheckLeadTimeType": "SubHeadEntity4",
    "FPlanOffsetTimeType": "SubHeadEntity4",
    "FFixLeadTimeType": "SubHeadEntity4",
    "FVarLeadTimeType": "SubHeadEntity4",
    "FOrderPolicy": "SubHeadEntity4",
    "FOrderIntervalTimeType": "SubHeadEntity4",
    "FIssueType": "SubHeadEntity5",
    "FOverControlMode": "SubHeadEntity5",
    "FMinIssueUnitId": "SubHeadEntity5",
    "FStandHourUnitId": "SubHeadEntity5",
    "FBackFlushType": "SubHeadEntity5",
    "FFirstQCControlType": "SubHeadEntity6",
}

# ---------------------------------------------------------------------------
# Inbound (Kingdee to Odoo)
# ---------------------------------------------------------------------------
# Material fields read from Kingdee, written in the BillQuery notation. Every key
# comes from the account field index (fields_master.csv, BD_MATERIAL): the header
# entity FBillHead carries FNumber, FName, FDocumentStatus, FForbidStatus and
# FMaterialGroup, SubHeadEntity carries FErpClsID, FCategoryID and FBaseUnitId.
# The reference fields are read through .FNumber, the form this account accepts
# for a reference (the payload sends exactly the same form).
KINGDEE_MATERIAL_FIELDS = (
    "FNumber",
    "FName",
    "FDocumentStatus",
    "FForbidStatus",
    "FErpClsID",
    "FCategoryID.FNumber",
    "FMaterialGroup.FNumber",
    "FBaseUnitId.FNumber",
)

# The same field list as the comma separated FieldKeys of a query call.
KINGDEE_MATERIAL_QUERY = ",".join(KINGDEE_MATERIAL_FIELDS)

# Inbound field mapping (Kingdee field -> Odoo field). It holds exactly the values
# the outbound payload derives from a record, so the inbound direction is the
# inverse of the outbound one: a material imported here can be pushed back
# without any value changing.
KINGDEE_MATERIAL_VALUE_MAP = {
    "FErpClsID": "kingdee_erp_cls_id",
    "FCategoryID.FNumber": "kingdee_category_number",
    "FMaterialGroup.FNumber": "kingdee_material_group",
    "FBaseUnitId.FNumber": "kingdee_unit_number",
}

# FDocumentStatus of a material -> synchronization state. The five values of the
# account are Z (draft), A (created), B (submitted), C (audited) and D
# (re-audited); anything but B and C is a material that simply exists in Kingdee.
KINGDEE_DOCUMENT_STATE = {
    "B": "submitted",
    "C": "audited",
}

# FForbidStatus of a material: A (enabled) or B (disabled).
KINGDEE_FORBIDDEN_STATUS = "B"

# Number of already linked materials refreshed by the scheduled job.
CRON_BATCH_SIZE = 50


class ProductTemplate(models.Model):
    _inherit = ["product.template", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = MATERIAL_FORM_ID

    kingdee_material_group = fields.Char(
        string="Kingdee Material Group", copy=False,
        help="Optional material group number (FMaterialGroup) applied when saving to Kingdee.",
    )
    kingdee_unit_number = fields.Char(
        string="Kingdee Unit", copy=False,
        help="Kingdee unit number (BD_UNIT, e.g. 001 or GE) applied to this material's "
             "base, store, purchase and sale unit fields. The unit configured in "
             "Settings (Kingdee > Material Defaults) is used when empty.",
    )
    kingdee_erp_cls_id = fields.Char(
        string="Kingdee Material Type", copy=False,
        help="Kingdee material type code (FErpClsID), e.g. 2 self-made or 3 subcontract "
             "(values observed in this account). The default from Settings is used when empty.",
    )
    kingdee_category_number = fields.Char(
        string="Kingdee Material Category", copy=False,
        help="Kingdee material category number (FCategoryID), e.g. CHLB05_SYS (产成品) or "
             "CHLB03_SYS (自制半成品). The default from Settings is used when empty.",
    )

    # ------------------------------------------------------------------
    # Kingdee hooks
    # ------------------------------------------------------------------
    def _kingdee_number(self):
        """Material number: the Kingdee number, else the internal reference."""
        self.ensure_one()
        return (self.kingdee_number or self.default_code or "").strip()

    def _kingdee_payload(self, client):
        """Return the material Save payload.

        Header fields are sent flat, the group fields are nested under the entity
        the metadata declares for them; see ``MATERIAL_FIELD_ENTITY``.
        """
        self.ensure_one()
        number = self._kingdee_number()
        # Kingdee requires the unit fields on a material: they are what links it
        # to BD_UNIT. The same unit is applied to the base, store, purchase and
        # sale fields unless the product overrides it.
        unit = (self.kingdee_unit_number or "").strip() or client.get_unit_number()
        erp_cls = ((self.kingdee_erp_cls_id or "").strip()
                   or client.get_setting("erp_cls_id"))
        category = ((self.kingdee_category_number or "").strip()
                    or client.get_setting("category_number"))
        group = ((self.kingdee_material_group or "").strip()
                 or client.get_setting("material_group"))
        values = dict(MATERIAL_PRESET_FIELDS)
        values.update({
            "FCreateOrgId": {"FNumber": client.get_default_org("create")},
            "FUseOrgId": {"FNumber": client.get_default_org("use")},
            "FNumber": number,
            "FName": (self.name or "").strip() or number,
            "FErpClsID": erp_cls,
            "FCategoryID": {"FNumber": category},
            "FBaseUnitId": {"FNumber": unit},
            "FStoreUnitID": {"FNumber": unit},
            "FPurchaseUnitId": {"FNumber": unit},
            "FPurchasePriceUnitId": {"FNumber": unit},
            "FSaleUnitId": {"FNumber": unit},
            "FSalePriceUnitId": {"FNumber": unit},
            "FMinIssueUnitId": {"FNumber": unit},
        })
        if group:
            # The platform metadata marks FMaterialGroup as mandatory, the account
            # metadata does not (fields_master.csv: 必录 empty for this field, which
            # is why the master index counts 35 mandatory fields here and the
            # platform tree counts 36). Sending it is safe and keeps the material in
            # the configured group; when nothing is configured it is left out and
            # Kingdee applies the default of the account.
            values["FMaterialGroup"] = {"FNumber": group}
        payload = {}
        for field, value in values.items():
            entity = MATERIAL_FIELD_ENTITY.get(field)
            if entity:
                payload.setdefault(entity, {})[field] = value
            else:
                payload[field] = value
        return payload

    # ------------------------------------------------------------------
    # Inbound: values read from Kingdee
    # ------------------------------------------------------------------
    @staticmethod
    def _kingdee_text(value):
        """Text of one value of a Kingdee answer.

        A ``View`` answer returns a translated field as a locale list
        (``[{"Key": 2052, "Value": "..."}]``) and a reference as a mapping, a
        query answer returns plain strings; the three shapes are normalised here
        so the callers only ever deal with text.
        """
        if value is None or value is False:
            return ""
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("Value") not in (None, ""):
                    return str(item["Value"]).strip()
            return ""
        if isinstance(value, dict):
            for key in ("Value", "FNumber", "Number"):
                if value.get(key) not in (None, ""):
                    return str(value[key]).strip()
            return ""
        return str(value).strip()

    @classmethod
    def _kingdee_mappings(cls, data):
        """Yield every mapping of a nested Kingdee answer, outermost first.

        ``View`` holds the values nested per entity (``SubHeadEntity``, ...), so a
        field has to be searched at any depth. Walking breadth first means the
        root wins, which is where the header fields are.
        """
        queue = [data] if isinstance(data, dict) else []
        while queue:
            node = queue.pop(0)
            yield node
            for value in node.values():
                if isinstance(value, dict):
                    queue.append(value)
                elif isinstance(value, list):
                    queue.extend(item for item in value if isinstance(item, dict))

    @classmethod
    def _kingdee_nested_value(cls, data, key):
        """Value of ``key`` in a ``View`` answer (values nested per entity).

        ``key`` uses the query notation: the first segment names the field, an
        optional second one the property to read on it (``FCategoryID.FNumber``).
        """
        field, _, prop = key.partition(".")
        for mapping in cls._kingdee_mappings(data):
            if field not in mapping:
                continue
            value = mapping[field]
            if not prop:
                return value
            if isinstance(value, dict):
                return value.get(prop)
        return None

    @classmethod
    def _kingdee_row_value(cls, row, key):
        """Value of ``key`` in a query row.

        ``BillQuery`` keys a row with the ``FieldKeys`` exactly as they were sent
        (``FCategoryID.FNumber``), and ``query_rows()`` gives the positional rows
        of ``ExecuteBillQuery`` the same shape. Nothing is ever guessed from the
        bare field name: an unexpected answer shape yields an empty value rather
        than the value of another field (``FNumber`` is also the last segment of
        the three reference keys, so a bare name would be ambiguous).
        """
        return row.get(key)

    @classmethod
    def _kingdee_data_from_row(cls, row):
        """Normalise a query row to the ``KINGDEE_MATERIAL_FIELDS`` key shape."""
        return {
            key: cls._kingdee_text(cls._kingdee_row_value(row, key))
            for key in KINGDEE_MATERIAL_FIELDS
        }

    @classmethod
    def _kingdee_data_from_view(cls, data):
        """Normalise a ``View`` answer to the same key shape."""
        return {
            key: cls._kingdee_text(cls._kingdee_nested_value(data, key))
            for key in KINGDEE_MATERIAL_FIELDS
        }

    @api.model
    def _kingdee_classification_values(self, data):
        """Odoo values of the classification fields a material carries.

        Only the fields the payload derives its values from are returned, so the
        inbound direction stays the exact inverse of the outbound one.
        """
        values = {}
        for key, field in KINGDEE_MATERIAL_VALUE_MAP.items():
            value = data.get(key)
            if value:
                values[field] = value
        return values

    @api.model
    def _kingdee_sync_state(self, data):
        """Synchronization state matching the FDocumentStatus of a material."""
        return KINGDEE_DOCUMENT_STATE.get(data.get("FDocumentStatus"), "saved")

    @api.model
    def _kingdee_is_forbidden(self, data):
        """Whether the material is disabled (FForbidStatus) in Kingdee."""
        return data.get("FForbidStatus") == KINGDEE_FORBIDDEN_STATUS

    def _kingdee_apply_readback(self, data):
        """Store the classification a ``View`` of this material answered.

        Called by ``action_kingdee_pull()``, which already stored the number, the
        name and the master id: this adds the classification fields and the real
        status, so "Refresh from Kingdee" refreshes the record itself and not only
        its synchronization state.
        """
        self.ensure_one()
        flat = self._kingdee_data_from_view(data)
        values = self._kingdee_classification_values(flat)
        values["kingdee_sync_state"] = self._kingdee_sync_state(flat)
        self.write(values)

    # ------------------------------------------------------------------
    # Inbound: import (Kingdee to Odoo)
    # ------------------------------------------------------------------
    @api.model
    def _kingdee_find_material(self, number):
        """Product already linked to the Kingdee material ``number``.

        The link is ``kingdee_number``. A product that only carries the number as
        its internal reference is adopted, which is how an existing Odoo
        catalogue gets linked. A product whose internal reference collides with a
        material linked to another number is a conflict: importing it would create
        a second product, so it is refused instead.
        """
        product = self.search([("kingdee_number", "=", number)], limit=1)
        if product:
            return product
        product = self.search([("default_code", "=", number)], limit=1)
        if not product or not product.kingdee_number:
            return product
        raise UserError(_(
            "The internal reference %(number)s is used by '%(product)s', which is already "
            "linked to the Kingdee number %(linked)s: importing the material %(number)s "
            "would create a second product."
        ) % {
            "number": number,
            "product": product.name,
            "linked": product.kingdee_number,
        })

    @api.model
    def _kingdee_import_row(self, row, update_existing=True, create_missing=True,
                            include_disabled=False, dry_run=False):
        """Create or update one product from a Kingdee material row.

        Returns ``"created"``, ``"updated"`` or ``"skipped"`` (a material the
        caller asked not to touch). With ``dry_run`` the decision is returned and
        nothing is written, which is what the preview reports. The name of an
        existing product is left alone: it is pushed to Kingdee by the payload, so
        Odoo owns it, and the Kingdee name is kept on ``kingdee_name``.
        """
        data = self._kingdee_data_from_row(row)
        number = data.get("FNumber")
        if not number:
            raise UserError(_("Kingdee returned a material without a number."))
        forbidden = self._kingdee_is_forbidden(data)
        if forbidden and not include_disabled:
            return "skipped"
        product = self._kingdee_find_material(number)
        if product and not update_existing:
            return "skipped"
        if not product and not create_missing:
            return "skipped"
        if dry_run:
            # Nothing has been written before this point, so the decision alone
            # is the whole answer and no record has to be touched.
            return "updated" if product else "created"
        values = self._kingdee_classification_values(data)
        values["kingdee_sync_state"] = self._kingdee_sync_state(data)
        values["kingdee_last_sync_at"] = fields.Datetime.now()
        values["kingdee_sync_message"] = (
            _("Imported from Kingdee, where the material is disabled.")
            if forbidden else _("Imported from Kingdee.")
        )
        name = data.get("FName")
        if name:
            values["kingdee_name"] = name
        if product:
            if not product.kingdee_number:
                # The product was adopted through its internal reference: record
                # the link now, otherwise nothing would ever tie the two together.
                values["kingdee_number"] = number
            product.write(values)
            return "updated"
        values["kingdee_number"] = number
        values["kingdee_name"] = name or number
        values["default_code"] = number
        values["name"] = name or number
        self.create(values)
        return "created"

    @api.model
    def _kingdee_import_materials(self, filter_string="", limit=0, update_existing=True,
                                  create_missing=True, include_disabled=False, dry_run=False):
        """Read the Kingdee materials and create or update the matching products.

        Every material runs inside its own savepoint: a row Kingdee or Odoo
        refuses is reported and does not stop the run, the same isolation
        ``_kingdee_run()`` gives to the outbound actions.

        :param str filter_string: Kingdee ``FilterString``, e.g. ``FDocumentStatus = 'C'``.
        :param int limit: highest number of materials read (0 reads them all).
        :param bool dry_run: report what the run would do without writing anything.
            A preview classifies as if both write switches were on, so its counts
            describe a full import.
        :return dict: counters ``read`` / ``created`` / ``updated`` / ``skipped`` /
            ``failed``, and the first failures under ``errors``.
        """
        if dry_run:
            update_existing = create_missing = True
        client = self.env["sn.wsd.kingdee.client"]
        summary = {"read": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0,
                   "errors": []}
        for row in client.iter_bill_query(
            MATERIAL_FORM_ID,
            KINGDEE_MATERIAL_QUERY,
            filter_string=(filter_string or "").strip(),
            order_string="FNumber",
        ):
            if limit and summary["read"] >= limit:
                break
            summary["read"] += 1
            number = self._kingdee_text(self._kingdee_row_value(row, "FNumber"))
            try:
                with self.env.cr.savepoint():
                    outcome = self._kingdee_import_row(
                        row,
                        update_existing=update_existing,
                        create_missing=create_missing,
                        include_disabled=include_disabled,
                        dry_run=dry_run,
                    )
            except Exception as err:  # noqa: BLE001 - reported, the run must go on
                summary["failed"] += 1
                _logger.warning(
                    "Kingdee material import failed for %s: %s", number or "?", err,
                )
                if len(summary["errors"]) < 5:
                    summary["errors"].append(_("%(number)s: %(message)s") % {
                        "number": number or "?", "message": err,
                    })
                continue
            summary[outcome] += 1
        return summary

    @api.model
    def _kingdee_import_notification(self, summary, dry_run=False):
        """Notification reporting the outcome of an import or preview run."""
        label = (_("Preview of Import Materials from Kingdee") if dry_run
                 else _("Import Materials from Kingdee"))
        counts = {
            "label": label,
            "created": summary["created"],
            "updated": summary["updated"],
            "skipped": summary["skipped"],
        }
        if dry_run:
            done = _("%(label)s: %(created)s to create, %(updated)s to update, "
                     "%(skipped)s skipped.")
            failed = _("%(label)s: %(created)s to create, %(updated)s to update, "
                       "%(skipped)s skipped, %(failed)s failed.\n%(details)s")
        else:
            done = _("%(label)s: %(created)s created, %(updated)s updated, %(skipped)s skipped.")
            failed = _("%(label)s: %(created)s created, %(updated)s updated, %(skipped)s skipped, "
                       "%(failed)s failed.\n%(details)s")
        if not summary["failed"]:
            return self._kingdee_notify(_("Kingdee"), done % counts)
        details = "\n".join(summary["errors"])
        return self._kingdee_notify(
            _("Kingdee"),
            failed % dict(counts, failed=summary["failed"], details=details),
            kind="danger",
            sticky=True,
        )

    # ------------------------------------------------------------------
    # Scheduled job
    # ------------------------------------------------------------------
    @api.model
    def _cron_kingdee_pull_materials(self):
        """Refresh the materials already linked to Kingdee, oldest sync first."""
        client = self.env["sn.wsd.kingdee.client"]
        if not client.is_enabled():
            _logger.info("Kingdee material refresh skipped: the integration is disabled.")
            return False
        products = self.search(
            [("kingdee_number", "!=", False)],
            limit=CRON_BATCH_SIZE,
            order="kingdee_last_sync_at asc, id asc",
        )
        if not products:
            _logger.info("Kingdee material refresh skipped: no linked material found.")
            return False
        products.action_kingdee_pull()
        return True


class ProductProduct(models.Model):
    """Kingdee material actions on the product variants.

    The Kingdee page of the product form also shows up on ``product.product``:
    the variant form is a primary view built on the template form
    (``product.product_normal_form_view`` inherits
    ``product.product_template_form_view``), so its buttons are validated
    against ``product.product``. The variant does not inherit the template's
    methods in Odoo 19 (``_inherits`` only delegates the fields), therefore
    every action is exposed here and delegated to the template, where the
    whole synchronization state lives.
    """

    _inherit = "product.product"

    def action_kingdee_save(self):
        return self.product_tmpl_id.action_kingdee_save()

    def action_kingdee_submit(self):
        return self.product_tmpl_id.action_kingdee_submit()

    def action_kingdee_audit(self):
        return self.product_tmpl_id.action_kingdee_audit()

    def action_kingdee_unaudit(self):
        return self.product_tmpl_id.action_kingdee_unaudit()

    def action_kingdee_pull(self):
        return self.product_tmpl_id.action_kingdee_pull()

    def action_kingdee_delete(self):
        return self.product_tmpl_id.action_kingdee_delete()

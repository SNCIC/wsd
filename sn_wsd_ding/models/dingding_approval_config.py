# -*- coding: utf-8 -*-

import json
import logging
import re
from datetime import date, datetime

import pytz

from odoo import _, Command, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SnWsdDingApprovalConfig(models.Model):
    _name = "sn.wsd.ding.approval.config"
    _description = "DingTalk Approval Config"
    _order = "name, id"

    active = fields.Boolean(default=True)
    name = fields.Char(required=True)
    process_code = fields.Char(string="DingTalk Process Code", required=True)
    description = fields.Text()
    target_model_id = fields.Many2one(
        "ir.model",
        string="Target Model",
        help="If set, this config is intended to be launched from records of this model, and record_field mappings will read from that record.",
    )
    server_action_id = fields.Many2one(
        "ir.actions.server",
        string="One-click Server Action",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Generated server action bound to the target model to launch this DingTalk approval from documents.",
    )
    dingding_schema_json = fields.Text(string="DingTalk Schema (raw)", readonly=True, copy=False)
    dingding_schema_sync_at = fields.Datetime(string="Schema Synced At", readonly=True, copy=False)
    field_ids = fields.One2many(
        "sn.wsd.ding.approval.field",
        "config_id",
        string="Field Mappings",
        copy=True,
    )

    @staticmethod
    def _norm(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    @staticmethod
    def _norm_label(s):
        # For matching DingTalk labels/ids across sync runs: keep unicode word chars (incl. CJK),
        # drop whitespace/punctuation/underscores, and case-fold latin letters.
        return re.sub(r"[\W_]+", "", (s or "").strip(), flags=re.UNICODE).lower()

    def _extract_dingding_fields(self, payload):
        def parse_json(value):
            if not value:
                return None
            if isinstance(value, (dict, list)):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return None
            return None

        if isinstance(payload, dict):
            candidate = payload.get("result") or payload.get("data") or payload
            if isinstance(candidate, list) and candidate and isinstance(candidate[0], dict):
                # Some SDK APIs (batchQuery) return {"result": [ {..., schemaContent: "..."} ]}
                first = candidate[0]
                for key in ("schemaContent", "schema_content", "processConfig", "process_config", "formSchema", "form_schema"):
                    parsed = parse_json(first.get(key))
                    if parsed is not None:
                        payload = parsed
                        break
            elif isinstance(candidate, dict):
                for key in ("formSchema", "form_schema", "processConfig", "process_config", "content"):
                    parsed = parse_json(candidate.get(key))
                    if parsed is not None:
                        payload = parsed
                        break
                schema_content = candidate.get("schemaContent") or candidate.get("schema_content")
                if isinstance(schema_content, dict):
                    items = schema_content.get("items") or []
                    if isinstance(items, list) and items:
                        def map_item(item):
                            if not isinstance(item, dict):
                                return None
                            props = item.get("props") or {}
                            field_id = props.get("id") or item.get("id")
                            label = props.get("label") or props.get("title") or props.get("name") or item.get("componentName")
                            ftype = item.get("componentName") or props.get("componentType") or props.get("type")
                            if not field_id or not ftype:
                                return None
                            required = props.get("required")
                            if not label:
                                label = field_id
                            entry = {
                                "id": str(field_id),
                                "name": str(label),
                                "type": str(ftype),
                                "required": bool(required) if required is not None else False,
                            }
                            children = item.get("children") or []
                            if isinstance(children, list) and children:
                                child_entries = []
                                for c in children:
                                    cprops = c.get("props") or {}
                                    child_id = cprops.get("id") or c.get("id")
                                    child_label = cprops.get("label") or cprops.get("title") or cprops.get("name") or c.get("componentName")
                                    ctype = c.get("componentName") or cprops.get("componentType") or cprops.get("type")
                                    if not child_id or not ctype:
                                        continue
                                    creq = cprops.get("required")
                                    child_entries.append(
                                        {
                                            "id": str(child_id),
                                            "name": str(child_label or child_id),
                                            "type": str(ctype),
                                            "required": bool(creq) if creq is not None else False,
                                        }
                                    )
                                if child_entries:
                                    entry["children"] = child_entries
                            return entry

                        entries = []
                        for it in items:
                            e = map_item(it)
                            if e:
                                entries.append(e)
                        if entries:
                            return entries

        def walk(obj):
            if isinstance(obj, dict):
                yield obj
                for v in obj.values():
                    yield from walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from walk(v)

        def pick_children(obj):
            if not isinstance(obj, dict):
                return []
            for key in ("children", "component_list", "components", "detail_list"):
                value = obj.get(key)
                if isinstance(value, list):
                    return value
            props = obj.get("props") if isinstance(obj.get("props"), dict) else {}
            for key in ("components", "detail_list", "component_list"):
                value = props.get(key)
                if isinstance(value, list):
                    return value
            return []

        candidates = []
        for d in walk(payload):
            field_id = d.get("id") or d.get("field_id") or d.get("fieldId")
            label = d.get("label") or d.get("title") or d.get("display_name") or d.get("displayName")
            ctype = d.get("component_type") or d.get("type") or d.get("componentName")
            if not field_id or not ctype:
                continue
            required = d.get("required")
            if required is None:
                required = d.get("is_required")
            if not label:
                label = field_id
            entry = {
                "id": str(field_id),
                "name": str(label),
                "type": str(ctype),
                "required": bool(required) if required is not None else False,
            }
            children = pick_children(d)
            if children:
                child_entries = []
                for c in children:
                    if not isinstance(c, dict):
                        continue
                    child_id = c.get("id") or c.get("field_id") or c.get("fieldId")
                    child_label = c.get("label") or c.get("title") or c.get("display_name") or c.get("displayName")
                    ctype = c.get("component_type") or c.get("type") or c.get("componentName")
                    if not child_id or not ctype:
                        continue
                    creq = c.get("required")
                    if creq is None:
                        creq = c.get("is_required")
                    child_entries.append(
                        {
                            "id": str(child_id),
                            "name": str(child_label or child_id),
                            "type": str(ctype),
                            "required": bool(creq) if creq is not None else False,
                        }
                    )
                if child_entries:
                    entry["children"] = child_entries
            candidates.append(entry)

        seen = set()
        fields_list = []
        for item in candidates:
            key = self._norm_label(item.get("id") or item.get("name"))
            if not key or key in seen:
                continue
            seen.add(key)
            fields_list.append(item)
        return fields_list

    def _suggest_record_field(self, mapping_line):
        self.ensure_one()
        target_model = mapping_line.record_field_model_id or self.target_model_id
        if not target_model:
            return None

        dingding_key = self._norm(mapping_line.dingding_field_name or mapping_line.dingding_field_id)
        if not dingding_key:
            return None

        candidates = self.env["ir.model.fields"].search(
            [
                ("model_id", "=", target_model.id),
                ("store", "=", True),
            ]
        )
        matched = []
        for f in candidates:
            if self._norm(f.name) == dingding_key or self._norm(f.field_description) == dingding_key:
                matched.append(f)
        if len(matched) == 1:
            return matched[0]
        return None

    def _sanitize_field_type(self, value):
        allowed = set(dict(self.env["sn.wsd.ding.approval.field"].
                           _fields["dingding_field_type"].selection).keys())
        raw = (value or "").strip()
        lowered = raw.lower()
        if "table" in lowered:
            return "table"
        if "attach" in lowered:
            return "attachment"
        if "date" in lowered:
            return "date"
        if "money" in lowered or "amount" in lowered:
            return "money"
        if "number" in lowered or "numeric" in lowered:
            return "number"
        if "textarea" in lowered:
            return "textarea"
        if "multi" in lowered and "select" in lowered:
            return "multi_select"
        if "select" in lowered:
            return "select"
        if "user" in lowered:
            return "user"
        if "dept" in lowered or "department" in lowered:
            return "department"
        return raw if raw in allowed else "text"

    def _apply_synced_fields(self, dingding_fields, *, overwrite=False):
        self.ensure_one()
        if not dingding_fields:
            return

        if not self.id:
            commands = []
            seq = 10
            for f in dingding_fields:
                vals = {
                    "sequence": seq,
                    "dingding_field_name": f["name"],
                    "dingding_field_id": f["id"],
                    "dingding_field_type": self._sanitize_field_type(f.get("type")),
                    "required": bool(f.get("required")),
                }
                if f.get("children"):
                    child_commands = []
                    child_seq = 10
                    for c in f["children"]:
                        child_commands.append(
                            Command.create(
                                {
                                    "sequence": child_seq,
                                    "dingding_field_name": c["name"],
                                    "dingding_field_id": c["id"],
                                    "dingding_field_type": self._sanitize_field_type(c.get("type")),
                                    "required": bool(c.get("required")),
                                }
                            )
                        )
                        child_seq += 10
                    vals["child_ids"] = child_commands
                commands.append(Command.create(vals))
                seq += 10
            if overwrite or not self.field_ids:
                self.field_ids = commands
            if self.target_model_id:
                for line in self.field_ids:
                    if line.dingding_field_type == "table":
                        continue
                    if line.record_field_id:
                        continue
                    suggested = self._suggest_record_field(line)
                    if suggested:
                        line.record_field_id = suggested
            return

        seq = (max(self.field_ids.mapped("sequence")) if self.field_ids else 0) + 10
        for f in dingding_fields:
            parent = self.env["sn.wsd.ding.approval.field"].create(
                {
                    "config_id": self.id,
                    "sequence": seq,
                    "dingding_field_name": f["name"],
                    "dingding_field_id": f["id"],
                    "dingding_field_type": self._sanitize_field_type(f.get("type")),
                    "required": bool(f.get("required")),
                    "parent_field_id": False,
                }
            )
            seq += 10
            if f.get("children"):
                child_seq = 10
                for c in f["children"]:
                    self.env["sn.wsd.ding.approval.field"].create(
                        {
                            "config_id": self.id,
                            "sequence": child_seq,
                            "dingding_field_name": c["name"],
                            "dingding_field_id": c["id"],
                            "dingding_field_type": self._sanitize_field_type(c.get("type")),
                            "required": bool(c.get("required")),
                            "parent_field_id": parent.id,
                        }
                    )
                    child_seq += 10

        for line in self.field_ids:
            if line.dingding_field_type == "table":
                continue
            if line.record_field_id:
                continue
            suggested = self._suggest_record_field(line)
            if suggested:
                line.write({"record_field_id": suggested.id})

    def action_sync_dingding_fields(self):
        for rec in self:
            payload = self.env["sn.wsd.ding.client"].get_process_definition(rec.process_code)
            rec.dingding_schema_json = json.dumps(payload, ensure_ascii=False, indent=2)
            rec.dingding_schema_sync_at = fields.Datetime.now()
            dingding_fields = rec._extract_dingding_fields(payload)
            if not dingding_fields:
                raise UserError(_("No fields found from DingTalk process definition."))
            rec._backfill_dingding_field_ids(dingding_fields)
            rec._sync_dingding_fields_incremental(dingding_fields)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": _("DingTalk fields synced."),
                "type": "success",
                "sticky": False,
            },
        }

    def _backfill_dingding_field_ids(self, dingding_fields):
        self.ensure_one()
        Field = self.env["sn.wsd.ding.approval.field"]

        def key_of(vals):
            return (vals.get("id") or vals.get("name") or "").strip()

        def norm_name(value):
            return self._norm_label(value)

        def existing_id(line):
            return (line.dingding_field_id or "").strip()

        def existing_label(line):
            return (line.dingding_field_name or "").strip()

        incoming_parents = [f for f in (dingding_fields or []) if isinstance(f, dict) and key_of(f)]
        incoming_by_id = {key_of(f): f for f in incoming_parents}

        incoming_by_name_norm = {}
        for f in incoming_parents:
            name_key = norm_name(f.get("name"))
            if not name_key:
                continue
            incoming_by_name_norm.setdefault(name_key, []).append(f)

        def match_one(incoming_list, *, label, field_type):
            if not incoming_list:
                return None
            if len(incoming_list) == 1:
                return incoming_list[0]
            typed = [f for f in incoming_list if self._sanitize_field_type(f.get("type")) == (field_type or "")]
            if len(typed) == 1:
                return typed[0]
            return None

        parents = Field.search([("config_id", "=", self.id), ("parent_field_id", "=", False)])
        # 1) backfill parent ids by name (unique match) without touching other columns
        for p in parents.filtered(lambda r: not existing_id(r) and existing_label(r)):
            matches = incoming_by_name_norm.get(norm_name(existing_label(p)), [])
            matched = match_one(matches, label=existing_label(p), field_type=p.dingding_field_type)
            if matched:
                p.write({"dingding_field_id": key_of(matched)})

        # 2) backfill child ids per table-parent (prefer parent id; fallback to parent name match)
        parents = parents.exists()
        for parent in parents.filtered(lambda r: r.child_ids):
            if not parent.child_ids.filtered(lambda c: not existing_id(c) and existing_label(c)):
                continue

            parent_incoming = None
            if existing_id(parent):
                parent_incoming = incoming_by_id.get(existing_id(parent))
            if not parent_incoming and existing_label(parent):
                matches = incoming_by_name_norm.get(norm_name(existing_label(parent)), [])
                matched = match_one(matches, label=existing_label(parent), field_type=parent.dingding_field_type)
                if matched:
                    parent_incoming = matched
                    if not existing_id(parent):
                        parent.write({"dingding_field_id": key_of(matched)})

            if not parent_incoming:
                continue

            incoming_children = [c for c in (parent_incoming.get("children") or []) if isinstance(c, dict) and key_of(c)]
            incoming_children_by_name_norm = {}
            for c in incoming_children:
                name_key = norm_name(c.get("name"))
                if not name_key:
                    continue
                incoming_children_by_name_norm.setdefault(name_key, []).append(c)

            for child in parent.child_ids.filtered(lambda r: not existing_id(r) and existing_label(r)):
                matches = incoming_children_by_name_norm.get(norm_name(existing_label(child)), [])
                matched = match_one(matches, label=existing_label(child), field_type=child.dingding_field_type)
                if matched:
                    child.write({"dingding_field_id": key_of(matched)})

    def _sync_dingding_fields_incremental(self, dingding_fields):
        self.ensure_one()
        Field = self.env["sn.wsd.ding.approval.field"]

        def key_of(vals):
            return (vals.get("id") or vals.get("name") or "").strip()

        def norm_name(value):
            return self._norm_label(value)

        def existing_id(line):
            return (line.dingding_field_id or "").strip()

        def existing_label(line):
            return (line.dingding_field_name or "").strip()

        incoming = [f for f in (dingding_fields or []) if isinstance(f, dict) and key_of(f)]
        incoming_ids = {key_of(f) for f in incoming}
        incoming_count_by_name_type = {}
        for f in incoming:
            name_key = norm_name(f.get("name"))
            ftype = self._sanitize_field_type(f.get("type"))
            incoming_count_by_name_type[(name_key, ftype)] = incoming_count_by_name_type.get((name_key, ftype), 0) + 1

        parents = Field.search([("config_id", "=", self.id), ("parent_field_id", "=", False)])
        parents = parents.exists()
        parents_by_id = {existing_id(p): p for p in parents if existing_id(p)}

        # Only delete when we can match by DingTalk field id; never delete "legacy" rows without id (to avoid wiping mappings).
        to_remove = parents.filtered(lambda p: existing_id(p) and existing_id(p) not in incoming_ids)
        if to_remove:
            to_remove.unlink()
            parents = parents.exists()
            parents_by_id = {existing_id(p): p for p in parents if existing_id(p)}

        parent_seq = (max(parents.mapped("sequence")) if parents else 0) + 10
        for f in incoming:
            field_id = key_of(f)
            label = (f.get("name") or field_id).strip()
            ftype = self._sanitize_field_type(f.get("type"))
            required = bool(f.get("required"))

            parent = parents_by_id.get(field_id)
            if not parent:
                name_key = norm_name(label)
                if incoming_count_by_name_type.get((name_key, ftype), 0) == 1:
                    candidates = parents.filtered(
                        lambda p: not existing_id(p)
                        and norm_name(existing_label(p))
                        and norm_name(existing_label(p)) == name_key
                        and p.dingding_field_type == ftype
                    )
                    if len(candidates) == 1:
                        parent = candidates[0]
                        parent.write({"dingding_field_id": field_id})
                        parents_by_id[field_id] = parent

            if not parent:
                parent = Field.create(
                    {
                        "config_id": self.id,
                        "sequence": parent_seq,
                        "dingding_field_id": field_id,
                        "dingding_field_name": label,
                        "dingding_field_type": ftype,
                        "required": required,
                        "parent_field_id": False,
                    }
                )
                parents_by_id[field_id] = parent
                parent_seq += 10
            else:
                vals = {}
                if not parent.dingding_field_id:
                    vals["dingding_field_id"] = field_id
                if parent.dingding_field_name != label:
                    vals["dingding_field_name"] = label
                if parent.dingding_field_type != ftype:
                    vals["dingding_field_type"] = ftype
                if parent.required != required:
                    vals["required"] = required
                if vals:
                    parent.write(vals)

            incoming_children = [c for c in (f.get("children") or []) if isinstance(c, dict) and key_of(c)]
            if not incoming_children and parent.child_ids:
                parent.child_ids.unlink()
                continue
            if not incoming_children:
                continue

            incoming_child_count_by_name_type = {}
            for child_vals in incoming_children:
                name_key = norm_name(child_vals.get("name"))
                ctype = self._sanitize_field_type(child_vals.get("type"))
                incoming_child_count_by_name_type[(name_key, ctype)] = (
                    incoming_child_count_by_name_type.get((name_key, ctype), 0) + 1
                )
            remaining_children = parent.child_ids.exists()
            existing_children_by_id = {existing_id(c): c for c in remaining_children if existing_id(c)}
            incoming_child_ids = {key_of(c) for c in incoming_children}

            children_to_remove = remaining_children.filtered(lambda c: existing_id(c) and existing_id(c) not in incoming_child_ids)
            if children_to_remove:
                children_to_remove.unlink()

            remaining_children = parent.child_ids.exists()
            child_seq = (max(remaining_children.mapped("sequence")) if remaining_children else 0) + 10
            for c in incoming_children:
                child_id = key_of(c)
                child_label = (c.get("name") or child_id).strip()
                child_type = self._sanitize_field_type(c.get("type"))
                child_required = bool(c.get("required"))

                child = existing_children_by_id.get(child_id)
                if not child:
                    name_key = norm_name(child_label)
                    if incoming_child_count_by_name_type.get((name_key, child_type), 0) == 1:
                        candidates = remaining_children.filtered(
                            lambda r: not existing_id(r)
                            and norm_name(existing_label(r))
                            and norm_name(existing_label(r)) == name_key
                            and r.dingding_field_type == child_type
                        )
                        if len(candidates) == 1:
                            child = candidates[0]
                            child.write({"dingding_field_id": child_id})
                            existing_children_by_id[child_id] = child

                if not child:
                    Field.create(
                        {
                            "config_id": self.id,
                            "sequence": child_seq,
                            "dingding_field_id": child_id,
                            "dingding_field_name": child_label,
                            "dingding_field_type": child_type,
                            "required": child_required,
                            "parent_field_id": parent.id,
                        }
                    )
                    child_seq += 10
                    continue

                vals = {}
                if not child.dingding_field_id:
                    vals["dingding_field_id"] = child_id
                if child.dingding_field_name != child_label:
                    vals["dingding_field_name"] = child_label
                if child.dingding_field_type != child_type:
                    vals["dingding_field_type"] = child_type
                if child.required != child_required:
                    vals["required"] = child_required
                if vals:
                    child.write(vals)

    def action_fetch_process_code_by_name(self):
        for rec in self:
            schema_name = (rec.name or "").strip()
            if not schema_name:
                raise UserError(_("Name is required to fetch DingTalk template code."))
            code = rec.env["sn.wsd.ding.client"].get_process_code_by_name(schema_name)
            if not code:
                raise UserError(_("DingTalk template code not found for name: %s") % schema_name)
            rec.process_code = code
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": _("Template code updated."),
                "type": "success",
                "sticky": False,
            },
        }

    def _server_action_code(self):
        self.ensure_one()
        return f"action = env['sn.wsd.ding.approval.config'].browse({self.id}).action_launch_for_records(records)"

    def action_generate_server_action(self):
        for rec in self:
            if not rec.target_model_id:
                raise UserError(_("Please set Target Model first."))
            values = {
                "name": _("Launch DingTalk Approval: %s") % (rec.name,),
                "model_id": rec.target_model_id.id,
                "binding_model_id": rec.target_model_id.id,
                "binding_view_types": "form,list",
                "state": "code",
                "code": rec._server_action_code(),
                "group_ids": [Command.link(self.env.ref("base.group_system").id)],
            }
            if rec.server_action_id:
                rec.server_action_id.write(values)
            else:
                rec.server_action_id = self.env["ir.actions.server"].create(values).id
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": _("One-click action generated/updated. Please refresh the page."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_launch_for_records(self, records):
        self.ensure_one()
        if not records:
            raise UserError(_("No records selected."))

        if self.target_model_id and records._name != self.target_model_id.model:
            raise UserError(_("This approval config is for model %s.") % self.target_model_id.model)

        client = self.env["sn.wsd.ding.client"]
        initiator_user = self.env.user

        initiator_dingding_user_id = (initiator_user.sudo().dingding_user_id or "").strip()
        if not initiator_dingding_user_id:
            initiator_phone = (
                getattr(initiator_user, "phone", False)
                or (initiator_user.partner_id and getattr(initiator_user.partner_id, "phone", False))
                or ""
            )
            if not initiator_phone:
                raise UserError(_("Current user has no phone; cannot map to DingTalk user."))
            initiator_dingding_user_id = client.get_user_id_by_mobile(initiator_phone)
            try:
                initiator_user.sudo().write({"dingding_user_id": initiator_dingding_user_id})
            except Exception:
                _logger.exception("Failed to cache DingTalk user_id on res.users for user=%s", initiator_user.id)

        # DingTalk approvals may require dept_id; try to infer from DingTalk user profile.
        initiator_dept_id = None
        try:
            initiator_dept_id = client.get_user_primary_dept_id(initiator_dingding_user_id)
        except Exception:
            _logger.exception("Failed to fetch DingTalk dept_id for user_id=%s", initiator_dingding_user_id)

        ok = 0
        errors = []
        Instance = self.env["sn.wsd.ding.approval.instance"]

        for record in records:
            try:
                existing = Instance.search(
                    [("res_model", "=", record._name), ("res_id", "=", record.id)],
                    order="id desc",
                    limit=1,
                )
                if existing:
                    errors.append(
                        _(
                            "%(name)s: DingTalk approval already launched (config: %(config)s, instance: %(code)s, status: %(status)s)."
                        )
                        % {
                            "name": record.display_name,
                            "config": existing.config_id.display_name,
                            "code": existing.process_instance_id,
                            "status": existing.status or "-",
                        }
                    )
                    continue

                form_values = self.build_dingding_form(record=record)
                payload = client.create_process_instance(
                    process_code=self.process_code,
                    originator_user_id=initiator_dingding_user_id,
                    form_component_values=form_values,
                    dept_id=initiator_dept_id,
                )
                result = payload.get("result") or {}
                process_instance_id = (
                    result.get("process_instance_id")
                    or result.get("instance_id")
                    or payload.get("processInstanceId")
                    or payload.get("process_instance_id")
                    or payload.get("instanceId")
                    or (payload.get("processInstance") or {}).get("instanceId")
                )
                if not process_instance_id:
                    raise UserError(_("DingTalk response missing process_instance_id."))

                status = (
                    result.get("status")
                    or payload.get("status")
                    or (payload.get("processInstance") or {}).get("status")
                    or ""
                )
                Instance.create(
                    {
                        "config_id": self.id,
                        "process_instance_id": process_instance_id,
                        "status": status,
                        "start_time": False,
                        "end_time": False,
                        "initiator_user_id": initiator_user.id,
                        "res_model": record._name,
                        "res_id": record.id,
                        "raw_response": json.dumps(payload, ensure_ascii=False, indent=2),
                    }
                )
                ok += 1
                _logger.info(
                    "DingTalk approval launched: config=%s(%s) process_code=%s model=%s id=%s instance=%s",
                    self.id,
                    self.display_name,
                    self.process_code,
                    record._name,
                    record.id,
                    process_instance_id,
                )
            except Exception as e:
                errors.append(f"{record.display_name}: {e}")
                _logger.exception(
                    "DingTalk approval launch failed: config=%s(%s) process_code=%s model=%s id=%s",
                    self.id,
                    self.display_name,
                    self.process_code,
                    record._name,
                    record.id,
                )

        message_lines = [
            _("Launched: %(ok)s, Errors: %(err)s") % {"ok": ok, "err": len(errors)},
        ]
        if errors:
            message_lines.append(_("First errors (max 10):"))
            message_lines.extend(errors[:10])
            message_lines.append(_("See server logs for full traceback."))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": "\n".join(message_lines),
                "type": "warning" if errors else "success",
                "sticky": bool(errors),
            },
        }

    @api.onchange("process_code")
    def _onchange_process_code_sync_fields(self):
        if not self.process_code or self.field_ids:
            return
        try:
            payload = self.env["sn.wsd.ding.client"].get_process_definition(self.process_code)
            self.dingding_schema_json = json.dumps(payload, ensure_ascii=False, indent=2)
            dingding_fields = self._extract_dingding_fields(payload)
            if dingding_fields:
                self._apply_synced_fields(dingding_fields, overwrite=False)
        except Exception as e:
            return {
                "warning": {
                    "title": _("DingTalk"),
                    "message": _("Failed to sync fields from DingTalk: %s") % e,
                }
            }

    @api.onchange("target_model_id")
    def _onchange_target_model_id_suggest_fields(self):
        for rec in self:
            if not rec.target_model_id:
                continue
            for line in rec.field_ids:
                if line.record_field_id:
                    continue
                suggested = rec._suggest_record_field(line)
                if suggested:
                    line.record_field_id = suggested

    def build_dingding_form(self, *, record=None):
        self.ensure_one()
        form_items = []
        for line in self.field_ids.filtered(lambda l: not l.parent_field_id).sorted("sequence"):
            if not line.dingding_field_id:
                raise UserError(
                    _("DingTalk component ID is missing for field: %s") % (line.dingding_field_name,)
                )
            value = line.compute_value(record=record)
            if line.required and (value in (None, "") or (isinstance(value, list) and not value)):
                raise UserError(_("Required DingTalk field missing: %s") % (line.dingding_field_name,))
            form_items.append(
                {
                    "name": line.dingding_field_id,
                    "value": value if value not in (None, False) else "",
                }
            )
        return form_items


class SnWsdDingApprovalField(models.Model):
    _name = "sn.wsd.ding.approval.field"
    _description = "DingTalk Approval Field Mapping"
    _order = "owner_sort, sequence, id"

    config_id = fields.Many2one("sn.wsd.ding.approval.config", required=True, ondelete="cascade")
    parent_field_id = fields.Many2one("sn.wsd.ding.approval.field", ondelete="cascade", index=True)
    child_ids = fields.One2many("sn.wsd.ding.approval.field", "parent_field_id", string="Detail Fields")
    target_model_id = fields.Many2one(related="config_id.target_model_id", readonly=True, store=False)
    line_model_id = fields.Many2one("ir.model", compute="_compute_line_model_id", store=False, readonly=True)
    record_field_model_id = fields.Many2one("ir.model", compute="_compute_record_field_model_id", store=False, readonly=True)
    record_field_model_name = fields.Char(compute="_compute_record_field_model_name", store=False, readonly=True)
    field_owner = fields.Char(string="Field Owner", compute="_compute_field_owner", store=False, readonly=True)
    owner_sort = fields.Char(string="Owner Sort", compute="_compute_owner_sort", store=True, readonly=True, index=True)
    sequence = fields.Integer(default=10)

    dingding_field_id = fields.Char(string="DingTalk Field ID", copy=False, index=True)
    dingding_field_name = fields.Char(string="DingTalk Field Name", required=True)
    dingding_field_type = fields.Selection(
        [
            ("text", "text"),
            ("textarea", "textarea"),
            ("number", "number"),
            ("date", "date"),
            ("money", "money"),
            ("select", "select"),
            ("multi_select", "multi_select"),
            ("attachment", "attachment"),
            ("table", "table"),
            ("user", "user"),
            ("department", "department"),
        ],
        string="DingTalk Field Type",
        required=True,
        default="text",
    )
    required = fields.Boolean(default=False)

    record_o2m_field_id = fields.Many2one(
        "ir.model.fields",
        string="Odoo Detail Table (One2many)",
        domain="[('ttype','=','one2many'), ('model_id', '=', target_model_id)]",
        help="For DingTalk table field: choose the One2many field on the target model that represents the detail table.",
    )
    record_field_id = fields.Many2one(
        "ir.model.fields",
        string="Record Field",
        domain="[('store','=',True), ('model_id', '=', record_field_model_id)]",
    )
    record_field_path = fields.Char(
        string="Record Field Path",
        compute="_compute_record_field_path",
        inverse="_inverse_record_field_path",
        store=True,
    )

    @api.depends("parent_field_id", "parent_field_id.record_o2m_field_id", "parent_field_id.record_o2m_field_id.field_description")
    def _compute_field_owner(self):
        for rec in self:
            if rec.parent_field_id:
                o2m = rec.parent_field_id.record_o2m_field_id
                rec.field_owner = o2m.field_description if o2m else "Detail"
            else:
                rec.field_owner = "Main"

    @api.depends("parent_field_id", "parent_field_id.record_o2m_field_id")
    def _compute_owner_sort(self):
        for rec in self:
            if rec.parent_field_id:
                o2m_id = rec.parent_field_id.record_o2m_field_id.id if rec.parent_field_id.record_o2m_field_id else 999999
                rec.owner_sort = f"1_detail_{o2m_id:06d}"
                continue
            if rec.dingding_field_type == "table":
                o2m_id = rec.record_o2m_field_id.id if rec.record_o2m_field_id else 999999
                rec.owner_sort = f"1_detail_{o2m_id:06d}"
            else:
                rec.owner_sort = "0_main"

    @api.depends("record_o2m_field_id")
    def _compute_line_model_id(self):
        IrModel = self.env["ir.model"]
        for rec in self:
            rec.line_model_id = False
            if rec.dingding_field_type == "table" and rec.record_o2m_field_id and rec.record_o2m_field_id.relation:
                rec.line_model_id = IrModel.search([("model", "=", rec.record_o2m_field_id.relation)], limit=1).id

    @api.depends("parent_field_id", "config_id.target_model_id", "parent_field_id.line_model_id")
    def _compute_record_field_model_id(self):
        for rec in self:
            if rec.parent_field_id:
                rec.record_field_model_id = rec.parent_field_id.line_model_id
            else:
                rec.record_field_model_id = rec.config_id.target_model_id

    @api.depends("record_field_model_id")
    def _compute_record_field_model_name(self):
        for rec in self:
            rec.record_field_model_name = rec.record_field_model_id.model or ""

    @api.depends("record_field_id")
    def _compute_record_field_path(self):
        for rec in self:
            if rec.record_field_id:
                rec.record_field_path = rec.record_field_id.name or ""
            elif rec.record_field_path:
                rec.record_field_path = rec.record_field_path
            else:
                rec.record_field_path = False

    def _validate_record_field_path(self, *, model_name, path):
        if not model_name:
            raise UserError(_("Please set the target model before selecting a record field."))
        if not path:
            return

        IrModelFields = self.env["ir.model.fields"]
        segments = [p for p in path.split(".") if p]
        if not segments:
            raise UserError(_("Invalid record field path."))

        current_model = model_name
        for i, name in enumerate(segments):
            field = IrModelFields.search([("model", "=", current_model), ("name", "=", name)], limit=1)
            if not field:
                raise UserError(_("Invalid field '%(field)s' on model '%(model)s'.") % {"field": name, "model": current_model})
            is_last = i == len(segments) - 1
            if not is_last:
                if field.ttype != "many2one" or not field.relation:
                    raise UserError(
                        _("Field path can only follow many2one relations. '%(field)s' on '%(model)s' is %(ttype)s.")
                        % {"field": name, "model": current_model, "ttype": field.ttype}
                    )
                current_model = field.relation
        return

    def _inverse_record_field_path(self):
        IrModelFields = self.env["ir.model.fields"]
        for rec in self:
            path = (rec.record_field_path or "").strip()
            if not path:
                rec.record_field_path = False
                rec.record_field_id = False
                continue

            model_name = rec.record_field_model_id.model if rec.record_field_model_id else ""
            rec._validate_record_field_path(model_name=model_name, path=path)

            if "." not in path:
                field = IrModelFields.search(
                    [
                        ("model", "=", model_name),
                        ("name", "=", path),
                        ("store", "=", True),
                    ],
                    limit=1,
                )
                rec.record_field_id = field
            else:
                rec.record_field_id = False

    def _stringify_record_value(self, record_value):
        if record_value is None or record_value is False:
            return ""
        if isinstance(record_value, models.BaseModel):
            return record_value.display_name or ""
        if isinstance(record_value, (list, tuple, set)):
            return ", ".join(str(v) for v in record_value)
        return str(record_value)

    def compute_value(self, *, record):
        self.ensure_one()
        if self.dingding_field_type == "table":
            if not record:
                raise UserError(_("Record is required to build DingTalk form from record fields."))
            if not self.record_o2m_field_id:
                return []
            lines = record[self.record_o2m_field_id.name]
            rows = []
            for line in lines:
                row_items = []
                for child in self.child_ids.sorted("sequence"):
                    if not child.dingding_field_id:
                        raise UserError(
                            _("DingTalk component ID is missing for field: %s")
                            % (child.dingding_field_name,)
                        )
                    value = child.compute_value(record=line)
                    row_items.append(
                        {
                            "name": child.dingding_field_id,
                            "value": value if value not in (None, False) else "",
                        }
                    )
                rows.append(row_items)
            return json.dumps(rows, ensure_ascii=False)

        if not record:
            raise UserError(_("Record is required to build DingTalk form from record fields."))

        field_path = (self.record_field_path or "").strip() or (self.record_field_id.name if self.record_field_id else "")
        if not field_path:
            return ""

        current = record
        for name in [p for p in field_path.split(".") if p]:
            if not isinstance(current, models.BaseModel):
                raise UserError(_("Invalid value while following field path '%s'.") % field_path)
            current = current[name]
        record_value = current
        if self.dingding_field_type == "attachment":
            if not record_value:
                return "[]"
            if isinstance(record_value, str):
                s = record_value.strip()
                if not s:
                    return "[]"
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        return json.dumps(parsed, ensure_ascii=False)
                except Exception:
                    pass
                tokens = [t.strip() for t in s.split(",") if t.strip()]
                return json.dumps(tokens, ensure_ascii=False)
            if isinstance(record_value, (list, tuple, set)):
                return json.dumps([v for v in record_value if v], ensure_ascii=False)
            if isinstance(record_value, models.BaseModel):
                raise UserError(_("attachment mapping does not support Odoo record values yet."))
            return "[]"
        if self.dingding_field_type == "date":
            user_tz = (self.env.user.tz or "UTC").strip() or "UTC"
            tz = pytz.timezone(user_tz)
            if isinstance(record_value, datetime):
                dt_utc = record_value
                if dt_utc.tzinfo is None:
                    dt_utc = pytz.utc.localize(dt_utc)
                dt_local = dt_utc.astimezone(tz)
                return dt_local.strftime("%Y-%m-%d")
            if isinstance(record_value, date):
                return record_value.strftime("%Y-%m-%d")
            if isinstance(record_value, str) and len(record_value) >= 10:
                return record_value[:10]
        if self.dingding_field_type in ("number", "money"):
            if isinstance(record_value, (int, float)):
                return record_value
            if isinstance(record_value, str):
                try:
                    return float(record_value)
                except Exception:
                    return record_value
        return self._stringify_record_value(record_value)

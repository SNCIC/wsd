# -*- coding: utf-8 -*-

import json
import logging
from datetime import datetime, timezone

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class SnWsdDingApprovalInstance(models.Model):
    _name = "sn.wsd.ding.approval.instance"
    _description = "DingTalk Approval Instance"
    _order = "id desc"

    config_id = fields.Many2one("sn.wsd.ding.approval.config", required=True, ondelete="restrict")
    process_instance_id = fields.Char(string="Process Instance ID", required=True, index=True)
    status = fields.Char(readonly=True)
    start_time = fields.Datetime(string="Start Time", readonly=True)
    end_time = fields.Datetime(string="End Time", readonly=True)

    initiator_user_id = fields.Many2one("res.users", string="Initiator", readonly=True)
    res_model = fields.Char(string="Related Model", index=True, readonly=True)
    res_id = fields.Integer(string="Related Record ID", index=True, readonly=True)
    res_name = fields.Char(string="Related Record Name", compute="_compute_res_name", store=False, readonly=True)

    raw_response = fields.Text(readonly=True)
    last_sync_at = fields.Datetime(string="Last Synced At", readonly=True, copy=False)
    last_sync_error = fields.Text(string="Last Sync Error", readonly=True, copy=False)

    log_ids = fields.One2many(
        "sn.wsd.ding.approval.instance.log",
        "instance_id",
        string="Approval Logs",
        readonly=True,
        copy=False,
    )

    @staticmethod
    def _extract_status(payload):
        result = (payload or {}).get("result") or {}
        process_instance = (
            payload.get("processInstance")
            or payload.get("process_instance")
            or result.get("process_instance")
            or {}
        )
        return (
            result.get("status")
            or result.get("instance_status")
            or (process_instance.get("status") if isinstance(process_instance, dict) else "")
            or (process_instance.get("instanceStatus") if isinstance(process_instance, dict) else "")
            or (payload or {}).get("status")
            or (payload or {}).get("instanceStatus")
            or ""
        )

    @staticmethod
    def _ms_to_datetime(value):
        """
        Backward-compatible datetime parser.

        DingTalk APIs may return timestamps in milliseconds/seconds or ISO-8601 strings (e.g. 2025-12-26T08:24Z).
        Returns a naive UTC datetime for Odoo fields.Datetime.
        """
        if value in (None, "", False):
            return False

        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc)
            return dt.replace(tzinfo=None)

        if isinstance(value, (int, float)):
            ms = int(value)
        else:
            s = str(value).strip()
            if not s:
                return False
            try:
                ms = int(s)
            except Exception:
                ms = None
            if ms is None:
                # ISO8601 string: 2025-12-26T08:24Z / 2025-12-26T08:24:00+08:00 / 2025-12-26
                try:
                    iso = s[:-1] + "+00:00" if s.endswith("Z") else s
                    dt = datetime.fromisoformat(iso)
                    if dt.tzinfo:
                        dt = dt.astimezone(timezone.utc)
                    return dt.replace(tzinfo=None)
                except Exception:
                    try:
                        dt = datetime.strptime(s[:10], "%Y-%m-%d")
                        return dt
                    except Exception:
                        return False

        if ms <= 0:
            return False
        seconds = ms if ms < 10_000_000_000 else (ms / 1000.0)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)

    @classmethod
    def _extract_meta(cls, payload):
        result = (payload or {}).get("result") or {}
        status = cls._extract_status(payload)
        process_instance = (
            payload.get("processInstance")
            or payload.get("process_instance")
            or result.get("process_instance")
            or {}
        )
        start_time = cls._ms_to_datetime(
            result.get("create_time")
            or result.get("start_time")
            or result.get("createTime")
            or result.get("startTime")
            or (process_instance.get("create_time") if isinstance(process_instance, dict) else None)
            or (process_instance.get("createTime") if isinstance(process_instance, dict) else None)
            or (process_instance.get("start_time") if isinstance(process_instance, dict) else None)
            or (process_instance.get("startTime") if isinstance(process_instance, dict) else None)
        )
        end_time = cls._ms_to_datetime(
            result.get("finish_time")
            or result.get("end_time")
            or result.get("finishTime")
            or result.get("endTime")
            or (process_instance.get("finish_time") if isinstance(process_instance, dict) else None)
            or (process_instance.get("finishTime") if isinstance(process_instance, dict) else None)
            or (process_instance.get("end_time") if isinstance(process_instance, dict) else None)
            or (process_instance.get("endTime") if isinstance(process_instance, dict) else None)
        )
        return {
            "status": status,
            "start_time": start_time,
            "end_time": end_time,
        }

    @api.depends("res_model", "res_id")
    def _compute_res_name(self):
        for rec in self:
            rec.res_name = ""
            if not rec.res_model or not rec.res_id:
                continue
            try:
                record = rec.env[rec.res_model].sudo().browse(rec.res_id)
            except Exception:
                continue
            if record.exists():
                rec.res_name = record.display_name or ""

    def _resolve_dingding_user_name(self, user_id):
        client = self.env["sn.wsd.ding.client"]
        return client.get_user_name_by_id(user_id) or user_id

    def _sync_logs_from_payload(self, payload):
        self.ensure_one()
        result = (payload or {}).get("result") or {}
        operations = (
            result.get("operation_records")
            or result.get("operation_records_v2")
            or result.get("operationRecords")
            or (payload.get("operationRecords") if isinstance(payload, dict) else None)
            or []
        )
        tasks = (
            result.get("tasks")
            or result.get("task_list")
            or result.get("taskList")
            or (payload.get("tasks") if isinstance(payload, dict) else None)
            or []
        )

        self.sudo().log_ids.unlink()

        logs = []
        seq = 10
        source = operations if isinstance(operations, list) and operations else tasks
        for op in source:
            if not isinstance(op, dict):
                continue
            user_id = (
                op.get("userId")
                or op.get("userid")
                or op.get("user_id")
                or op.get("operator_userid")
                or op.get("operatorUserId")
                or ""
            )
            user_id = (user_id or "").strip()
            logs.append(
                {
                    "sequence": seq,
                    "node_name": op.get("showName")
                    or op.get("activity_name")
                    or op.get("activityName")
                    or op.get("activityId")
                    or op.get("activity_id")
                    or op.get("title")
                    or op.get("node_name")
                    or op.get("nodeName")
                    or "Approval",
                    "approver_user_id": user_id,
                    "approver_name": "",
                    "result": op.get("operation_result") or op.get("result") or op.get("status") or "",
                    "comment": op.get("remark") or op.get("comment") or "",
                    "action_time": self._ms_to_datetime(
                        op.get("date")
                        or op.get("operate_time")
                        or op.get("operateTime")
                        or op.get("timestamp")
                        or op.get("createTime")
                        or op.get("finishTime")
                    ),
                    "raw_type": op.get("type") or op.get("operation_type") or "",
                }
            )
            seq += 10

        name_cache = {}
        for l in logs:
            uid = (l.get("approver_user_id") or "").strip()
            if uid and uid not in name_cache:
                try:
                    name_cache[uid] = self._resolve_dingding_user_name(uid)
                except Exception:
                    _logger.exception("Resolve approver name failed: instance=%s user_id=%s", self.process_instance_id, uid)
                    name_cache[uid] = uid
            l["approver_name"] = name_cache.get(uid) if uid else ""

        if logs:
            self.env["sn.wsd.ding.approval.instance.log"].sudo().create(
                [{"instance_id": self.id, **vals} for vals in logs]
            )
        _logger.info(
            "DingTalk instance logs synced: instance=%s ops=%s logs=%s",
            self.process_instance_id,
            len(operations) if isinstance(operations, list) else 0,
            len(logs),
        )

    def _refresh_from_dingding(self):
        for rec in self:
            try:
                payload = self.env["sn.wsd.ding.client"].get_process_instance(rec.process_instance_id)
                meta = self._extract_meta(payload)
                rec.status = meta.get("status") or rec.status
                rec.start_time = meta.get("start_time") or rec.start_time
                rec.end_time = meta.get("end_time") or False

                originator_user_id = ""
                try:
                    result = (payload or {}).get("result") or {}
                    originator_user_id = (
                        result.get("originator_user_id")
                        or result.get("originatorUserId")
                        or (payload.get("originatorUserId") if isinstance(payload, dict) else None)
                        or ""
                    )
                    originator_user_id = (originator_user_id or "").strip()
                except Exception:
                    originator_user_id = ""
                if originator_user_id and not rec.initiator_user_id:
                    user = rec.env["res.users"].sudo().search([("dingding_user_id", "=", originator_user_id)], limit=1)
                    if user:
                        rec.initiator_user_id = user.id

                rec.raw_response = json.dumps(payload, ensure_ascii=False, indent=2)
                try:
                    rec._sync_logs_from_payload(payload)
                except Exception:
                    _logger.exception("DingTalk instance logs sync failed: instance=%s", rec.process_instance_id)
                rec.last_sync_at = fields.Datetime.now()
                rec.last_sync_error = False
            except Exception as e:
                rec.last_sync_at = fields.Datetime.now()
                rec.last_sync_error = str(e)

    def action_open_related_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "target": "current",
        }

    def action_refresh_status(self):
        self._refresh_from_dingding()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": _("Approval instance refreshed."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_refresh_status_batch(self):
        self._refresh_from_dingding()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": _("Selected approval instances refreshed."),
                "type": "success",
                "sticky": False,
            },
        }


class SnWsdDingApprovalInstanceLog(models.Model):
    _name = "sn.wsd.ding.approval.instance.log"
    _description = "DingTalk Approval Instance Log"
    _order = "sequence,id"

    instance_id = fields.Many2one("sn.wsd.ding.approval.instance", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    node_name = fields.Char(string="Node", readonly=True)
    approver_name = fields.Char(string="Approver", readonly=True)
    approver_user_id = fields.Char(string="User ID", readonly=True)
    result = fields.Char(string="Result", readonly=True)
    comment = fields.Text(string="Comment", readonly=True)
    action_time = fields.Datetime(string="Action Time", readonly=True)
    raw_type = fields.Char(string="Raw Type", readonly=True)

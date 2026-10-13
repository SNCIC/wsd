# -*- coding: utf-8 -*-

import json
import logging
import os
import sys
import threading
import time

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_PREFIX = "sn_wsd_kingdee"

# The Kingdee WebAPI SDK ships as a local wheel inside this module (it is not
# published on PyPI):
#   <this module>/SDK_Python3.0_V8.2.0/python_sdk_v8.2.0/kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl
# It is imported lazily so this module stays installable and configurable before
# the wheel is deployed on the server. Note the wheel's distribution name
# (kingdee.cdp.webapi.sdk) differs from the package it installs
# (k3cloud_webapi_sdk), so `pip show` is not a valid check.
SDK_WHEEL_RELATIVE_PATH = (
    "SDK_Python3.0_V8.2.0/python_sdk_v8.2.0/"
    "kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl"
)
MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sdk_wheel_path():
    """Absolute path of the wheel shipped with this module."""
    return os.path.normpath(os.path.join(MODULE_ROOT, SDK_WHEEL_RELATIVE_PATH))


def sdk_install_hint():
    """Copy-pasteable install command for the interpreter that runs Odoo.

    Installing into another environment is the usual reason for the missing
    SDK, so the hint names ``sys.executable`` and the wheel of this module
    instead of a relative path that only makes sense on a developer machine.
    """
    executable = '"%s"' % sys.executable
    wheel = sdk_wheel_path()
    if os.path.isfile(wheel):
        return '%s -m pip install "%s"' % (executable, wheel)
    return '%s -m pip install <path to %s>  (the wheel is normally shipped in %s)' % (
        executable, os.path.basename(SDK_WHEEL_RELATIVE_PATH), MODULE_ROOT,
    )

REQUIRED_CONFIG = (
    ("server_url", "Server URL"),
    ("acct_id", "Account ID"),
    ("user_name", "User Name"),
    ("app_id", "App ID"),
    ("app_secret", "App Secret"),
)

# A Kingdee session (session cookie) belongs to one set of credentials, so SDK
# instances are cached per credential tuple. The lock protects the cache because
# Odoo serves requests from several threads.
_SDK_CACHE = {}
_SDK_CACHE_LOCK = threading.Lock()

# Payloads stored on the sync log are truncated to keep the table reasonable.
LOG_PAYLOAD_LIMIT = 20000


class SnWsdKingdeeClient(models.AbstractModel):
    """Thin, logged wrapper around the Kingdee ``k3cloud_webapi_sdk`` client."""

    _name = "sn.wsd.kingdee.client"
    _description = "Kingdee Cloud Galaxy WebAPI Client"

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _get_param(self, key, default=None):
        return self.env["ir.config_parameter"].sudo().get_param(
            "%s.%s" % (PARAM_PREFIX, key), default=default,
        )

    def _get_int_param(self, key, default=0):
        raw = self._get_param(key)
        try:
            return int(raw) if raw not in (None, "", False) else default
        except (TypeError, ValueError):
            _logger.warning("Invalid integer for parameter %s.%s: %r", PARAM_PREFIX, key, raw)
            return default

    def is_enabled(self):
        return bool(self._get_param("enabled"))

    def get_default_org(self, kind):
        """Return the default organization number used to create/use a material.

        :param str kind: either ``create`` or ``use``
        """
        if kind not in ("create", "use"):
            raise ValueError("kind must be 'create' or 'use'")
        value = (self._get_param("%s_org_number" % kind) or "").strip()
        if kind == "use" and not value:
            value = (self._get_param("create_org_number") or "").strip()
        return value

    def _get_config(self, override=None):
        config = {
            "server_url": (self._get_param("server_url") or "").strip(),
            "acct_id": (self._get_param("acct_id") or "").strip(),
            "user_name": (self._get_param("user_name") or "").strip(),
            "app_id": (self._get_param("app_id") or "").strip(),
            "app_secret": (self._get_param("app_secret") or "").strip(),
            "lcid": self._get_int_param("lcid", 2052) or 2052,
            "org_num": self._get_int_param("org_num", 0),
            "connect_timeout": self._get_int_param("connect_timeout", 120) or 120,
            "request_timeout": self._get_int_param("request_timeout", 120) or 120,
        }
        for key, value in (override or {}).items():
            if value not in (None, "", False):
                config[key] = value
        return config

    def _check_config(self, config):
        missing = [label for key, label in REQUIRED_CONFIG if not config.get(key)]
        if missing:
            raise UserError(
                _("Kingdee integration is not configured yet. Missing: %s") % ", ".join(missing)
            )
        return config

    # ------------------------------------------------------------------
    # SDK instance
    # ------------------------------------------------------------------
    def _get_sdk(self, override=None, force_refresh=False):
        try:
            from k3cloud_webapi_sdk.main import K3CloudApiSdk
        except ImportError as err:
            raise UserError(
                _(
                    "The Kingdee WebAPI SDK is not installed for the interpreter "
                    "running Odoo (%(error)s).\n"
                    "Install the wheel shipped with this module and restart Odoo:\n"
                    "%(hint)s"
                ) % {"error": err, "hint": sdk_install_hint()}
            ) from err

        config = self._check_config(self._get_config(override=override))
        cache_key = (
            config["server_url"], config["acct_id"], config["user_name"],
            config["app_id"], config["app_secret"], config["lcid"], config["org_num"],
        )
        with _SDK_CACHE_LOCK:
            sdk = None if force_refresh else _SDK_CACHE.get(cache_key)
            if sdk is None:
                sdk = K3CloudApiSdk(config["server_url"], timeout=config["request_timeout"])
                sdk.InitConfig(
                    config["acct_id"],
                    config["user_name"],
                    config["app_id"],
                    config["app_secret"],
                    config["server_url"],
                    lcid=config["lcid"],
                    org_num=config["org_num"],
                    connect_timeout=config["connect_timeout"],
                    request_timeout=config["request_timeout"],
                )
                if not sdk.initialize:
                    raise UserError(
                        _("The Kingdee SDK refused the configuration, please review the "
                          "credentials in Settings and check the server log.")
                    )
                _SDK_CACHE[cache_key] = sdk
            return sdk

    def clear_sdk_cache(self):
        """Drop every cached session, e.g. after the credentials were changed."""
        with _SDK_CACHE_LOCK:
            _SDK_CACHE.clear()

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _as_json(raw, api_name):
        """Decode the answer of the SDK.

        The SDK returns the response body as ``str``. On a few error paths it
        returns the exception instance instead of raising it, which is handled
        here so the caller always gets a usable error message.
        """
        if isinstance(raw, BaseException):
            raise UserError(_("Kingdee %(api)s failed: %(error)s") % {"api": api_name, "error": raw})
        if not isinstance(raw, str):
            raise UserError(
                _("Kingdee %(api)s returned an unexpected %(kind)s instead of a JSON string.")
                % {"api": api_name, "kind": type(raw).__name__}
            )
        text = raw.strip()
        if not text:
            raise UserError(_("Kingdee %(api)s returned an empty response.") % {"api": api_name})
        try:
            return json.loads(text)
        except ValueError:
            raise UserError(
                _("Kingdee %(api)s returned a non JSON response: %(body)s")
                % {"api": api_name, "body": text[:1000]}
            ) from None

    @staticmethod
    def _response_status(payload):
        """Return the ``ResponseStatus`` mapping of a dynamic form service answer.

        Most services answer ``{"Result": {"ResponseStatus": {...}}}``, a few put
        the flags directly under ``Result``. ``None`` is returned for the flat
        answers of the query services (``ExecuteBillQuery``, ``BillQuery``).
        """
        if not isinstance(payload, dict):
            return None
        result = payload.get("Result")
        if not isinstance(result, dict):
            return None
        status = result.get("ResponseStatus")
        if isinstance(status, dict):
            return status
        if "IsSuccess" in result:
            return result
        return None

    @staticmethod
    def _status_error(status):
        messages = []
        errors = status.get("Errors")
        if isinstance(errors, list):
            for error in errors:
                if not isinstance(error, dict):
                    continue
                message = error.get("Message") or error.get("FieldName") or ""
                if message:
                    messages.append(str(message))
        if not messages:
            messages.append(str(status.get("Message") or _("Unknown error")))
        return " | ".join(dict.fromkeys(messages))

    @classmethod
    def _check_success(cls, payload, api_name):
        status = cls._response_status(payload)
        if status is None:
            return payload
        is_success = status.get("IsSuccess")
        if is_success is None or is_success in (True, 1, "1", "true", "True"):
            return payload
        raise UserError(
            _("Kingdee %(api)s failed: %(message)s")
            % {"api": api_name, "message": cls._status_error(status)}
        )

    @staticmethod
    def get_result(payload):
        """Return the ``Result`` mapping of a dynamic form service answer."""
        if not isinstance(payload, dict):
            return {}
        result = payload.get("Result")
        return result if isinstance(result, dict) else {}

    @classmethod
    def get_response_data(cls, payload):
        """Return the first ``NeedReturnData`` mapping of a ``View`` answer."""
        inner = cls.get_result(payload).get("Result")
        if not isinstance(inner, dict):
            inner = cls.get_result(payload)
        data = inner.get("NeedReturnData")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return {}

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    @staticmethod
    def _dump(value, limit=LOG_PAYLOAD_LIMIT):
        if value in (None, False, ""):
            return False
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
            except (TypeError, ValueError):
                text = str(value)
        if len(text) > limit:
            text = text[:limit] + "\n... (truncated)"
        return text

    def _create_log(self, env, api_name, form_id, direction, success, error, payload,
                    request_payload, duration_ms, res_record):
        vals = {
            "api_name": api_name,
            "form_id": form_id or False,
            "direction": direction,
            "state": "success" if success else "error",
            "error_message": error or False,
            "request_payload": self._dump(request_payload),
            "response_payload": self._dump(payload),
            "duration_ms": duration_ms,
            "user_id": self.env.uid,
            "company_id": self.env.company.id,
        }
        if res_record:
            record = res_record[:1]
            vals["res_model"] = record._name
            vals["res_id"] = record.id
        env["sn.wsd.kingdee.sync.log"].create(vals)

    def _store_log(self, api_name, *, form_id=None, direction="out", success=True, error=None,
                   payload=None, request_payload=None, duration_ms=0, res_record=None,
                   force_new_cursor=False):
        """Store one call on the sync log.

        Failures are written through a dedicated cursor: the business error
        raised afterwards rolls the caller transaction back, and an error log
        that disappears with it would be useless.
        """
        if force_new_cursor:
            try:
                # The cursor context manager commits on a clean exit (odoo/orm/registry.py).
                with self.pool.cursor() as cr:
                    self._create_log(
                        self.env(cr=cr, su=True), api_name, form_id, direction, success,
                        error, payload, request_payload, duration_ms, res_record,
                    )
            except Exception:  # noqa: BLE001 - logging must never mask the original error
                _logger.exception("Unable to store the Kingdee sync log entry for %s", api_name)
            return
        try:
            self._create_log(
                self.env, api_name, form_id, direction, success, error, payload,
                request_payload, duration_ms, res_record,
            )
        except Exception:  # noqa: BLE001
            _logger.exception("Unable to store the Kingdee sync log entry for %s", api_name)

    # ------------------------------------------------------------------
    # Generic call
    # ------------------------------------------------------------------
    def _call(self, api_name, call, *, form_id=None, direction="out", res_record=None,
              request_payload=None):
        """Run one WebAPI call, store it on the sync log and validate the answer."""
        started = time.monotonic()

        def elapsed():
            return int((time.monotonic() - started) * 1000)

        try:
            raw = call()
        except UserError as err:
            self._store_log(
                api_name, form_id=form_id, direction=direction, success=False,
                error=str(err.args[0]) if err.args else str(err),
                request_payload=request_payload, duration_ms=elapsed(),
                res_record=res_record, force_new_cursor=True,
            )
            raise
        except Exception as err:  # noqa: BLE001 - transport errors from requests/urllib3
            self._store_log(
                api_name, form_id=form_id, direction=direction, success=False, error=str(err),
                request_payload=request_payload, duration_ms=elapsed(),
                res_record=res_record, force_new_cursor=True,
            )
            raise UserError(
                _("Kingdee %(api)s request failed: %(error)s") % {"api": api_name, "error": err}
            ) from err

        try:
            payload = self._as_json(raw, api_name)
            self._check_success(payload, api_name)
        except UserError as err:
            self._store_log(
                api_name, form_id=form_id, direction=direction, success=False,
                error=str(err.args[0]) if err.args else str(err),
                request_payload=request_payload, duration_ms=elapsed(),
                res_record=res_record, force_new_cursor=True,
            )
            raise

        self._store_log(
            api_name, form_id=form_id, direction=direction, success=True, payload=payload,
            request_payload=request_payload, duration_ms=elapsed(), res_record=res_record,
        )
        return payload

    # ------------------------------------------------------------------
    # Dynamic form services
    # ------------------------------------------------------------------
    def save(self, form_id, model, res_record=None, **options):
        """Create or update a bill. ``model`` holds the field values keyed by
        Kingdee field name, e.g. ``{"FNumber": "M001", "FName": "Bolt"}``."""
        payload = {
            "NeedUpDateFields": [],
            "NeedReturnFields": [],
            "IsDeleteEntry": "True",
            "SubSystemId": "",
            "IsVerifyBaseDataField": "False",
            "IsEntryBatchFill": "True",
            "ValidateFlag": "True",
            "NumberSearch": "True",
            "IsAutoAdjustField": "False",
            "InterationFlags": "",
            "IgnoreInterationFlag": "",
            "IsControlPrecision": "False",
            "Model": model,
        }
        payload.update(options)
        return self._call(
            "Save", lambda: self._get_sdk().Save(form_id, payload), form_id=form_id,
            res_record=res_record, request_payload=payload,
        )

    def batch_save(self, form_id, models, res_record=None, **options):
        payload = {
            "NumberSearch": "True",
            "ValidateFlag": "True",
            "IsDeleteEntry": "True",
            "IsEntryBatchFill": "True",
            "NeedUpDateFields": [],
            "NeedReturnFields": [],
            "SubSystemId": "",
            "InterationFlags": "",
            "Model": models,
            "BatchCount": 0,
            "IsVerifyBaseDataField": "False",
            "IsAutoAdjustField": "False",
            "IgnoreInterationFlag": "False",
            "IsControlPrecision": "False",
            "ValidateRepeatJson": "False",
        }
        payload.update(options)
        return self._call(
            "BatchSave", lambda: self._get_sdk().BatchSave(form_id, payload), form_id=form_id,
            res_record=res_record, request_payload=payload,
        )

    def bill_action(self, api_name, form_id, numbers=None, ids=None, res_record=None):
        """Run a workflow action: Submit, Audit, UnAudit or Delete."""
        if api_name not in ("Submit", "Audit", "UnAudit", "Delete"):
            raise ValueError("Unsupported bill action: %s" % api_name)
        payload = {
            "CreateOrgId": 0,
            "Numbers": numbers or [],
            "Ids": ids or "",
            "SelectedPostId": 0,
            "NetworkCtrl": "",
            "IgnoreInterationFlag": "",
        }
        if api_name == "Audit":
            payload["IsVerifyProcInst"] = ""
        return self._call(
            api_name, lambda: getattr(self._get_sdk(), api_name)(form_id, payload),
            form_id=form_id, res_record=res_record, request_payload=payload,
        )

    def view(self, form_id, number=None, record_id=None, create_org_id=0, is_sort_by_seq="false"):
        payload = {
            "CreateOrgId": create_org_id,
            "Number": number or "",
            "Id": record_id or "",
            "IsSortBySeq": is_sort_by_seq,
        }
        return self._call(
            "View", lambda: self._get_sdk().View(form_id, payload), form_id=form_id,
            direction="in", request_payload=payload,
        )

    def execute_bill_query(self, form_id, field_keys, filter_string="", order_string="",
                           top_row_count=0, start_row=0, limit=2000, sub_system_id=""):
        """Paged query. Returns a list of rows, each row being a list of values
        ordered like ``field_keys``. Field names are not echoed back."""
        payload = {
            "FormId": form_id,
            "FieldKeys": field_keys,
            "FilterString": filter_string,
            "OrderString": order_string,
            "TopRowCount": top_row_count,
            "StartRow": start_row,
            "Limit": limit,
            "SubSystemId": sub_system_id,
        }
        return self._call(
            "ExecuteBillQuery", lambda: self._get_sdk().ExecuteBillQuery(payload),
            form_id=form_id, direction="in", request_payload=payload,
        )

    def bill_query(self, form_id, field_keys, filter_string="", order_string="",
                   top_row_count=0, start_row=0, limit=2000, sub_system_id=""):
        """Paged query returning rows as mappings (field names included)."""
        payload = {
            "FormId": form_id,
            "FieldKeys": field_keys,
            "FilterString": filter_string,
            "OrderString": order_string,
            "TopRowCount": top_row_count,
            "StartRow": start_row,
            "Limit": limit,
            "SubSystemId": sub_system_id,
        }
        return self._call(
            "BillQuery", lambda: self._get_sdk().BillQuery(payload), form_id=form_id,
            direction="in", request_payload=payload,
        )

    def allocate(self, form_id, pk_ids, target_org_ids, auto_submit_audit="false", res_record=None):
        payload = {
            "PkIds": pk_ids,
            "TOrgIds": target_org_ids,
            "IsAutoSubmitAndAudit": auto_submit_audit,
        }
        return self._call(
            "Allocate", lambda: self._get_sdk().Allocate(form_id, payload), form_id=form_id,
            res_record=res_record, request_payload=payload,
        )

    def cancel_allocate(self, form_id, pk_ids, target_org_ids, res_record=None):
        payload = {"PkIds": pk_ids, "TOrgIds": target_org_ids}
        return self._call(
            "CancelAllocate", lambda: self._get_sdk().CancelAllocate(form_id, payload),
            form_id=form_id, res_record=res_record, request_payload=payload,
        )

    def get_sys_report_data(self, form_id, data):
        """Fetch a system report (account balance, stock report, ...).

        The report must already exist in Kingdee: its ``SchemeId`` is part of
        the request payload.
        """
        return self._call(
            "GetSysReportData", lambda: self._get_sdk().GetSysReportData(form_id, data),
            form_id=form_id, direction="in", request_payload=data,
        )

    def switch_org(self, org_number):
        """Switch the current organization of the session.

        Warning: this changes the state of the cached SDK session, therefore it
        also affects every other caller sharing the same credentials. Prefer
        setting the ``Organization Number`` parameter instead, which is applied
        when the session is created.
        """
        payload = {"OrgNumber": org_number}
        return self._call("SwitchOrg", lambda: self._get_sdk().SwitchOrg(payload),
                          request_payload=payload)

    def execute(self, service_name, data=None):
        """Call any Kingdee service that has no dedicated wrapper.

        :param str service_name: full service stub name, e.g.
            ``Kingdee.K3.SCM.WebApi.ServicesStub.StockReportQueryService.GetReportData,
            Kingdee.K3.SCM.WebApi.ServicesStub``
        """
        stub = service_name.split(",", 1)[0]
        return self._call(
            stub.rsplit(".", 1)[-1] or stub,
            lambda: self._get_sdk().Execute(service_name, data or {}),
            direction="in", request_payload=data,
        )

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------
    def test_connection(self, override=None):
        """Return the data centers declared for the configured account.

        Raises a ``UserError`` describing precisely what went wrong when the
        credentials, the URL or the SDK are not usable.
        """
        payload = self._call(
            "GetDataCenters",
            lambda: self._get_sdk(override=override, force_refresh=True).GetDataCenters(),
        )
        return payload

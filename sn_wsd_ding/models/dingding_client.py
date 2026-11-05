# -*- coding: utf-8 -*-

import logging
import time

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SnWsdDingClient(models.AbstractModel):
    _name = "sn.wsd.ding.client"
    _description = "DingTalk API Client"

    def _get_param(self, key, default=None):
        return self.env["ir.config_parameter"].sudo().get_param(key, default=default)

    def _set_param(self, key, value):
        return self.env["ir.config_parameter"].sudo().set_param(key, value)

    def _dingding_base_url(self):
        return "https://oapi.dingtalk.com"

    def _dingding_base_url_v1(self):
        return "https://api.dingtalk.com"

    def _workflow_sdk_client(self):
        try:
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_dingtalk.workflow_1_0 import client as workflow_client
        except Exception as e:
            raise UserError(_("Missing dependency alibabacloud_dingtalk: %s") % e)

        # Follow the official SDK sample: only set protocol + region_id, let the SDK pick endpoint.
        config = open_api_models.Config()
        config.protocol = "https"
        config.region_id = "central"
        return workflow_client.Client(config)

    def _get_app_credentials(self):
        app_key = (self._get_param("sn_wsd_ding.app_key") or "").strip()
        app_secret = (self._get_param("sn_wsd_ding.app_secret") or "").strip()
        if not app_key or not app_secret:
            raise UserError(_("Please configure DingTalk App Key and App Secret in Settings."))
        return app_key, app_secret

    def _get_app_uuid(self):
        app_uuid = (self._get_param("sn_wsd_ding.app_uuid") or "").strip()
        if not app_uuid:
            raise UserError(_("Please configure DingTalk App UUID in Settings."))
        return app_uuid

    def _get_app_uuid_optional(self):
        return (self._get_param("sn_wsd_ding.app_uuid") or "").strip() or ""

    def _access_token_cache_get(self):
        token = (self._get_param("sn_wsd_ding.access_token") or "").strip()
        expire_at = self._get_param("sn_wsd_ding.access_token_expire_at")
        try:
            expire_at = int(expire_at) if expire_at else 0
        except Exception:
            expire_at = 0
        return token, expire_at

    def _access_token_cache_set(self, token, expire_at):
        self._set_param("sn_wsd_ding.access_token", token or "")
        self._set_param("sn_wsd_ding.access_token_expire_at", str(int(expire_at or 0)))

    def _access_token_v1_cache_get(self):
        token = (self._get_param("sn_wsd_ding.access_token_v1") or "").strip()
        expire_at = self._get_param("sn_wsd_ding.access_token_v1_expire_at")
        try:
            expire_at = int(expire_at) if expire_at else 0
        except Exception:
            expire_at = 0
        return token, expire_at

    def _access_token_v1_cache_set(self, token, expire_at):
        self._set_param("sn_wsd_ding.access_token_v1", token or "")
        self._set_param("sn_wsd_ding.access_token_v1_expire_at", str(int(expire_at or 0)))

    def _request(self, method, url, *, params=None, json=None, timeout=20):
        try:
            resp = requests.request(method, url, params=params, json=json, timeout=timeout)
        except Exception as e:
            _logger.exception("DingTalk request error: %s %s", method, url)
            raise UserError(_("DingTalk request failed: %s") % (e,))
        try:
            payload = resp.json()
        except Exception:
            raise UserError(_("DingTalk response is not JSON (HTTP %s).") % resp.status_code)
        if resp.status_code >= 400:
            raise UserError(_("DingTalk HTTP error %s: %s") % (resp.status_code, payload))
        errcode = payload.get("errcode", 0)
        if errcode not in (0, "0", None):
            raise UserError(_("DingTalk API error: %(code)s %(msg)s") % {"code": errcode, "msg": payload.get("errmsg")})
        return payload

    def _request_v1(self, method, url, *, headers=None, params=None, json=None, timeout=20):
        try:
            resp = requests.request(method, url, headers=headers, params=params, json=json, timeout=timeout)
        except Exception as e:
            _logger.exception("DingTalk v1 request error: %s %s", method, url)
            raise UserError(_("DingTalk request failed: %s") % (e,))
        try:
            payload = resp.json()
        except Exception:
            raise UserError(_("DingTalk response is not JSON (HTTP %s).") % resp.status_code)
        if resp.status_code >= 400:
            raise UserError(_("DingTalk HTTP error %s: %s") % (resp.status_code, payload))
        code = payload.get("code")
        if code not in (None, "0", 0):
            raise UserError(_("DingTalk API error: %(code)s %(msg)s") % {"code": code, "msg": payload.get("message")})
        return payload

    def get_access_token(self, *, force_refresh=False):
        token, expire_at = self._access_token_cache_get()
        now = int(time.time())
        if token and expire_at and now < (expire_at - 60) and not force_refresh:
            return token

        app_key, app_secret = self._get_app_credentials()
        url = f"{self._dingding_base_url()}/gettoken"
        payload = self._request("GET", url, params={"appkey": app_key, "appsecret": app_secret})
        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 0) or 0)
        if not token or not expires_in:
            raise UserError(_("Failed to get DingTalk access_token."))
        self._access_token_cache_set(token, now + expires_in)
        return token

    def get_access_token_v1(self, *, force_refresh=False):
        token, expire_at = self._access_token_v1_cache_get()
        now = int(time.time())
        if token and expire_at and now < (expire_at - 60) and not force_refresh:
            return token

        app_key, app_secret = self._get_app_credentials()
        url = f"{self._dingding_base_url_v1()}/v1.0/oauth2/accessToken"
        payload = self._request_v1("POST", url, json={"appKey": app_key, "appSecret": app_secret})
        token = payload.get("accessToken") or payload.get("access_token")
        expires_in = int(payload.get("expireIn", 0) or payload.get("expires_in", 0) or 0)
        if not token or not expires_in:
            raise UserError(_("Failed to get DingTalk access_token."))
        self._access_token_v1_cache_set(token, now + expires_in)
        return token

    @api.model
    def normalize_mobile(self, mobile):
        mobile = (mobile or "").strip()
        if not mobile:
            return ""
        normalized = (
            mobile.replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        if normalized.startswith("00") and len(normalized) > 2:
            normalized = f"+{normalized[2:]}"
        if normalized.startswith("+"):
            return normalized
        digits = "".join(ch for ch in normalized if ch.isdigit())
        if len(digits) == 11:
            return f"+86{digits}"
        if digits.startswith("86") and len(digits) == 13:
            return f"+{digits}"
        return normalized

    def get_user_id_by_mobile(self, mobile):
        mobile = self.normalize_mobile(mobile)
        if not mobile:
            raise UserError(_("Mobile/Phone is empty."))

        token = self.get_access_token()
        url = f"{self._dingding_base_url()}/topapi/v2/user/getbymobile"
        payload = self._request("POST", url, params={"access_token": token}, json={"mobile": mobile})

        result = payload.get("result") or {}
        user_id = result.get("userid") or result.get("user_id")
        if not user_id:
            raise UserError(_("DingTalk user not found for mobile: %s") % mobile)
        return user_id

    def get_user_name_by_id(self, user_id):
        user_id = (user_id or "").strip()
        if not user_id:
            return ""
        token = self.get_access_token()
        url = f"{self._dingding_base_url()}/topapi/v2/user/get"
        payload = self._request("POST", url, params={"access_token": token}, json={"userid": user_id})
        result = payload.get("result") or {}
        return (result.get("name") or result.get("nick") or "").strip()

    def get_user_dept_ids(self, user_id):
        user_id = (user_id or "").strip()
        if not user_id:
            return []
        token = self.get_access_token()
        url = f"{self._dingding_base_url()}/topapi/v2/user/get"
        payload = self._request("POST", url, params={"access_token": token}, json={"userid": user_id})
        result = payload.get("result") or {}
        dept_ids = result.get("dept_id_list") or result.get("dept_id") or []
        if isinstance(dept_ids, (int, str)):
            dept_ids = [dept_ids]
        cleaned = []
        for d in dept_ids:
            try:
                cleaned.append(int(d))
            except Exception:
                continue
        return cleaned

    def get_user_primary_dept_id(self, user_id):
        dept_ids = self.get_user_dept_ids(user_id)
        return dept_ids[0] if dept_ids else None

    def get_agent_id(self):
        agent_id = (self._get_param("sn_wsd_ding.agent_id") or "").strip()
        return agent_id

    def get_app_uuid(self):
        return self._get_app_uuid()

    def get_app_uuid_optional(self):
        return self._get_app_uuid_optional()

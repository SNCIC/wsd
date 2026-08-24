# -*- coding: utf-8 -*-

import base64
import hashlib
import json
import logging
import secrets
import string
import time

from odoo import fields, http
from odoo.http import request

try:
    from ..scripts.DingCallbackCrypto3 import DingCallbackCrypto3 as DingCallbackCrypto3Official
except Exception:
    DingCallbackCrypto3Official = None

_logger = logging.getLogger(__name__)


class SnWsdDingApprovalWebhookController(http.Controller):
    @http.route(
        "/sn/wsd/ding/approval/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def dingding_approval_webhook(self, **kwargs):
        payload_bytes = request.httprequest.get_data() or b""
        try:
            payload_dict = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            _logger.warning("DingTalk webhook invalid JSON: body=%r", payload_bytes[:2000])
            return self._json({"msg": "invalid_json"}, status=400)

        is_encrypted = bool(payload_dict.get("encrypt"))

        # DingTalk puts signature fields in query string, not in JSON body.
        # Merge them into payload_dict so downstream validation can work.
        query_params = self._query_params()
        for k in ("signature", "msg_signature", "msgSignature", "timestamp", "timeStamp", "nonce"):
            if k in query_params and k not in payload_dict:
                payload_dict[k] = query_params[k]

        icp = request.env["ir.config_parameter"].sudo()
        callback_token = (icp.get_param("sn_wsd_ding.callback_token") or "").strip()
        aes_key = (icp.get_param("sn_wsd_ding.callback_aes_key") or "").strip()
        owner_key = (icp.get_param("sn_wsd_ding.callback_owner_key") or "").strip()
        fallback_owner_key = (icp.get_param("sn_wsd_ding.app_key") or "").strip()

        try:
            plaintext_dict, crypto = self._decode_dingding_callback(
                payload_dict,
                callback_token,
                aes_key,
                owner_key=owner_key,
                fallback_owner_key=fallback_owner_key,
            )
        except Exception as e:
            _logger.exception("DingTalk webhook decode failed")
            return self._json({"msg": "decode_failed", "error": str(e)}, status=400)

        event_type = self._find_first(plaintext_dict, ("EventType", "event_type", "type")) or ""
        if event_type in ("check_url", "url_verification"):
            # DingTalk callback check expects an encrypted "success" response when encryption is enabled.
            return self._success_response(crypto, encrypted=is_encrypted)

        instance_id = self._find_first(plaintext_dict, ("processInstanceId", "process_instance_id", "instance_id"))
        status = self._find_first(plaintext_dict, ("result", "status", "instance_status"))

        if not instance_id:
            return self._success_response(crypto, encrypted=is_encrypted)

        inst = request.env["sn.wsd.ding.approval.instance"].sudo().search(
            [("process_instance_id", "=", instance_id)], limit=1
        )
        if not inst:
            return self._success_response(crypto, encrypted=is_encrypted)

        values = {
            "raw_response": json.dumps(plaintext_dict, ensure_ascii=False, indent=2),
            "last_sync_at": fields.Datetime.now(),
            "last_sync_error": False,
        }
        if status:
            values["status"] = status
        inst.write(values)

        try:
            inst._refresh_from_dingding()
        except Exception:
            _logger.exception("DingTalk webhook refresh failed: instance=%s event_type=%s", instance_id, event_type)

        _logger.info("DingTalk webhook processed instance=%s status=%s event_type=%s", instance_id, status, event_type)
        return self._success_response(crypto, encrypted=is_encrypted)

    @staticmethod
    def _json(payload, status=200):
        resp = request.make_json_response(payload)
        resp.status_code = status
        return resp

    @staticmethod
    def _find_first(obj, keys):
        if isinstance(obj, dict):
            for k in keys:
                if k in obj and obj[k] not in (None, ""):
                    return obj[k]
            for v in obj.values():
                found = SnWsdDingApprovalWebhookController._find_first(v, keys)
                if found not in (None, ""):
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = SnWsdDingApprovalWebhookController._find_first(v, keys)
                if found not in (None, ""):
                    return found
        return None

    @staticmethod
    def _query_params():
        try:
            args = request.httprequest.args
        except Exception:
            return {}
        return {k: args.get(k) for k in args.keys()}

    @staticmethod
    def _decode_dingding_callback(payload_dict, callback_token, aes_key, *, owner_key: str, fallback_owner_key: str):
        encrypt = payload_dict.get("encrypt")
        if encrypt:
            if not aes_key:
                raise ValueError("callback_aes_key not configured for encrypted DingTalk callbacks")
            if not callback_token:
                raise ValueError("callback_token not configured for encrypted DingTalk callbacks")
            if DingCallbackCrypto3Official is None:
                raise RuntimeError("missing dependency or import error: scripts.DingCallbackCrypto3 (pycryptodome)")

            msg_signature = payload_dict.get("msg_signature") or payload_dict.get("msgSignature") or payload_dict.get("signature") or ""
            timestamp = payload_dict.get("timeStamp") or payload_dict.get("timestamp") or payload_dict.get("time_stamp") or ""
            nonce = payload_dict.get("nonce") or ""
            if not msg_signature or not timestamp or not nonce:
                raise ValueError("missing signature params (msg_signature/timestamp/nonce)")

            candidates = []
            if owner_key:
                candidates.extend([k.strip() for k in owner_key.replace(";", ",").split(",") if k.strip()])
            if fallback_owner_key and fallback_owner_key not in candidates:
                candidates.append(fallback_owner_key)
            if not candidates:
                raise ValueError(
                    "missing callback_owner_key: set ir.config_parameter sn_wsd_ding.callback_owner_key "
                    "(corpId/appKey/suiteKey depending on your DingTalk callback type)"
                )

            last_error = None
            for k in candidates:
                try:
                    crypto = DingCallbackCrypto3Official(callback_token, aes_key, k)
                    plaintext = crypto.getDecryptMsg(msg_signature, str(timestamp), str(nonce), encrypt)
                    return json.loads(plaintext), crypto
                except Exception as e:
                    last_error = e
                    continue
            raise ValueError(f"decrypt failed with all owner_key candidates: {last_error}")
        return payload_dict, None

    @staticmethod
    def _success_response(crypto, *, encrypted: bool):
        if not encrypted:
            return SnWsdDingApprovalWebhookController._json({"msg": "success"})
        if crypto is None:
            return SnWsdDingApprovalWebhookController._json(
                {"msg": "crypto_not_ready"},
                status=500,
            )

        # Follow the official Java implementation (important):
        # the "official" Python demo in scripts/DingCallbackCrypto3.py uses string decode/encode for the 4-byte length,
        # which can corrupt the message layout and cause DingTalk to fail validating the response fields.
        # Here we build the encrypted response strictly as Java does:
        # random(16 bytes) + msg_len(4 bytes big-endian) + plaintext + owner_key + pkcs7(32) padding, then AES-CBC.
        timestamp = str(int(time.time() * 1000))
        alphabet = string.ascii_letters + string.digits
        nonce = "".join(secrets.choice(alphabet) for _ in range(16))

        encrypt = SnWsdDingApprovalWebhookController._encrypt_java_style(
            encoding_aes_key=getattr(crypto, "encodingAesKey", ""),
            owner_key=getattr(crypto, "key", ""),
            plaintext="success",
        )

        msg_signature = hashlib.sha1(
            "".join(sorted([str(crypto.token), str(timestamp), str(nonce), str(encrypt)])).encode("utf-8")
        ).hexdigest()

        return SnWsdDingApprovalWebhookController._json(
            {"msg_signature": msg_signature, "encrypt": encrypt, "timeStamp": timestamp, "nonce": nonce}
        )

    @staticmethod
    def _pkcs7_pad_32(data: bytes) -> bytes:
        pad_len = 32 - (len(data) % 32)
        if pad_len == 0:
            pad_len = 32
        return data + bytes([pad_len]) * pad_len

    @staticmethod
    def _encrypt_java_style(*, encoding_aes_key: str, owner_key: str, plaintext: str) -> str:
        """
        Build encrypt exactly like the official Java implementation:
        random(16) + msg_len(4 bytes BE) + msg + owner_key + pkcs7(32), then AES-256-CBC, then base64.
        """
        if not encoding_aes_key:
            raise ValueError("missing encoding_aes_key")
        if not owner_key:
            raise ValueError("missing owner_key")
        pad = "=" * (-len(encoding_aes_key) % 4)
        aes_key = base64.b64decode((encoding_aes_key + pad).encode("utf-8"))
        iv = aes_key[:16]

        msg = (plaintext or "").encode("utf-8")
        owner = owner_key.encode("utf-8")
        alphabet = string.ascii_letters + string.digits
        random16 = "".join(secrets.choice(alphabet) for _ in range(16)).encode("utf-8")
        raw = random16 + len(msg).to_bytes(4, "big") + msg + owner
        padded = SnWsdDingApprovalWebhookController._pkcs7_pad_32(raw)

        # Prefer pycryptodome (Crypto) if available because the official script depends on it.
        try:
            from Crypto.Cipher import AES as _AES  # type: ignore

            cipher = _AES.new(aes_key, _AES.MODE_CBC, iv)
            ciphertext = cipher.encrypt(padded)
        except Exception:
            try:
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            except Exception as e:
                raise RuntimeError("missing dependency: Crypto or cryptography") from e

            encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).encryptor()
            ciphertext = encryptor.update(padded) + encryptor.finalize()

        return base64.b64encode(ciphertext).decode("utf-8")

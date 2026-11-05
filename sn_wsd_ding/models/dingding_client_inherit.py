# -*- coding: utf-8 -*-

import json
import logging

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SnWsdDingClient(models.AbstractModel):
    _inherit = "sn.wsd.ding.client"

    def _workflow_sdk_headers(self, headers_cls):
        headers = headers_cls()
        headers.x_acs_dingtalk_access_token = self.get_access_token_v1()
        return headers

    def _workflow_sdk_form_values(self, form_component_values):
        from alibabacloud_dingtalk.workflow_1_0 import models as workflow_models

        items = []
        for item in form_component_values or []:
            if isinstance(item, workflow_models.StartProcessInstanceRequestFormComponentValues):
                items.append(item)
                continue
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            value = item.get("value")
            if value in (None, False):
                value = ""
            elif isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, ensure_ascii=False)
            else:
                value = str(value)
            items.append(workflow_models.StartProcessInstanceRequestFormComponentValues(name=name, value=value))
        return items

    def get_process_code_by_name(self, schema_name):
        schema_name = (schema_name or "").strip()
        if not schema_name:
            return ""
        from alibabacloud_dingtalk.workflow_1_0 import models as workflow_models
        from alibabacloud_tea_util import models as util_models

        client = self._workflow_sdk_client()
        request = workflow_models.GetProcessCodeByNameRequest(name=schema_name)
        headers = self._workflow_sdk_headers(workflow_models.GetProcessCodeByNameHeaders)
        response = client.get_process_code_by_name_with_options(request, headers, util_models.RuntimeOptions())
        if response and response.body and response.body.result:
            return (response.body.result.process_code or "").strip()
        return ""

    def get_process_definition(self, process_code):
        process_code = (process_code or "").strip()
        if not process_code:
            return {}
        from alibabacloud_dingtalk.workflow_1_0 import models as workflow_models
        from alibabacloud_tea_util import models as util_models

        client = self._workflow_sdk_client()
        runtime = util_models.RuntimeOptions()

        app_uuid = self.get_app_uuid_optional()
        first_error = None
        first_error_type = None

        if app_uuid:
            try:
                request = workflow_models.QuerySchemaByProcessCodeRequest(
                    app_uuid=app_uuid,
                    process_code=process_code,
                )
                headers = self._workflow_sdk_headers(workflow_models.QuerySchemaByProcessCodeHeaders)
                response = client.query_schema_by_process_code_with_options(request, headers, runtime)
                if response and response.body:
                    return response.body.to_map()
            except Exception as e:
                first_error = e
                first_error_type = "QuerySchemaByProcessCode"
                # Common in real tenants: process_code not under this app_uuid -> formNotExist.
                if "formNotExist" not in str(e):
                    _logger.exception(
                        "DingTalk query_schema_by_process_code failed: process_code=%s app_uuid=%s",
                        process_code,
                        app_uuid,
                    )

        # Fallback: query schema+process config by process_code only (single query)
        try:
            request = workflow_models.QuerySchemaAndProcessRequest(process_code=process_code)
            headers = self._workflow_sdk_headers(workflow_models.QuerySchemaAndProcessHeaders)
            response = client.query_schema_and_process_with_options(request, headers, runtime)
            if response and response.body:
                return response.body.to_map()
        except Exception as e:
            last_error = e
            last_error_type = "QuerySchemaAndProcess"
            _logger.exception("DingTalk query_schema_and_process failed: process_code=%s", process_code)

        details = []
        if first_error is not None:
            details.append(f"{first_error_type}: {first_error}")
        if last_error is not None and (last_error is not first_error):
            details.append(f"{last_error_type}: {last_error}")
        if not details:
            details.append("unknown error")

        raise UserError(
            _(
                "Failed to get DingTalk form schema via v1.0 SDK (process_code=%(code)s, app_uuid=%(app)s).\n%(details)s"
            )
            % {"code": process_code, "app": app_uuid or "-", "details": "\n".join(details)}
        )

    def create_process_instance(self, *, process_code, originator_user_id, form_component_values, dept_id=None):
        process_code = (process_code or "").strip()
        originator_user_id = (originator_user_id or "").strip()
        if not process_code:
            raise UserError(_("DingTalk process_code is required."))
        if not originator_user_id:
            raise UserError(_("DingTalk originator_user_id is required."))
        if not form_component_values:
            raise UserError(_("DingTalk form_component_values is required."))

        try:
            agent_id = (self.get_agent_id() or "").strip()
            from alibabacloud_dingtalk.workflow_1_0 import models as workflow_models
            from alibabacloud_tea_util import models as util_models

            client = self._workflow_sdk_client()
            request = workflow_models.StartProcessInstanceRequest(
                process_code=process_code,
                originator_user_id=originator_user_id,
                form_component_values=self._workflow_sdk_form_values(form_component_values),
                microapp_agent_id=int(agent_id) if agent_id else None,
                dept_id=int(dept_id) if dept_id else None,
            )
            headers = self._workflow_sdk_headers(workflow_models.StartProcessInstanceHeaders)
            response = client.start_process_instance_with_options(request, headers, util_models.RuntimeOptions())
            instance_id = ""
            if response and response.body:
                instance_id = response.body.instance_id or ""
            return {
                "processInstanceId": instance_id,
                "instanceId": instance_id,
            }
        except Exception:
            token = self.get_access_token()
            url = f"{self._dingding_base_url()}/topapi/processinstance/create"
            body = {
                "process_code": process_code,
                "originator_user_id": originator_user_id,
                "form_component_values": form_component_values,
            }
            agent_id = (self.get_agent_id() or "").strip()
            if agent_id:
                body["agent_id"] = agent_id
            if dept_id:
                body["dept_id"] = int(dept_id)
            return self._request("POST", url, params={"access_token": token}, json=body)

    def get_process_instance(self, process_instance_id):
        process_instance_id = (process_instance_id or "").strip()
        if not process_instance_id:
            return {}
        try:
            from alibabacloud_dingtalk.workflow_1_0 import models as workflow_models
            from alibabacloud_tea_util import models as util_models

            client = self._workflow_sdk_client()
            request = workflow_models.GetProcessInstanceRequest(process_instance_id=process_instance_id)
            headers = self._workflow_sdk_headers(workflow_models.GetProcessInstanceHeaders)
            response = client.get_process_instance_with_options(request, headers, util_models.RuntimeOptions())
            if response and response.body:
                return response.body.to_map()
            return {}
        except Exception:
            token = self.get_access_token()
            url = f"{self._dingding_base_url()}/topapi/processinstance/get"
            return self._request("GET", url, params={"access_token": token, "process_instance_id": process_instance_id})

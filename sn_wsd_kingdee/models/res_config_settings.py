# -*- coding: utf-8 -*-

import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    kingdee_enabled = fields.Boolean(
        string="Scheduled Material Refresh",
        config_parameter="sn_wsd_kingdee.enabled",
        help="Allow the scheduled action to refresh the materials already linked to Kingdee.",
    )
    kingdee_server_url = fields.Char(
        string="Server URL",
        config_parameter="sn_wsd_kingdee.server_url",
        help="Kingdee K/3 Cloud base URL, it must end with /k3cloud/.",
    )
    kingdee_acct_id = fields.Char(
        string="Account ID",
        config_parameter="sn_wsd_kingdee.acct_id",
        help="Data center identifier (AcctID) of the third party login authorization.",
    )
    kingdee_user_name = fields.Char(
        string="User Name",
        config_parameter="sn_wsd_kingdee.user_name",
        help="Kingdee user granted for the WebAPI calls.",
    )
    kingdee_app_id = fields.Char(
        string="App ID",
        config_parameter="sn_wsd_kingdee.app_id",
    )
    kingdee_app_secret = fields.Char(
        string="App Secret",
        config_parameter="sn_wsd_kingdee.app_secret",
        help="Stored unencrypted in the system parameters, keep it restricted to administrators.",
    )
    kingdee_lcid = fields.Integer(
        string="Locale ID",
        config_parameter="sn_wsd_kingdee.lcid",
        default=2052,
        help="Account locale, 2052 for Simplified Chinese.",
    )
    kingdee_org_num = fields.Integer(
        string="Organization Number",
        config_parameter="sn_wsd_kingdee.org_num",
        default=0,
        help="Organization number, only relevant when multi-organization is enabled.",
    )
    kingdee_connect_timeout = fields.Integer(
        string="Connection Timeout (s)",
        config_parameter="sn_wsd_kingdee.connect_timeout",
        default=120,
    )
    kingdee_request_timeout = fields.Integer(
        string="Request Timeout (s)",
        config_parameter="sn_wsd_kingdee.request_timeout",
        default=120,
    )
    kingdee_create_org_number = fields.Char(
        string="Create Organization",
        config_parameter="sn_wsd_kingdee.create_org_number",
        help="Organization number (FCreateOrgId) used when a material is created in Kingdee.",
    )
    kingdee_use_org_number = fields.Char(
        string="Use Organization",
        config_parameter="sn_wsd_kingdee.use_org_number",
        help="Organization number (FUseOrgId) of the material. Defaults to the create organization.",
    )
    kingdee_unit_number = fields.Char(
        string="Material Unit",
        config_parameter="sn_wsd_kingdee.unit_number",
        help="Kingdee unit number (BD_UNIT, e.g. 001 or GE) applied to the base, store, "
             "purchase and sale unit fields of a material. It can be overridden on "
             "each product. Defaults to 001 when empty.",
    )

    def _kingdee_settings_config(self):
        """Return the credentials currently typed in the settings form."""
        self.ensure_one()
        return {
            "server_url": (self.kingdee_server_url or "").strip(),
            "acct_id": (self.kingdee_acct_id or "").strip(),
            "user_name": (self.kingdee_user_name or "").strip(),
            "app_id": (self.kingdee_app_id or "").strip(),
            "app_secret": (self.kingdee_app_secret or "").strip(),
            "lcid": self.kingdee_lcid or 2052,
            "org_num": self.kingdee_org_num or 0,
            "connect_timeout": self.kingdee_connect_timeout or 120,
            "request_timeout": self.kingdee_request_timeout or 120,
        }

    def action_kingdee_test_connection(self):
        """Check the WebAPI credentials without leaving the settings screen."""
        self.ensure_one()
        client = self.env["sn.wsd.kingdee.client"]
        try:
            # The form values are used directly: the settings may not be saved yet.
            payload = client.test_connection(override=self._kingdee_settings_config())
        except Exception as err:  # noqa: BLE001 - surfaced to the user as a notification
            _logger.warning("Kingdee connection test failed: %s", err)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "title": _("Kingdee"),
                    "message": str(err),
                    "sticky": True,
                },
            }

        if isinstance(payload, list):
            count = len(payload)
        elif isinstance(payload, dict):
            data = payload.get("Result")
            count = len(data) if isinstance(data, (list, dict)) else 0
        else:
            count = 0
        message = _("Connection succeeded.")
        if count:
            message = _("Connection succeeded. %s data center(s) returned.") % count
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Kingdee"),
                "message": message,
                "sticky": False,
            },
        }

    def action_kingdee_clear_cache(self):
        """Drop the cached Kingdee sessions, e.g. after rotating the app secret."""
        self.ensure_one()
        self.env["sn.wsd.kingdee.client"].clear_sdk_cache()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Kingdee"),
                "message": _("Cached Kingdee sessions cleared."),
                "sticky": False,
            },
        }

# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    dingding_app_key = fields.Char(string="DingTalk App Key", config_parameter="sn_wsd_ding.app_key")
    dingding_app_secret = fields.Char(string="DingTalk App Secret", config_parameter="sn_wsd_ding.app_secret")
    dingding_app_uuid = fields.Char(string="DingTalk App UUID", config_parameter="sn_wsd_ding.app_uuid")
    dingding_agent_id = fields.Char(string="DingTalk Agent ID", config_parameter="sn_wsd_ding.agent_id")

    dingding_callback_token = fields.Char(
        string="DingTalk Callback Token",
        config_parameter="sn_wsd_ding.callback_token",
        help="Used to verify DingTalk event callbacks (approval instance status change).",
    )
    dingding_callback_aes_key = fields.Char(
        string="DingTalk Callback AES Key",
        config_parameter="sn_wsd_ding.callback_aes_key",
        help="Used to decrypt/verify DingTalk event callbacks.",
    )

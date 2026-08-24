# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = "res.users"

    dingding_user_id = fields.Char(string="DingTalk User ID", readonly=True, copy=False, groups="base.group_system")

    def _sn_wsd_get_mobile_for_dingding(self):
        self.ensure_one()
        phone_value = ""
        if "mobile" in self._fields and self["mobile"]:
            phone_value = self["mobile"]
        elif "phone" in self._fields and self["phone"]:
            phone_value = self["phone"]
        elif self.partner_id:
            if "mobile" in self.partner_id._fields and self.partner_id["mobile"]:
                phone_value = self.partner_id["mobile"]
            elif "phone" in self.partner_id._fields and self.partner_id["phone"]:
                phone_value = self.partner_id["phone"]
        return self.env["sn.wsd.ding.client"].normalize_mobile(phone_value)

    def action_fetch_dingding_user_id(self):
        self.ensure_one()
        mobile = self._sn_wsd_get_mobile_for_dingding()
        if not mobile:
            raise UserError(_("Please set Mobile or Phone first."))
        user_id = self.env["sn.wsd.ding.client"].get_user_id_by_mobile(mobile)
        self.dingding_user_id = user_id
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": _("DingTalk user_id updated: %s") % user_id,
                "type": "success",
                "sticky": False,
            },
        }

    def action_fetch_dingding_user_ids_batch(self):
        updated = 0
        skipped = 0
        errors = []
        client = self.env["sn.wsd.ding.client"]

        for user in self:
            mobile = user._sn_wsd_get_mobile_for_dingding()
            if not mobile:
                skipped += 1
                continue
            try:
                user_id = client.get_user_id_by_mobile(mobile)
                user.dingding_user_id = user_id
                updated += 1
            except Exception as e:
                errors.append(f"{user.display_name}: {e}")

        msg_parts = [
            _("Updated: %s") % updated,
            _("Skipped(no phone): %s") % skipped,
            _("Errors: %s") % len(errors),
        ]
        if errors:
            preview = "\n".join(errors[:10])
            msg_parts.append(_("First errors:\n%s") % preview)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("DingTalk"),
                "message": "\n".join(msg_parts),
                "type": "warning" if errors else "success",
                "sticky": bool(errors),
            },
        }

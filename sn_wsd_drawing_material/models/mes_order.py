from odoo import models

from odoo.addons.sn_wsd_drawing_material.models.esop_document import (
    esop_bus_channel,
)


class MesOrder(models.Model):
    _inherit = 'sn.wsd.mes.order'

    def write(self, vals):
        result = super().write(vals)
        # 上线(state→in_progress)/下线(清 x_online_date)/完工/取消都会改到
        # 这两个字段之一；挂在写入层，任何入口的变化都不漏。
        if vals.keys() & {'state', 'x_online_date'}:
            for company in self.mapped('company_id'):
                self.env['bus.bus']._sendone(
                    esop_bus_channel(company.id), 'esop_refresh', True)
        return result

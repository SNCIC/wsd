# LOCAL PATCH #9：制令单甘特原来 color="state"，state 是字符串选择字段，getColorIndex() 对字符串一律返回 0 → 所有色块同色。
# 增加非存储整数字段 x_gantt_color 按状态映射 Odoo 色板序号，甘特视图改用该字段着色。
from odoo import api, fields, models

GANTT_STATE_COLORS = {'released': 8, 'picked': 2, 'in_progress': 10, 'done': 4, 'cancelled': 1}


class SnWsdMesOrderGanttColor(models.Model):
    _inherit = 'sn.wsd.mes.order'

    x_gantt_color = fields.Integer(string='Gantt Color', compute='_compute_x_gantt_color')

    @api.depends('state')
    def _compute_x_gantt_color(self):
        for order in self:
            order.x_gantt_color = GANTT_STATE_COLORS.get(order.state, 0)

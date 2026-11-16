from odoo import fields, models


class SnInjDefect(models.Model):
    """注塑缺陷代码（缩水、飞边、缺料、银纹…），报工按代码记不良。"""
    _name = 'sn.inj.defect'
    _description = '注塑缺陷代码'
    _order = 'sequence, code'

    sequence = fields.Integer(default=10)
    code = fields.Char(string='缺陷代码', required=True)
    name = fields.Char(string='缺陷名称', required=True)
    category = fields.Selection(
        [('appearance', '外观'), ('dimension', '尺寸'), ('function', '功能/结构')],
        string='类别', default='appearance', required=True)
    cause = fields.Char(string='常见原因')
    action = fields.Char(string='调机对策')
    active = fields.Boolean(default=True)

    _sn_inj_defect_code_unique = models.Constraint('unique(code)', '缺陷代码必须唯一。')

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s %s' % (rec.code, rec.name)

from odoo import fields, models


class MrpFeederLine(models.Model):
    _inherit = 'mrp.feeder.line'

    online_material_id = fields.Many2one(
        'sn.smt.online.material',
        string='SMT Online Material',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    device_seq = fields.Integer(string='Device Sequence')
    table_no = fields.Char(string='Table No')
    loadpoint = fields.Char(string='Loadpoint')
    chanel_sn = fields.Char(string='Channel')
    feeder_spec = fields.Char(string='Feeder Spec')
    is_tray = fields.Selection([('Y', 'Yes'), ('N', 'No')], string='Tray', default='N')

    _sn_smt_feeder_line_online_material_unique = models.Constraint(
        'unique(online_material_id)',
        'Each SMT online material position can only have one feeder verification line.',
    )

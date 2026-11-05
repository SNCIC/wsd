from odoo import _, fields, models


class OqcDispositionEventScrapLink(models.Model):
    """Scrap linkage on the OQC disposition event (oqc-disposition-closure
    task 6.2): the real scrap-reference is declared here in sn_wsd_scrap
    (which depends on quality), so the quality base model never references
    an uninstalled comodel -- the base snapshot already keeps the source
    identity, this field makes it a navigable link."""

    _inherit = 'sn.wsd.quality.oqc.disposition.event'

    scrap_record_id = fields.Many2one(
        'sn.wsd.scrap.record', string='Scrap Record',
        check_company=True, index=True, ondelete='restrict',
        help='Scrap record behind a scrap / scrap-restore event; opens the '
             'stock scrap and its reason from the disposition history.')

    def action_open_scrap_record(self):
        """处置历史行跳报废单（任务 7.3）：scrap 事件关联的既有报废单，
        从事件列表直接打开核对库存报废与原因。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Scrap Record'),
            'res_model': 'sn.wsd.scrap.record',
            'res_id': self.scrap_record_id.id,
            'view_mode': 'form',
        }

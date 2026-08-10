from odoo import fields, models, _
from odoo.exceptions import ValidationError


class SnSmtTableImportWizard(models.TransientModel):
    _name = 'sn.smt.table.import.wizard'
    _description = 'SMT Material Table Import Wizard'
    _inherit = 'sn.smt.table.import.mixin'

    table_id = fields.Many2one(
        'sn.smt.material.table',
        string='Material Table',
        required=True,
        check_company=True,
    )
    import_file = fields.Binary(string='CSV File', required=True)
    import_filename = fields.Char(string='Filename')
    clear_existing = fields.Boolean(string='Clear Existing Details', default=False)

    def action_import(self):
        self.ensure_one()
        rows = self._parse_import_file(self.import_file)
        if not rows:
            raise ValidationError(_('The import file is empty.'))
        if self.clear_existing:
            self.table_id.detail_ids.unlink()
        detail_model = self.env['sn.smt.material.table.detail']
        for row in rows:
            detail_model.create({
                'mt_id': self.table_id.id,
                'item_code': (row.get('ITEM_CODE') or '').strip(),
                'device_seq': int((row.get('DEVICE_SEQ') or '0').strip() or 0),
                'table_no': (row.get('TABLE_NO') or '').strip(),
                'loadpoint': (row.get('LOADPOINT') or '').strip(),
                'chanel_sn': (row.get('CHANEL_SN') or '').strip(),
                'point_qty': int((row.get('POINT_QTY') or '0').strip() or 0),
                'feeder_spec': (row.get('FEEDER_SPEC') or '').strip(),
                'is_tray': ((row.get('IS_TRAY') or 'N').strip() or 'N').upper(),
                'is_skip': ((row.get('IS_SKIP') or 'N').strip() or 'N').upper(),
                'track_type': (row.get('TRACK_TYPE') or self.table_id.track_type or 'single').strip() or 'single',
                'direction': (row.get('DIRECTION') or '').strip(),
                'point_location': (row.get('POINT_LOCATION') or '').strip(),
            })
        return {'type': 'ir.actions.act_window_close'}

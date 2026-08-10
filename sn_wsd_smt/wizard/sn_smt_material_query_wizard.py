from odoo import fields, models, _
from odoo.exceptions import UserError


class SnSmtMaterialQueryWizard(models.TransientModel):
    _name = 'sn.smt.material.query.wizard'
    _description = 'SMT Material Query Wizard'

    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        check_company=True,
    )
    material_sn_input = fields.Char(string='Material SN', required=True)
    result_text = fields.Text(string='Result', readonly=True)

    def action_query(self):
        self.ensure_one()
        if not self.production_id.x_smt_production_line_id:
            raise UserError(_('No manufacturing order is online for the current line.'))
        material_lot = self.env['stock.lot'].search([
            ('name', '=', self.material_sn_input),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.production_id.company_id.id),
        ], limit=1)
        if not material_lot:
            raise UserError(_('The material SN could not be resolved to a material item code.'))
        positions = self.production_id.x_smt_online_material_ids.filtered(
            lambda line: line.item_code == material_lot.product_id.default_code
        )
        if not positions:
            raise UserError(_('The material SN does not match the current online material table requirements.'))
        self.result_text = '\n'.join(
            f"{line.device_seq}.{line.table_no}-{line.loadpoint}-{line.chanel_sn or ''}"
            for line in positions.sorted(lambda item: (item.device_seq, item.table_no, item.loadpoint, item.id))
        )
        return True

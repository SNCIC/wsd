from odoo import api, fields, models


class SnLabelPrintLog(models.Model):
    """Audit trail: one line per printed record, whatever the channel
    (PC ZPL download or PDA CPCL fetch, design decision: print audit).

    Print channels write it server-side with sudo so regular users can
    print without write access on the audit model; they only read it.
    """

    _name = 'sn.label.print.log'
    _description = 'Label Print Log'
    _order = 'id desc'
    _rec_name = 'template_id'

    template_id = fields.Many2one(
        'sn.label.template', string='Template', required=True, index=True)
    res_model = fields.Char(string='Record Model', required=True, index=True)
    res_id = fields.Integer(string='Record ID', required=True)
    copies = fields.Integer(string='Copies', default=1)
    user_id = fields.Many2one(
        'res.users', string='Printed By', index=True, readonly=True,
        default=lambda self: self.env.user)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    @api.depends('template_id', 'res_model', 'res_id')
    def _compute_display_name(self):
        for log in self:
            log.display_name = '%s (%s #%s)' % (
                log.template_id.display_name, log.res_model, log.res_id)

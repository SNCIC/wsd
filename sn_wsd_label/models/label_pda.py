from odoo import _, api, models
from odoo.exceptions import UserError


class SnLabelPdaService(models.AbstractModel):
    """PDA print channel service (design decision 7).

    The PDA client action fetches CPCL-JSON commands for a template and a
    list of record ids; the browser only base64-encodes them into the
    PrintServer APP ``printserver:cpcl?content=`` URL scheme. All layout
    logic stays server-side, and every successful fetch writes the print
    audit exactly like the PC wizard channel.
    """

    _name = 'sn.label.pda.service'
    _description = 'Label PDA Print Service'

    @api.model
    def print_commands(self, template_id, ids, copies=1):
        """Render CPCL-JSON commands for ``ids`` records of the template.

        :return: dict with ``commands`` (list of command dicts, directly
            JSON-serializable for the scheme payload) and ``copies``.
        :raise UserError: unknown template, unknown model, missing records
            or a non-positive copy count.
        :raise AccessError: the current user cannot read a target record
            (enforced by the renderer's check_records).
        """
        template = self.env['sn.label.template'].browse(template_id).exists()
        if not template:
            raise UserError(
                _('The label template %s does not exist.', template_id))
        model = self.env.get(template.model_name)
        if model is None:
            raise UserError(_('Unknown model %s.', template.model_name))
        try:
            copies = int(copies)
        except (TypeError, ValueError):
            copies = 0
        if copies < 1:
            raise UserError(
                _('The number of copies must be a positive integer.'))
        # accept a bare id, normalize/deduplicate while preserving order
        if isinstance(ids, int):
            ids = [ids]
        try:
            ids = [int(value) for value in (ids or [])]
        except (TypeError, ValueError):
            raise UserError(
                _('No records were selected for label printing.'))
        ids = list(dict.fromkeys(ids))
        if not ids:
            raise UserError(
                _('No records were selected for label printing.'))
        records = model.browse(ids).exists()
        if not records or len(records) != len(ids):
            raise UserError(_('Some of the selected records no longer exist.'))
        commands = self.env['sn.label.renderer'].render_cpcl_json(
            template._to_layout_dict(), records, copies=copies)
        self._log_print(template, records, copies)
        return {'commands': commands, 'copies': copies}

    def _log_print(self, template, records, copies):
        """One sn.label.print.log per printed record, written with sudo so
        printing never requires write access on the audit model (same
        contract as the PC wizard channel)."""
        company_id = template.company_id.id or self.env.company.id
        self.env['sn.label.print.log'].sudo().create([{
            'template_id': template.id,
            'res_model': template.model_name,
            'res_id': record.id,
            'copies': copies,
            'user_id': self.env.user.id,
            'company_id': company_id,
        } for record in records])

import base64
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class SnLabelPrintWizard(models.TransientModel):
    """PC label print wizard: pick an active template for the target model,
    set copies, download the ZPL through the qweb-text report and write the
    print audit (design decision 6).

    Connector modules open it with context keys (contract, keep stable):

    - ``default_res_model`` / ``default_res_ids`` where res_ids is a JSON
      array string such as ``"[1,2]"``, or the standard
      ``active_model`` / ``active_ids`` pair;
    - ``default_template_id`` for an explicit template (otherwise the
      single active template of the model is auto-selected).
    """

    _name = 'sn.label.print.wizard'
    _description = 'Label Print Wizard'

    template_id = fields.Many2one(
        'sn.label.template', string='Label Template', required=True,
        domain="['&', ('active', '=', True), ('model_name', '=', res_model)]")
    res_model = fields.Char(string='Record Model', required=True)
    res_ids = fields.Char(
        string='Record IDs', required=True,
        help='JSON array of the record ids to print, e.g. "[1,2]".')
    copies = fields.Integer(string='Copies', default=1, required=True)
    preview_png = fields.Binary(
        string='Preview', compute='_compute_preview_png')
    zpl_data = fields.Text(
        string='ZPL Data',
        help='ZPL rendered when the print action is confirmed; consumed by '
             'the qweb-text report shell.')

    # ------------------------------------------------------------------
    # Defaults / template auto-selection
    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        context = self.env.context
        res_model = defaults.get('res_model') or context.get('active_model')
        if res_model:
            defaults['res_model'] = res_model
        res_ids = defaults.get('res_ids')
        if res_ids in (None, False, ''):
            res_ids = self._context_active_ids(res_model)
        if isinstance(res_ids, (list, tuple)):
            res_ids = json.dumps(list(res_ids))
        if res_ids:
            defaults['res_ids'] = res_ids
        if not defaults.get('template_id') and defaults.get('res_model'):
            defaults['template_id'] = self._default_template_id(
                defaults['res_model'])
        return defaults

    @api.model
    def _context_active_ids(self, res_model):
        """Fallback record ids from the standard active_ids context, only
        when they belong to the same model the wizard targets."""
        context = self.env.context
        if context.get('active_model') != res_model:
            return None
        active_ids = list(context.get('active_ids') or [])
        if not active_ids and context.get('active_id'):
            active_ids = [context['active_id']]
        return active_ids or None

    @api.model
    def _default_template_id(self, res_model):
        """Auto-select when exactly one active template matches the model
        (single-template fast path); several templates stay a user choice."""
        if not res_model or self.env.get(res_model) is None:
            return False
        templates = self.env['sn.label.template'].search([
            ('model_id.model', '=', res_model),
            ('active', '=', True),
        ])
        return templates[:1].id if len(templates) == 1 else False

    @api.onchange('res_model')
    def _onchange_res_model(self):
        self.template_id = self._default_template_id(self.res_model)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _res_ids_list(self):
        """Parse and sanity-check the JSON array of record ids."""
        self.ensure_one()
        try:
            ids = json.loads(self.res_ids or '[]')
        except (TypeError, ValueError):
            raise UserError(
                _('The wizard record ids must be a JSON list of integers.'))
        if not isinstance(ids, list) or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in ids):
            raise UserError(
                _('The wizard record ids must be a JSON list of integers.'))
        # deduplicate while preserving order
        return list(dict.fromkeys(ids))

    def _target_records(self):
        """Browse the target records, checking the model exists and every
        record still exists. Read access is enforced later by the renderer
        (check_records) so preview and print share the same gate."""
        self.ensure_one()
        model = self.env.get(self.res_model)
        if model is None:
            raise UserError(_('Unknown model %s.', self.res_model))
        ids = self._res_ids_list()
        if not ids:
            raise UserError(_('No records were selected for label printing.'))
        records = model.browse(ids).exists()
        if len(records) != len(ids):
            raise UserError(_('Some of the selected records no longer exist.'))
        return records

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------
    @api.depends('template_id', 'res_model', 'res_ids')
    def _compute_preview_png(self):
        renderer = self.env['sn.label.renderer']
        for wizard in self:
            wizard.preview_png = False
            if not wizard.template_id or not wizard.res_model:
                continue
            model = wizard.env.get(wizard.res_model)
            if model is None:
                continue
            try:
                ids = json.loads(wizard.res_ids or '[]')
                record = model.browse(ids[:1]).exists()
                if record:
                    wizard.preview_png = base64.b64encode(
                        renderer.render_png(
                            wizard.template_id._to_layout_dict(), record))
            except (UserError, ValidationError, AccessError, ValueError,
                    TypeError):
                wizard.preview_png = False

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------
    def action_print(self):
        """Validate, render the ZPL for every selected record, write one
        audit line per record and return the qweb-text report action."""
        self.ensure_one()
        template = self.template_id
        if self.copies < 1:
            raise UserError(_('The number of copies must be a positive integer.'))
        records = self._target_records()
        # model_name is a stored related: comparing through model_id would
        # read ir.model and fail for users without ir.model access.
        if template.model_name != self.res_model:
            raise UserError(_(
                'The label template %s targets model %s and cannot print '
                'records of model %s.',
                template.display_name, template.model_name, self.res_model))
        zpl = self.env['sn.label.renderer'].render_zpl(
            template._to_layout_dict(), records, copies=self.copies)
        self.zpl_data = zpl
        self._log_print(records)
        report_action = self.env.ref(
            'sn_wsd_label.action_report_label_zpl').report_action(
                self.id, config=False)
        report_action.update({'close_on_report_download': True})
        return report_action

    def _log_print(self, records):
        """One sn.label.print.log per printed record, written with sudo so
        printing never requires write access on the audit model."""
        self.ensure_one()
        company_id = self.template_id.company_id.id or self.env.company.id
        self.env['sn.label.print.log'].sudo().create([{
            'template_id': self.template_id.id,
            'res_model': self.res_model,
            'res_id': record.id,
            'copies': self.copies,
            'user_id': self.env.user.id,
            'company_id': company_id,
        } for record in records])

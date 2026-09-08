# -*- coding: utf-8 -*-
"""Wizard that imports an ERP tree-structured BOM Excel file into mrp.bom.

Workflow inside one form:
1. Upload the template (.xlsx), optionally enable skipping existing BOM codes.
2. Click "Parse & Preview" to validate materials, UoMs, and workshops and to
   see which BOMs will be created, skipped, or blocked.
3. Click "Import" to create sub-assembly BOMs bottom-up, then the top-level
   BOMs. Each run is recorded in ``sn.bom.import.log``.

Import rules:
- ``product_qty`` comes from the Excel standard quantity column and is already
  normalized from the numerator/denominator fields.
- Disabled rows are skipped and never become BOM lines.
- BOM header: ``code`` = BOM version, ``type`` = normal, ``product_qty`` = 1,
  ``product_uom_id`` = the ERP unit of the produced item, ``x_workshop_id`` =
  workshop (required).
- BOM lines are created with command values for product, quantity, UoM, and
  sequence.
- ``child_bom_id`` is left to Odoo and is resolved from the component product.
- Missing products, UoMs, or workshops block the whole import so the user can
  fix the file or master data and retry. Duplicate BOM codes are skipped and
  listed in the preview.
"""

import base64

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from .bom_template_parser import parse_bom_xlsx


def _esc(value):
    from markupsafe import escape

    return escape('' if value is None else str(value))


class BomImportWizard(models.TransientModel):
    _name = 'sn.bom.import.wizard'
    _description = 'BOM Excel Import Wizard'

    # ``file`` is intentionally not required at model level. The menu action
    # opens an empty transient record first, and a required field without a
    # default would fail before the wizard becomes visible.
    file = fields.Binary(string='Excel Template', attachment=False)
    file_name = fields.Char(string='File Name', readonly=True)
    skip_existing = fields.Boolean(
        string='Skip BOM codes that already exist',
        default=True,
        help='When a BOM version code from the file already exists in the '
             'system it is reported and skipped instead of being re-created.',
    )
    report_html = fields.Html(string='Validation Preview', readonly=True)
    result_html = fields.Html(string='Import Result', readonly=True)
    log_id = fields.Many2one('sn.bom.import.log', string='Import Log', readonly=True)

    # ------------------------------------------------------------------ utils

    def _open_wizard(self):
        """Open the wizard with a freshly created transient record."""
        wizard = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _decode_file(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Please select an Excel template file first.'))
        return base64.b64decode(self.file or b'')

    def _collect(self, parsed):
        """Merge parse output into flat candidate lists with row info."""
        candidates = list(parsed['top']) + list(parsed['subs'])
        used_codes = set()
        used_uoms = set()
        for cand in candidates:
            if cand['code']:
                used_codes.add(cand['code'])
            for line in cand['lines']:
                if line['disabled']:
                    continue
                if line['code']:
                    used_codes.add(line['code'])
                if line['uom']:
                    used_uoms.add(line['uom'])
        return candidates, used_codes, used_uoms

    def _precheck(self, parsed):
        """Map file candidates against master data and return a report dict."""
        candidates, used_codes, used_uoms = self._collect(parsed)
        Product = self.env['product.product'].with_context(active_test=False)
        Uom = self.env['uom.uom']
        Workshop = self.env['sn.mrp.workshop']
        Bom = self.env['mrp.bom'].with_context(active_test=False)

        product_map = {}
        if used_codes:
            for product in Product.search([('default_code', 'in', sorted(used_codes))]):
                if product.default_code not in product_map:
                    product_map[product.default_code] = product.id

        uom_map = {}
        if used_uoms:
            for uom in Uom.search([('name', 'in', sorted(used_uoms))]):
                uom_map.setdefault(uom.name, uom.id)

        ws_map = {}
        workshop_names = {c['workshop'] for c in candidates if c['workshop']}
        if workshop_names:
            for workshop in Workshop.search([('name', 'in', sorted(workshop_names))]):
                ws_map.setdefault(workshop.name, workshop.id)

        bom_codes = []
        for cand in candidates:
            if cand['bom_version']:
                bom_codes.append(cand['bom_version'])
            elif cand['code']:
                bom_codes.append('%s_IMP' % cand['code'])

        existing_codes = set()
        if bom_codes:
            for bom in Bom.search([('code', 'in', bom_codes)]):
                existing_codes.add(bom.code)

        missing_products = []
        missing_uoms = []
        missing_workshops = []
        no_workshop = []
        report_candidates = []

        for cand in candidates:
            bom_code = cand['bom_version'] or (('%s_IMP' % cand['code']) if cand['code'] else '')
            status = 'new'
            reason = ''

            if cand['disabled']:
                status = 'blocked'
                reason = _('root row disabled')
            elif not cand['code']:
                status = 'blocked'
                reason = _('missing product code')
            elif not bom_code:
                status = 'blocked'
                reason = _('missing BOM version')
            elif bom_code in existing_codes:
                if self.skip_existing:
                    status = 'skip'
                else:
                    status = 'blocked'
                    reason = _('BOM code already exists')
            elif cand['code'] not in product_map:
                status = 'blocked'
                reason = _('product not found: %s') % cand['code']
                missing_products.append((cand['code'], cand['name']))
            elif not cand['workshop']:
                status = 'blocked'
                reason = _('missing workshop on row %s') % cand['row']
                no_workshop.append((cand['row'], cand['code'], cand['name']))
            elif cand['workshop'] not in ws_map:
                status = 'blocked'
                reason = _('workshop not found: %s') % cand['workshop']
                missing_workshops.append(cand['workshop'])
            elif cand['uom'] not in uom_map:
                status = 'blocked'
                reason = _('uom not found: %s') % cand['uom']
                missing_uoms.append(cand['uom'])
            else:
                for line in cand['lines']:
                    if line['disabled']:
                        continue
                    if not line['code']:
                        status = 'blocked'
                        reason = _('line without product code (row %s)') % line['row']
                        break
                    if line['code'] not in product_map:
                        status = 'blocked'
                        reason = _('line product not found: %s (row %s)') % (
                            line['code'], line['row'])
                        missing_products.append((line['code'], line['name']))
                        break
                    if line['uom'] not in uom_map:
                        status = 'blocked'
                        reason = _('line uom not found: %s (row %s)') % (
                            line['uom'], line['row'])
                        missing_uoms.append(line['uom'])
                        break
                    if line['std_qty'] is None:
                        status = 'blocked'
                        reason = _('line without usage quantity (row %s)') % line['row']
                        break

            report_candidates.append({
                'row': cand['row'],
                'code': cand['code'],
                'name': cand['name'],
                'spec': cand['spec'],
                'bom_code': bom_code,
                'uom': cand['uom'],
                'workshop': cand['workshop'],
                'depth': cand['depth'],
                'status': status,
                'block_reason': reason,
                'line_count': cand['line_count'],
                'active_line_count': sum(1 for ln in cand['lines'] if not ln['disabled']),
                'lines': cand['lines'],
            })

        dedup_missing = []
        seen = set()
        for code, name in missing_products:
            if code not in seen:
                seen.add(code)
                dedup_missing.append((code, name))

        blocked = any(c['status'] == 'blocked' for c in report_candidates)
        return {
            'candidates': report_candidates,
            'missing_products': dedup_missing,
            'missing_uoms': sorted(set(missing_uoms)),
            'missing_workshops': sorted(set(missing_workshops)),
            'no_workshop': no_workshop,
            'blocked': blocked,
        }

    # --------------------------------------------------------------- preview

    def _build_report_html(self, parsed, check):
        to_import = [c for c in check['candidates'] if c['status'] == 'new']
        skipped = [c for c in check['candidates'] if c['status'] == 'skip']
        blocked = [c for c in check['candidates'] if c['status'] == 'blocked']
        lines = [c['active_line_count'] for c in to_import]
        status_label = {
            'new': _('New'),
            'skip': _('Skip'),
            'blocked': _('Blocked'),
        }

        html = []
        html.append('<h4>%s</h4>' % _('File summary'))
        html.append(
            '<p>%s <b>%s</b> - %s - %s - %s</p>'
            % (_('Sheet'), _esc(parsed['sheet']),
               _('%s data rows') % parsed['raw_count'],
               _('%s disabled row(s) excluded') % parsed['disabled_count'],
               _('%s BOM candidate(s) found') % len(check['candidates'])))
        html.append('<h4>%s</h4>' % _('Candidates'))
        if check['candidates']:
            html.append('<table border="1" cellspacing="0" cellpadding="4" '
                        'style="border-collapse:collapse">')
            html.append('<tr>')
            for header in (_('Status'), _('BOM code'), _('Product'),
                           _('Workshop'), _('UoM'), _('Rows'), _('Lines'),
                           _('Detail')):
                html.append('<th>%s</th>' % header)
            html.append('</tr>')
            color = {'new': '#0a6', 'skip': '#888', 'blocked': '#c00'}
            for c in check['candidates']:
                html.append(
                    '<tr><td style="color:%s"><b>%s</b></td><td>%s</td>'
                    '<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                    '<td>%s</td></tr>'
                    % (color[c['status']], status_label[c['status']],
                       _esc(c['bom_code']),
                       _esc('%s %s' % (c['code'], c['name'])),
                       _esc(c['workshop'] or '-'), _esc(c['uom'] or '-'),
                       c['row'], c['active_line_count'],
                       _esc(c['block_reason'] or '')))
            html.append('</table>')
        if check['missing_products']:
            html.append('<h4 style="color:#c00">%s</h4><ul>'
                        % _('Missing products'))
            for code, name in check['missing_products']:
                html.append('<li>%s - %s</li>' % (_esc(code), _esc(name)))
            html.append('</ul>')
        if check['missing_uoms']:
            html.append('<h4 style="color:#c00">%s</h4><ul>'
                        % _('Missing UoMs'))
            for name in check['missing_uoms']:
                html.append('<li>%s</li>' % _esc(name))
            html.append('</ul>')
        if check['missing_workshops']:
            html.append('<h4 style="color:#c00">%s</h4><ul>'
                        % _('Missing workshops'))
            for name in check['missing_workshops']:
                html.append('<li>%s</li>' % _esc(name))
            html.append('</ul>')
        if not to_import and not skipped:
            html.append('<p style="color:#c00"><b>%s</b></p>'
                        % _('Nothing importable found in this file.'))
        elif check['blocked']:
            html.append(
                '<p style="color:#c00"><b>%s</b> %s. %s %s.</p>'
                % (_('Blocked:'),
                   _('%s BOM(s) have master-data gaps') % len(blocked),
                   _('Resolve them (or fix the file) and preview again.'),
                   _('Nothing can be imported until all gaps are cleared.')))
        else:
            ready_line = ('<p style="color:#0a6"><b>%s</b> %s.'
                          % (_('Ready:'),
                             _('%s BOM(s) / %s line(s) will be created')
                             % (len(to_import), sum(lines))))
            if skipped:
                ready_line = ('<p style="color:#0a6"><b>%s</b> %s - %s.'
                              % (_('Ready:'),
                                 _('%s BOM(s) / %s line(s) will be created')
                                 % (len(to_import), sum(lines)),
                                 _('%s already existing skipped')
                                 % len(skipped)))
            html.append(ready_line)
        return ''.join(html)

    def action_parse(self):
        self.ensure_one()
        parsed = parse_bom_xlsx(self._decode_file())
        check = self._precheck(parsed)
        self.report_html = self._build_report_html(parsed, check)
        self.result_html = False
        self.log_id = False
        return self._reopen()

    # ---------------------------------------------------------------- import

    def _import_candidates(self, check):
        """Create BOMs bottom-up. Returns ``(bom_count, line_count)``."""
        candidates = [c for c in check['candidates'] if c['status'] == 'new']
        if not candidates:
            raise UserError(_('There is nothing to import. Run Parse & Preview '
                              'first and check the report.'))

        Product = self.env['product.product'].with_context(active_test=False)
        Uom = self.env['uom.uom']
        Workshop = self.env['sn.mrp.workshop']
        Bom = self.env['mrp.bom']

        all_codes = {c['code'] for c in candidates}
        line_codes = {ln['code'] for cand in candidates
                      for ln in cand['lines'] if not ln['disabled']}
        all_codes |= line_codes

        product_map = {}
        for product in Product.search([('default_code', 'in', sorted(all_codes))]):
            product_map.setdefault(product.default_code, product)

        uom_map = {}
        uom_names = {c['uom'] for c in candidates} | {
            ln['uom'] for cand in candidates
            for ln in cand['lines'] if not ln['disabled']}
        for uom in Uom.search([('name', 'in', sorted(uom_names))]):
            uom_map.setdefault(uom.name, uom)

        ws_map = {}
        for workshop in Workshop.search([('name', 'in',
                                          sorted({c['workshop'] for c in candidates}))]):
            ws_map.setdefault(workshop.name, workshop)

        # Deepest sub-assemblies first, then the top-level BOMs.
        ordered = sorted(candidates, key=lambda c: c['depth'], reverse=True)
        bom_count = 0
        line_count = 0
        for cand in ordered:
            line_commands = []
            seq = 0
            for line in cand['lines']:
                if line['disabled'] or not line['code']:
                    continue
                seq += 1
                line_commands.append(Command.create({
                    'product_id': product_map[line['code']].id,
                    'product_qty': float(line['std_qty']),
                    'product_uom_id': uom_map[line['uom']].id,
                    'sequence': seq,
                }))

            Bom.create({
                'code': cand['bom_code'],
                'type': 'normal',
                'product_tmpl_id': product_map[cand['code']].product_tmpl_id.id,
                'product_qty': 1.0,
                'product_uom_id': uom_map[cand['uom']].id,
                'x_workshop_id': ws_map[cand['workshop']].id,
                'ready_to_produce': 'asap',
                'consumption': 'flexible',
                'bom_line_ids': line_commands,
            })
            bom_count += 1
            line_count += len(line_commands)
        return bom_count, line_count

    def action_import(self):
        self.ensure_one()
        parsed = parse_bom_xlsx(self._decode_file())
        check = self._precheck(parsed)
        blocked = [c for c in check['candidates'] if c['status'] == 'blocked']
        if blocked:
            details = '; '.join(
                '%s (%s)' % (c['bom_code'], c['block_reason'])
                for c in blocked[:10])
            raise UserError(_(
                'Import blocked: %s BOM(s) have master-data gaps (%s). Fix the '
                'file or the master data, then preview again.'
            ) % (len(blocked), details))

        skipped = [c for c in check['candidates'] if c['status'] == 'skip']
        bom_count, line_count = self._import_candidates(check)

        log = self.env['sn.bom.import.log'].create({
            'file_name': self.file_name or 'upload.xlsx',
            'state': 'success',
            'bom_count': bom_count,
            'line_count': line_count,
            'skipped_count': len(skipped),
            'summary': _('Created %s BOM(s) with %s line(s); skipped %s '
                         'existing BOM code(s).') % (
                             bom_count, line_count, len(skipped)),
        })
        self.log_id = log.id
        self.result_html = (
            '<p style="color:#0a6"><b>%s</b> %s.</p>'
            '<p>%s: %s.</p>'
            % (_('Import finished'),
               _('%s BOM(s) created with %s line(s)')
               % (bom_count, line_count),
               _('Skipped existing'),
               ', '.join(_esc(c['bom_code']) for c in skipped) if skipped
               else _('none')))
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

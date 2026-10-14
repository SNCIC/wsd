"""Measuring support for incoming inspections (IQC).

Adds the per-item measuring wizard, the one-click test data generation and
the helpers the printed incoming inspection record is built on.
"""

import hashlib
import random

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_repr


REPORT_TEST_DATA_COLUMNS = 7
# Rows the printed test data grid always shows, so a short series of
# measurements still fills the sheet like the paper form it mirrors.
REPORT_TEST_DATA_ROWS = 8
REPORT_FILE_SUFFIX = '.pdf'
# Height the printed record fills on one A4 page (297mm minus the 10mm
# margins, kept short of the edge) and the height of every block that is not
# the item table: the item table takes the room that is left, so the record
# covers the sheet instead of stopping in the middle of it.
# Height the printed record is laid out for. wkhtmltopdf renders a cell a
# little shorter than the spacer it holds, so the figure keeps a margin over
# the 277mm printable height of the sheet: the record lands close to it
# without ever spilling onto a second page.
REPORT_PAGE_HEIGHT_MM = 270.0
REPORT_HEIGHT_MM = {
    'title': 18.0,
    'meta': 8.0,
    'info_row': 11.0,
    'description': 26.0,
    'conclusion': 11.0,
    'inspector': 11.0,
    'item_header': 8.0,
    'plain_item_row': 13.0,
}
REPORT_INFO_ROWS = 4
REPORT_GRID_PADDING_MM = 4.0
REPORT_MAX_ROW_HEIGHT_MM = 12.0
REPORT_MIN_ROW_HEIGHT_MM = 3.0
REPORT_MAX_FONT_SIZE = 11.0
REPORT_MIN_FONT_SIZE = 6.5


class QualityInspectionScheme(models.Model):
    _inherit = 'sn.wsd.quality.inspection.scheme'

    x_inspection_basis = fields.Char(
        string='Inspection Basis',
        tracking=True,
        help='Standard the inspection follows, for instance the incoming '
             'inspection specification. Printed on the incoming inspection '
             'record and copied onto the inspections taken from this scheme.',
    )


class QualityInspection(models.Model):
    _inherit = 'sn.wsd.quality.inspection'

    x_inspection_basis = fields.Char(
        string='Inspection Basis',
        help='Standard the inspection follows; copied from the scheme.',
    )
    x_reviewer_id = fields.Many2one(
        'res.users',
        string='Reviewer',
        default=lambda self: self.env.user,
        tracking=True,
        help='Person who reviewed the inspection record.',
    )
    manufacturer = fields.Char(
        string='Manufacturer',
        compute='_compute_manufacturer',
        store=True,
        readonly=False,
        tracking=True,
        help='Maker of the incoming material. Defaulted from the supplier '
             'and editable: printed next to the supplier on the inspection '
             'record.',
    )

    @api.depends('picking_id.partner_id.manufacturer')
    def _compute_manufacturer(self):
        for inspection in self:
            inspection.manufacturer = (
                inspection.picking_id.partner_id.manufacturer or '')
    x_report_file = fields.Binary(
        string='Inspection Report',
        attachment=True,
        copy=False,
        help='Measuring report handed in by the inspection unit (PDF only).',
    )
    x_report_filename = fields.Char(string='Report Filename', copy=False)
    x_pass_qty = fields.Integer(
        string='Qualified Qty',
        compute='_compute_x_report_stats',
        store=True,
        help='Measured samples that came out qualified.',
    )
    x_pass_rate = fields.Float(
        string='Qualified Rate (%)',
        compute='_compute_x_report_stats',
        store=True,
        digits=(16, 2),
    )

    @api.depends('sample_value_ids.result', 'sample_value_ids.sample_id',
                 'sample_ids.result', 'sample_ids.qty', 'sample_size')
    def _compute_x_report_stats(self):
        """Qualified pieces of the incoming record.

        The printed record counts pieces, not measurements: a sample is
        qualified unless one of its measurements came out failed. Counting the
        judged measurement rows instead would multiply the quantity by the
        number of inspection items and break the figure of the record.
        """
        for inspection in self:
            judged_values = inspection.sample_value_ids.filtered(
                lambda value: value.result in ('pass', 'fail'))
            judged_samples = inspection.sample_ids.filtered(
                lambda sample: sample.result in ('pass', 'fail'))
            failed_values = judged_values.filtered(
                lambda value: value.result == 'fail')
            defect_samples = failed_values.mapped('sample_id') \
                | judged_samples.filtered(
                    lambda sample: sample.result == 'fail')
            defect_qty = sum(defect_samples.mapped('qty'))
            if not defect_samples:
                # An item recorded per lot carries no sample: the failed item
                # itself stands for the defect.
                defect_qty = len(failed_values.mapped('line_id'))
            # Nothing judged yet: the record reports no quantity instead of a
            # fully qualified lot nobody has looked at.
            measured = bool(judged_values or judged_samples)
            inspection.x_pass_qty = max(
                inspection.sample_size - defect_qty, 0) if measured else 0
            inspection.x_pass_rate = (
                100.0 * inspection.x_pass_qty / inspection.sample_size
                if measured and inspection.sample_size else 0.0)

    @api.constrains('x_report_filename')
    def _check_x_report_filename(self):
        for inspection in self:
            name = (inspection.x_report_filename or '').strip()
            if name and not name.lower().endswith(REPORT_FILE_SUFFIX):
                raise ValidationError(_(
                    'The inspection report must be a PDF file.'))

    @api.model
    def create_from_scheme(self, scheme, values):
        if scheme and not hasattr(scheme, 'ids'):
            scheme = self.env['sn.wsd.quality.inspection.scheme'].browse(
                int(scheme)).exists()
        values = dict(values)
        if scheme and scheme.x_inspection_basis \
                and not values.get('x_inspection_basis'):
            values['x_inspection_basis'] = scheme.x_inspection_basis
        return super().create_from_scheme(scheme, values)

    def action_generate_all_values(self):
        """Generate the test data of every item still waiting for input.

        Generated data means the samples carried no defect, so the pending
        rows of the sampling ledger are cleared too and the inspection can
        be finished in one go.
        """
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_(
                'Reset the inspection before generating new values.'))
        for line in self.line_ids:
            line.action_generate_values()
        self.sample_ids.filtered(
            lambda sample: sample.result == 'pending').write({'result': 'pass'})
        return True

    def action_set_all_pass(self):
        """Set the whole inspection pass: items, measurements and samples.

        One button for the inspector. The measurements are what makes an
        incoming inspection pass, so the items read sample by sample are
        settled here as well instead of staying pending until someone types
        every figure.
        """
        result = super().action_set_all_pass()
        self.filtered(
            lambda inspection: not inspection._is_sample_matrix_inspection()
        ).line_ids._record_pass_values()
        return result

    def _get_iqc_sampling_notice(self):
        """Sampling rule of the printed record, as a single term."""
        self.ensure_one()
        levels = dict(
            self._fields['inspection_level']._description_selection(self.env))
        return _(
            'GB/T 2828.1 normal inspection, single sampling: '
            'level %(level)s, AQL %(aql)s, AC %(ac)s, Re %(re)s',
            level=levels.get(self.inspection_level, ''),
            aql=self.aql_value,
            ac=self.accept_qty,
            re=self.reject_qty,
        )


    def _get_iqc_supplier_batch_no(self):
        """Supplier production batch printed on the incoming record.

        The batch the receiving flow recorded sits on the lot; when the lot
        carries none, the transfers behind the inspection are read back — the
        quality-control transfer and the receipt that fed it — so the printed
        record never shows a blank production batch.
        """
        self.ensure_one()
        if self.lot_id.supplier_batch_no:
            return self.lot_id.supplier_batch_no
        lines = self._iqc_source_move_lines(
            self.picking_id.move_line_ids, self.product_id)
        return next(
            (line.supplier_batch_no for line in lines
             if line.supplier_batch_no), '')

    def _get_iqc_result_labels(self):
        """Conclusion words of the printed record, one per possible result.

        They come from the result field itself: its selection labels are
        translated from the module's own entries, while a plain word such as
        "Qualified" is shared with other modules and would be translated by
        whichever of them loads last.
        """
        self.ensure_one()
        return dict(self._fields['result']._description_selection(self.env))

    def _get_iqc_report_metrics(self):
        """Heights the printed record needs to cover one A4 page.

        Every block carries the height of the paper form it mirrors; the item
        table takes the room that is left, and inside it the numeric row is
        the tallest cell of the sheet: its grid of figures is printed with
        REPORT_TEST_DATA_ROWS rows and fills that row. A long series of
        measurements is printed in smaller type and shorter rows instead of
        pushing the record onto a second page.
        """
        self.ensure_one()
        heights = dict(REPORT_HEIGHT_MM)
        numeric_lines = self.line_ids.filtered(
            lambda line: line.item_type == 'numeric')
        rows = max(
            [len(line._get_report_test_data_rows()) for line in numeric_lines]
            or [1])
        items_height = REPORT_PAGE_HEIGHT_MM - (
            heights['title'] + heights['meta']
            + REPORT_INFO_ROWS * heights['info_row']
            + heights['description'] + heights['conclusion']
            + heights['inspector'])
        other_rows = len(self.line_ids) - len(numeric_lines)
        numeric_row = max(
            items_height - heights['item_header']
            - other_rows * heights['plain_item_row'],
            heights['plain_item_row'])
        row_height = max(
            min(REPORT_MAX_ROW_HEIGHT_MM,
                (numeric_row - REPORT_GRID_PADDING_MM) / rows),
            REPORT_MIN_ROW_HEIGHT_MM)
        font_size = max(
            min(REPORT_MAX_FONT_SIZE, row_height * 1.55),
            REPORT_MIN_FONT_SIZE)
        metrics = {
            'rows': rows,
            'row_height': round(row_height, 2),
            'font_size': round(font_size, 2),
            'items_height': round(items_height, 1),
            'numeric_row': round(numeric_row, 2),
        }
        metrics.update(heights)
        return metrics

    def _get_iqc_report_styles(self):
        """Layout of the sheet, handed over as a stylesheet.

        wkhtmltopdf sizes a table row from a rule, not from the height or the
        padding written on the cell itself (an inline style is dropped), so
        the block heights of the paper form are emitted as CSS. Every cell
        keeps centring what it holds, which is what vertical-align does.
        """
        self.ensure_one()
        values = dict(self._get_iqc_report_metrics())
        values['grid_row_height'] = values['row_height']
        rules = (
            'table.head td.head-block { height: %(title)smm; }',
            'table.meta td.meta-block { height: %(meta)smm; }',
            'table.info td.info-block { height: %(info_row)smm; }',
            'table.items tbody td.plain-item-block {'
            ' height: %(plain_item_row)smm; }',
            'table.items tbody td.numeric-item-block {'
            ' height: %(numeric_row)smm; }',
            'table.summary td.description { height: %(description)smm; }',
            'table.summary td.conclusion { height: %(conclusion)smm; }',
            'table.summary td.inspector { height: %(inspector)smm; }',
            'table.test-data td { height: %(grid_row_height)smm; }',
        )
        return '\n'.join(
            '                    .sn-iqc-record %s' % (rule % values)
            for rule in rules)

    def _get_iqc_manufacturer_supplier(self):
        """Maker of the incoming material, with the supplier behind it.

        The maker defaults from the supplier and stays editable on the
        inspection, so an incoming batch bought from a distributor names the
        maker that actually produced it. A single name is printed when the
        supplier is the maker itself or when no maker is recorded.
        """
        self.ensure_one()
        supplier = self.picking_id.partner_id.name or ''
        manufacturer = self.manufacturer or ''
        if manufacturer and supplier and manufacturer != supplier:
            return self.env._(
                '%(manufacturer)s (%(supplier)s)',
                manufacturer=manufacturer,
                supplier=supplier,
            )
        return supplier or manufacturer


class QualityInspectionLine(models.Model):
    _inherit = 'sn.wsd.quality.inspection.line'

    sample_value_ids = fields.One2many(
        'sn.wsd.quality.inspection.sample.value',
        'line_id',
        string='Sample Values',
    )
    x_inspect_qty = fields.Integer(
        string='Qty to Inspect',
        compute='_compute_x_inspect_qty',
        store=True,
        readonly=False,
        help='How many measurements this item requires: one per sample for '
             "'One Value per Sample' items, a single one otherwise. Derived "
             'from the sampling result and editable while the inspection is '
             'open.',
    )
    x_checked_qty = fields.Integer(
        string='Checked Qty',
        compute='_compute_x_checked_qty',
        store=True,
        help='Measurements already concluded (qualified or failed).',
    )

    @api.depends('sample_record_mode', 'inspection_id.sample_size',
                 'inspection_id.sample_ids', 'sample_value_ids')
    def _compute_x_inspect_qty(self):
        for line in self:
            if line.x_inspect_qty:
                continue
            line.x_inspect_qty = line._default_inspect_qty()

    @api.depends('sample_value_ids.result')
    def _compute_x_checked_qty(self):
        for line in self:
            line.x_checked_qty = len(line.sample_value_ids.filtered(
                lambda value: value.result in ('pass', 'fail')))

    @api.depends(
        'item_type', 'is_checked', 'measured_value', 'lower_limit',
        'upper_limit', 'text_value', 'expected_value', 'manual_result',
        'cell_ids.result', 'inspection_id.sample_ids.result',
        'inspection_id.sample_ids.x_line_id', 'inspection_id.inspection_type',
        'sample_value_ids.result',
    )
    def _compute_result(self):
        super()._compute_result()
        for line in self.filtered(
                lambda item: item.sample_value_ids
                and item.inspection_id.inspection_type == 'iqc'):
            # Incoming inspection: the item conclusion rolls up the recorded
            # measurements, so any failed measurement fails the item and the
            # item only passes once every measurement is recorded and good.
            results = set(line.sample_value_ids.mapped('result'))
            if 'fail' in results:
                line.result = 'fail'
            elif results == {'pass'}:
                line.result = 'pass'
            else:
                line.result = 'pending'

    def _default_inspect_qty(self):
        self.ensure_one()
        if self.sample_record_mode != 'per_sample':
            return 1
        inspection = self.inspection_id
        return (len(self.sample_value_ids) or len(inspection.sample_ids)
                or inspection.sample_size or 1)

    def _required_inspect_qty(self):
        self.ensure_one()
        return max(self.x_inspect_qty or self._default_inspect_qty(), 1)

    def _ensure_sample_value_rows(self):
        """Create the measurements rows this item still misses."""
        for line in self:
            inspection = line.inspection_id
            existing = line.sample_value_ids
            commands = []
            if line.sample_record_mode == 'per_sample':
                target = line._required_inspect_qty()
                samples = inspection.sample_ids[:target]
                if samples:
                    covered = set(existing.mapped('sample_id').ids)
                    commands = [
                        {'sequence': sequence, 'sample_id': sample.id}
                        for sequence, sample in enumerate(samples, 1)
                        if sample.id not in covered
                    ]
                elif len(existing) < target:
                    commands = [
                        {'sequence': sequence}
                        for sequence in range(len(existing) + 1, target + 1)
                    ]
            elif not existing:
                commands = [{'sequence': 1}]
            if commands:
                line.write({'sample_value_ids': [
                    Command.create(dict(command, inspection_id=inspection.id))
                    for command in commands
                ]})
        return True

    def _generate_random_value(self, index):
        """Random measure inside the item limits.

        The value only depends on the record, the row index and the limits,
        so the same item always produces the same figures.
        """
        self.ensure_one()
        lower, upper = self.lower_limit, self.upper_limit
        if upper < lower:
            lower, upper = upper, lower
        seed = '%s-%s-%s-%s' % (self.id, index, lower, upper)
        digest = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]
        generator = random.Random(int(digest, 16))
        return round(generator.uniform(lower, upper), self._get_value_digits())

    def action_generate_values(self):
        """Fill every pending measurement of this item."""
        self.ensure_one()
        if self.inspection_id.state == 'done':
            raise UserError(_(
                'Reset the inspection before generating new values.'))
        self._ensure_sample_value_rows()
        now = fields.Datetime.now()
        pending = self.sample_value_ids.filtered(
            lambda value: value.result == 'pending')
        if self.item_type == 'numeric':
            for index, value in enumerate(pending, 1):
                measured = self._generate_random_value(index)
                # The conclusion is written along with the measurement: the
                # legacy sample-value compute only refreshes it as a side
                # effect of the deviation, which is not always triggered.
                value.write({
                    'measured_value': measured,
                    'measured_at': now,
                    'result': self._judge_item_value(
                        'numeric',
                        measured=measured,
                        lower=self.lower_limit,
                        upper=self.upper_limit,
                    ),
                })
        else:
            pending.write({'result': 'pass', 'measured_at': now})
        return True

    def _record_pass_values(self):
        """Record a qualifying value on every measurement still waiting.

        Deterministic counterpart of ``action_generate_values``: numeric items
        take the middle of their limits instead of a random figure, so a record
        filled by "all pass" reads back the same every time.
        """
        for line in self:
            if line.inspection_id.state == 'done':
                raise UserError(_(
                    'Reset the inspection before recording new values.'))
            line._ensure_sample_value_rows()
            now = fields.Datetime.now()
            for value in line.sample_value_ids.filtered(
                    lambda item: item.result == 'pending'):
                values = {'measured_at': now}
                if line.item_type == 'numeric':
                    measured = line._get_pass_numeric_value()
                    # The conclusion is written along with the measurement,
                    # the way action_generate_values does it: the sample value
                    # only refreshes its result as a side effect of the
                    # deviation, which a caller reading the item later in the
                    # same transaction (the batch pass) never triggers.
                    values['measured_value'] = measured
                    values['result'] = line._judge_item_value(
                        'numeric',
                        measured=measured,
                        lower=line.lower_limit,
                        upper=line.upper_limit,
                    )
                else:
                    # A non-numeric row carries no judgement of its own: the
                    # conclusion is written along with the value.
                    values['text_value'] = line._get_pass_text_value()
                    values['result'] = 'pass'
                value.write(values)
        return True

    def _measure_wizard_line_values(self):
        """Rows the measuring wizard opens with.

        The recorded measurements are loaded back; an item without any row
        opens on the rows it still expects.
        """
        self.ensure_one()
        existing = self.sample_value_ids.sorted(
            lambda value: (value.sequence, value.id))
        if existing:
            return [{
                'sequence': value.sequence,
                'sample_id': value.sample_id.id,
                'measured_value': value.measured_value,
                'text_value': value.text_value,
                'measured_at': value.measured_at,
                'manual_result': (
                    value.result if value.result in ('pass', 'fail')
                    else 'pending'),
                'defect_code_id': value.defect_code_id.id,
                'note': value.note,
            } for value in existing]
        inspection = self.inspection_id
        if self.sample_record_mode == 'per_sample':
            samples = inspection.sample_ids[:self._required_inspect_qty()]
            if samples:
                return [
                    {'sequence': sequence, 'sample_id': sample.id}
                    for sequence, sample in enumerate(samples, 1)
                ]
            return [
                {'sequence': sequence}
                for sequence in range(1, self._required_inspect_qty() + 1)
            ]
        return [{'sequence': 1}]

    def action_open_measure_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inspection Measurement'),
            'res_model': 'sn.wsd.quality.inspection.measure.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_line_id': self.id},
        }

    def _get_report_test_data_rows(self, columns=REPORT_TEST_DATA_COLUMNS):
        """Test data of a numeric item, laid out ``columns`` cells per row."""
        self.ensure_one()
        values = self.sample_value_ids.sorted(
            lambda value: (value.sequence, value.id))
        cells = [(value._get_report_measured_text(), value.result)
                 for value in values]
        while cells and len(cells) % columns:
            cells.append(('', 'empty'))
        rows = [cells[index:index + columns]
                for index in range(0, len(cells), columns)]
        # The grid keeps the shape of the paper form: empty rows are printed
        # under the figures instead of leaving the sheet half blank.
        while len(rows) < REPORT_TEST_DATA_ROWS:
            rows.append([('', 'empty')] * columns)
        return rows

    def _get_report_requirement(self):
        """Requirement cell of the printed record, as a single term."""
        self.ensure_one()
        if self.item_type != 'numeric':
            return self.expected_value or self.instruction or ''
        digits = self._get_value_digits()
        limits = '%s (%s ~ %s)' % (
            float_repr(self.nominal_value, digits),
            float_repr(self.lower_limit, digits),
            float_repr(self.upper_limit, digits),
        )
        return '%s %s' % (limits, self.unit) if self.unit else limits

    def _get_report_mark_cells(self):
        """One mark per inspected sample of a non-numeric item."""
        self.ensure_one()
        values = self.sample_value_ids.sorted(
            lambda value: (value.sequence, value.id))
        if values:
            return list(values.mapped('result'))
        count = self._required_inspect_qty()
        if self.result in ('pass', 'fail'):
            return [self.result] * count
        return ['pending'] * count


class QualityInspectionSampleValue(models.Model):
    _inherit = 'sn.wsd.quality.inspection.sample.value'

    def _get_report_measured_text(self):
        self.ensure_one()
        if self.line_id.item_type == 'numeric':
            return float_repr(
                self.measured_value, self.line_id._get_value_digits())
        return self.text_value or ''


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_iqc_inspect_qty = fields.Integer(
        string='Qty to Inspect',
        compute='_compute_x_iqc_inspect_qty',
        help='Sample size the incoming quality control requires for this '
             'line, taken from the inspection the transfer generated.',
    )

    def _compute_x_iqc_inspect_qty(self):
        Inspection = self.env['sn.wsd.quality.inspection']
        for move in self:
            inspections = move.move_line_ids.x_quality_inspection_ids.filtered(
                lambda inspection: inspection.inspection_type == 'iqc')
            if not inspections and move.picking_id and move.product_id:
                inspections = Inspection.search([
                    ('inspection_type', '=', 'iqc'),
                    ('picking_id', '=', move.picking_id.id),
                    ('product_id', '=', move.product_id.id),
                    ('state', '!=', 'skipped'),
                ])
            move.x_iqc_inspect_qty = max(
                inspections.mapped('sample_size') or [0])

    def action_create_iqc_inspection(self):
        self.ensure_one()
        action = super().action_create_iqc_inspection()
        if not action and self.picking_id._is_iqc_control_picking():
            raise UserError(_(
                'No effective incoming inspection scheme matches %s.',
                self.product_id.display_name))
        return action


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    x_iqc_inspect_qty = fields.Integer(
        string='Qty to Inspect',
        compute='_compute_x_iqc_inspect_qty',
        help='Sample size the incoming quality control requires for this '
             'line, taken from the inspection the transfer generated.',
    )

    def _compute_x_iqc_inspect_qty(self):
        Inspection = self.env['sn.wsd.quality.inspection']
        for move_line in self:
            inspections = move_line.x_quality_inspection_ids.filtered(
                lambda inspection: inspection.inspection_type == 'iqc')
            if not inspections and move_line.picking_id and move_line.product_id:
                inspections = Inspection.search([
                    ('inspection_type', '=', 'iqc'),
                    ('picking_id', '=', move_line.picking_id.id),
                    ('product_id', '=', move_line.product_id.id),
                    ('state', '!=', 'skipped'),
                ])
            move_line.x_iqc_inspect_qty = max(
                inspections.mapped('sample_size') or [0])

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


INSPECTION_LEVEL_SELECTION = [
    ('s1', 'S-1'),
    ('s2', 'S-2'),
    ('s3', 'S-3'),
    ('s4', 'S-4'),
    ('g1', 'General I'),
    ('g2', 'General II'),
    ('g3', 'General III'),
]

SWITCHING_MODE_SELECTION = [
    ('normal', 'Normal'),
    ('tightened', 'Tightened'),
    ('reduced', 'Reduced'),
]

SAMPLING_METHOD_SELECTION = [
    ('fixed', 'Fixed Quantity'),
    ('aql', 'AQL'),
    ('full', '100% Inspection'),
]

LOT_QTY_SOURCE_SELECTION = [
    ('manual', 'Manual'),
    ('move_line', 'Operation Line Quantity'),
    ('picking_product', 'Transfer Product Quantity'),
    ('mes_order', 'MES Order Quantity'),
    ('production', 'Manufacturing Order Quantity'),
    ('workorder_output', 'Work Order Output Quantity'),
]

SAMPLE_SELECTION_METHOD_SELECTION = [
    ('manual', 'Manual'),
    ('systematic', 'Systematic'),
]

DEFAULT_AQL_VALUES = [0.01, 0.015, 0.025, 0.04, 0.065, 0.1, 0.15, 0.25, 0.4, 0.65, 1.0, 1.5, 2.5, 4.0, 6.5, 10.0]
DEFAULT_SAMPLE_SIZE_CODES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R']


class QualitySamplingStandard(models.Model):
    _name = 'sn.wsd.quality.sampling.standard'
    _description = 'WSD Quality Sampling Standard'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code, id'
    _check_company_auto = True

    name = fields.Char(string='Standard Name', required=True, tracking=True)
    code = fields.Char(string='Standard Code', required=True, index=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    note = fields.Text(string='Notes')
    lot_range_ids = fields.One2many(
        'sn.wsd.quality.sampling.lot.range',
        'standard_id',
        string='Lot Ranges',
    )
    plan_ids = fields.One2many(
        'sn.wsd.quality.sampling.plan',
        'standard_id',
        string='Sampling Plans',
    )

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The sampling standard code must be unique per company.',
    )

    @api.model
    def _matrix_level_columns(self):
        return [
            {'key': key, 'label': label}
            for key, label in INSPECTION_LEVEL_SELECTION
        ]

    @api.model
    def _matrix_mode_columns(self):
        return [
            {'key': key, 'label': _(label)}
            for key, label in SWITCHING_MODE_SELECTION
        ]

    @api.model
    def _matrix_aql_columns(self):
        return [
            {'key': self._matrix_aql_key(value), 'value': value, 'label': ('%g' % value)}
            for value in DEFAULT_AQL_VALUES
        ]

    @api.model
    def _matrix_aql_key(self, value):
        return ('%g' % float(value)).replace('.', '_')

    @api.model
    def _matrix_aql_value_from_key(self, key):
        return float(str(key).replace('_', '.'))

    @api.model
    def _default_lot_range_rows(self):
        return [
            {'lot_qty_min': 2, 'lot_qty_max': 8},
            {'lot_qty_min': 9, 'lot_qty_max': 15},
            {'lot_qty_min': 16, 'lot_qty_max': 25},
            {'lot_qty_min': 26, 'lot_qty_max': 50},
            {'lot_qty_min': 51, 'lot_qty_max': 90},
            {'lot_qty_min': 91, 'lot_qty_max': 150},
            {'lot_qty_min': 151, 'lot_qty_max': 280},
            {'lot_qty_min': 281, 'lot_qty_max': 500},
            {'lot_qty_min': 501, 'lot_qty_max': 1200},
            {'lot_qty_min': 1201, 'lot_qty_max': 3200},
            {'lot_qty_min': 3201, 'lot_qty_max': 10000},
            {'lot_qty_min': 10001, 'lot_qty_max': 35000},
            {'lot_qty_min': 35001, 'lot_qty_max': 150000},
            {'lot_qty_min': 150001, 'lot_qty_max': 500000},
            {'lot_qty_min': 500001, 'lot_qty_max': 999999999},
        ]

    @api.model
    def _default_plan_rows(self):
        return [
            {'sample_size_code': code, 'sample_size': size}
            for code, size in zip(DEFAULT_SAMPLE_SIZE_CODES, [2, 3, 5, 8, 13, 20, 32, 50, 80, 125, 200, 315, 500, 800, 1250, 2000])
        ]

    @api.model
    def action_open_sampling_matrix(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_quality.sampling_matrix',
            'name': _('AQL Sampling Matrix'),
        }

    @api.model
    def get_sampling_matrix_data(self, standard_id=False, switching_mode='normal'):
        standards = self.search([('active', '=', True)], order='code, id')
        standard = self.browse(standard_id).exists() if standard_id else standards[:1]
        if not standard:
            return {
                'standards': [],
                'standard_id': False,
                'switching_mode': switching_mode,
                'levels': self._matrix_level_columns(),
                'modes': self._matrix_mode_columns(),
                'aqls': self._matrix_aql_columns(),
                'lot_rows': self._default_lot_range_rows(),
                'plan_rows': self._default_plan_rows(),
            }

        lot_rows = []
        range_groups = {}
        for range_record in standard.lot_range_ids.sorted(lambda record: (record.lot_qty_min, record.lot_qty_max, record.id)):
            key = (range_record.lot_qty_min, range_record.lot_qty_max)
            row = range_groups.setdefault(key, {
                'lot_qty_min': range_record.lot_qty_min,
                'lot_qty_max': range_record.lot_qty_max,
                'codes': {},
            })
            row['codes'][range_record.inspection_level] = range_record.sample_size_code
        lot_rows = list(range_groups.values()) or self._default_lot_range_rows()
        for row in lot_rows:
            row.setdefault('codes', {})

        plan_rows = []
        plans = standard.plan_ids.filtered(lambda plan: plan.switching_mode == switching_mode)
        plan_groups = {}
        for plan in plans.sorted(lambda record: (record.sample_size_code, record.sample_size, record.aql_value, record.id)):
            row = plan_groups.setdefault(plan.sample_size_code, {
                'sample_size_code': plan.sample_size_code,
                'sample_size': plan.sample_size,
                'cells': {},
            })
            row['sample_size'] = plan.sample_size
            row['cells'][self._matrix_aql_key(plan.aql_value)] = {
                'accept_qty': plan.accept_qty,
                'reject_qty': plan.reject_qty,
            }
        plan_rows = list(plan_groups.values()) or self._default_plan_rows()
        for row in plan_rows:
            row.setdefault('cells', {})

        return {
            'standards': [{'id': item.id, 'display_name': item.display_name} for item in standards],
            'standard_id': standard.id,
            'switching_mode': switching_mode,
            'levels': self._matrix_level_columns(),
            'modes': self._matrix_mode_columns(),
            'aqls': self._matrix_aql_columns(),
            'lot_rows': lot_rows,
            'plan_rows': plan_rows,
        }

    @api.model
    def save_sampling_matrix_data(self, standard_id, switching_mode, lot_rows, plan_rows):
        standard = self.browse(standard_id).exists()
        if not standard:
            raise UserError(_('Select a sampling standard before saving.'))
        if switching_mode not in dict(SWITCHING_MODE_SELECTION):
            raise UserError(_('Select a valid switching mode.'))

        range_model = self.env['sn.wsd.quality.sampling.lot.range']
        plan_model = self.env['sn.wsd.quality.sampling.plan']

        existing_ranges = {
            (record.lot_qty_min, record.lot_qty_max, record.inspection_level): record
            for record in standard.lot_range_ids
        }
        seen_ranges = set()
        for row in lot_rows:
            lot_qty_min = int(row.get('lot_qty_min') or 0)
            lot_qty_max = int(row.get('lot_qty_max') or 0)
            codes = row.get('codes') or {}
            for level in dict(INSPECTION_LEVEL_SELECTION):
                code = (codes.get(level) or '').strip().upper()
                key = (lot_qty_min, lot_qty_max, level)
                if not code:
                    if key in existing_ranges:
                        existing_ranges[key].unlink()
                    continue
                seen_ranges.add(key)
                values = {
                    'standard_id': standard.id,
                    'inspection_level': level,
                    'lot_qty_min': lot_qty_min,
                    'lot_qty_max': lot_qty_max,
                    'sample_size_code': code,
                }
                if key in existing_ranges:
                    existing_ranges[key].write(values)
                else:
                    range_model.create(values)
        for key, record in existing_ranges.items():
            if key not in seen_ranges:
                record.unlink()

        existing_plans = {
            (record.sample_size_code, self._matrix_aql_key(record.aql_value)): record
            for record in standard.plan_ids.filtered(lambda plan: plan.switching_mode == switching_mode)
        }
        seen_plans = set()
        for row in plan_rows:
            code = (row.get('sample_size_code') or '').strip().upper()
            sample_size = int(row.get('sample_size') or 0)
            if not code or sample_size <= 0:
                continue
            cells = row.get('cells') or {}
            for aql_key, cell in cells.items():
                accept_qty = cell.get('accept_qty')
                reject_qty = cell.get('reject_qty')
                if accept_qty in (None, '') and reject_qty in (None, ''):
                    key = (code, aql_key)
                    if key in existing_plans:
                        existing_plans[key].unlink()
                    continue
                accept_qty = int(accept_qty or 0)
                reject_qty = int(reject_qty or 0)
                key = (code, aql_key)
                seen_plans.add(key)
                values = {
                    'standard_id': standard.id,
                    'switching_mode': switching_mode,
                    'sample_size_code': code,
                    'sample_size': sample_size,
                    'aql_value': self._matrix_aql_value_from_key(aql_key),
                    'accept_qty': accept_qty,
                    'reject_qty': reject_qty,
                }
                if key in existing_plans:
                    existing_plans[key].write(values)
                else:
                    plan_model.create(values)
        for key, record in existing_plans.items():
            if key not in seen_plans:
                record.unlink()

        return self.get_sampling_matrix_data(standard.id, switching_mode)


class QualitySamplingLotRange(models.Model):
    _name = 'sn.wsd.quality.sampling.lot.range'
    _description = 'WSD Quality Sampling Lot Range'
    _order = 'standard_id, lot_qty_min, inspection_level, id'
    _check_company_auto = True

    standard_id = fields.Many2one(
        'sn.wsd.quality.sampling.standard',
        string='Sampling Standard',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='standard_id.company_id',
        store=True,
        readonly=True,
    )
    inspection_level = fields.Selection(
        INSPECTION_LEVEL_SELECTION,
        string='Inspection Level',
        required=True,
        default='g2',
        index=True,
    )
    lot_qty_min = fields.Integer(string='From Quantity', required=True, default=1)
    lot_qty_max = fields.Integer(string='To Quantity', required=True, default=1)
    sample_size_code = fields.Char(string='Sample Size Code', required=True, index=True)

    _range_level_uniq = models.Constraint(
        'unique(standard_id, inspection_level, lot_qty_min, lot_qty_max)',
        'The lot range must be unique within one standard and inspection level.',
    )

    @api.constrains('lot_qty_min', 'lot_qty_max', 'sample_size_code')
    def _check_lot_range(self):
        for record in self:
            if record.lot_qty_min <= 0:
                raise ValidationError(_('The start quantity must be greater than zero.'))
            if record.lot_qty_max < record.lot_qty_min:
                raise ValidationError(_('The end quantity must be greater than or equal to the start quantity.'))
            if not (record.sample_size_code or '').strip():
                raise ValidationError(_('The sample size code is required.'))


class QualitySamplingPlan(models.Model):
    _name = 'sn.wsd.quality.sampling.plan'
    _description = 'WSD Quality Sampling Plan'
    _order = 'standard_id, switching_mode, sample_size_code, aql_value, id'
    _check_company_auto = True

    standard_id = fields.Many2one(
        'sn.wsd.quality.sampling.standard',
        string='Sampling Standard',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='standard_id.company_id',
        store=True,
        readonly=True,
    )
    switching_mode = fields.Selection(
        SWITCHING_MODE_SELECTION,
        string='Switching Mode',
        required=True,
        default='normal',
        index=True,
    )
    sample_size_code = fields.Char(string='Sample Size Code', required=True, index=True)
    sample_size = fields.Integer(string='Sample Size', required=True, default=1)
    aql_value = fields.Float(string='AQL', required=True, digits=(16, 3), index=True)
    accept_qty = fields.Integer(string='Accept Qty', required=True, default=0)
    reject_qty = fields.Integer(string='Reject Qty', required=True, default=1)

    _plan_uniq = models.Constraint(
        'unique(standard_id, switching_mode, sample_size_code, aql_value)',
        'The AQL sampling plan must be unique per standard, switching mode, sample code, and AQL.',
    )

    @api.constrains('sample_size', 'aql_value', 'accept_qty', 'reject_qty', 'sample_size_code')
    def _check_sampling_plan(self):
        for record in self:
            if not (record.sample_size_code or '').strip():
                raise ValidationError(_('The sample size code is required.'))
            if record.sample_size <= 0:
                raise ValidationError(_('The sample size must be greater than zero.'))
            if float_compare(record.aql_value, 0.0, precision_digits=6) < 0:
                raise ValidationError(_('AQL must be greater than or equal to zero.'))
            if record.accept_qty < 0 or record.reject_qty < 0:
                raise ValidationError(_('Accept and reject quantities must be greater than or equal to zero.'))
            if record.reject_qty <= record.accept_qty:
                raise ValidationError(_('Reject quantity must be greater than accept quantity.'))


class QualityInspectionScheme(models.Model):
    _inherit = 'sn.wsd.quality.inspection.scheme'

    sampling_method = fields.Selection(
        SAMPLING_METHOD_SELECTION,
        string='Sampling Method',
        required=True,
        default='fixed',
        tracking=True,
    )
    sampling_standard_id = fields.Many2one(
        'sn.wsd.quality.sampling.standard',
        string='Sampling Standard',
        check_company=True,
        tracking=True,
    )
    lot_qty_source = fields.Selection(
        LOT_QTY_SOURCE_SELECTION,
        string='Lot Quantity Source',
        required=True,
        default='manual',
        tracking=True,
    )
    inspection_level = fields.Selection(
        INSPECTION_LEVEL_SELECTION,
        string='Inspection Level',
        default='g2',
        tracking=True,
    )
    switching_mode = fields.Selection(
        SWITCHING_MODE_SELECTION,
        string='Switching Mode',
        default='normal',
        tracking=True,
    )
    aql_value = fields.Float(string='AQL', digits=(16, 3), default=1.0, tracking=True)
    sample_selection_method = fields.Selection(
        SAMPLE_SELECTION_METHOD_SELECTION,
        string='Sample Selection',
        required=True,
        default='systematic',
        tracking=True,
    )

    @api.constrains(
        'sampling_method',
        'sampling_standard_id',
        'lot_qty_source',
        'inspection_level',
        'switching_mode',
        'aql_value',
    )
    def _check_sampling_configuration(self):
        for scheme in self:
            if scheme.sampling_method == 'aql':
                if not scheme.sampling_standard_id:
                    raise ValidationError(_('A sampling standard is required for AQL sampling.'))
                if not scheme.inspection_level:
                    raise ValidationError(_('An inspection level is required for AQL sampling.'))
                if not scheme.switching_mode:
                    raise ValidationError(_('A switching mode is required for AQL sampling.'))
                if not scheme.lot_qty_source or scheme.lot_qty_source == 'manual':
                    raise ValidationError(_('A lot quantity source is required for AQL sampling.'))
                if float_compare(scheme.aql_value, 0.0, precision_digits=6) < 0:
                    raise ValidationError(_('AQL must be greater than or equal to zero.'))

    def _get_lot_qty_from_values(self, values):
        self.ensure_one()
        source = self.lot_qty_source
        if values.get('lot_qty'):
            return int(values['lot_qty'])
        if source == 'move_line':
            move_line = self.env['stock.move.line'].browse(values.get('move_line_id')).exists()
            return int(round(move_line.quantity)) if move_line else 0
        if source == 'picking_product':
            picking = self.env['stock.picking'].browse(values.get('picking_id')).exists()
            product = self.env['product.product'].browse(values.get('product_id')).exists()
            if not picking or not product:
                return 0
            lines = picking.move_line_ids.filtered(lambda line: line.product_id == product and line.quantity > 0)
            return int(round(sum(lines.mapped('quantity'))))
        if source == 'mes_order':
            mes_order = self.env['sn.wsd.mes.order'].browse(values.get('mes_order_id')).exists()
            if mes_order:
                serial_count = len(mes_order.internal_serial_ids.filtered(
                    lambda serial: serial.active and not serial.is_confirmed_scrapped()
                ))
                return serial_count or int(round(mes_order.planned_qty or 0.0))
            return 0
        if source == 'production':
            production = self.env['mrp.production'].browse(values.get('production_id')).exists()
            return int(round(production.product_qty)) if production else 0
        if source == 'workorder_output':
            workorder = self.env['mrp.workorder'].browse(values.get('workorder_id')).exists()
            return int(round(workorder.qty_produced or workorder.qty_production or 0.0)) if workorder else 0
        return int(values.get('lot_qty') or 0)

    def _get_aql_sampling_values(self, lot_qty):
        self.ensure_one()
        if lot_qty <= 0:
            raise UserError(_('Lot quantity must be greater than zero for AQL sampling.'))
        range_record = self.env['sn.wsd.quality.sampling.lot.range'].search([
            ('standard_id', '=', self.sampling_standard_id.id),
            ('inspection_level', '=', self.inspection_level),
            ('lot_qty_min', '<=', lot_qty),
            ('lot_qty_max', '>=', lot_qty),
        ], limit=1)
        if not range_record:
            raise UserError(_(
                'No AQL lot range was found for standard %(standard)s, level %(level)s, and lot quantity %(qty)s.',
                standard=self.sampling_standard_id.display_name,
                level=dict(INSPECTION_LEVEL_SELECTION).get(self.inspection_level),
                qty=lot_qty,
            ))
        plan = self.env['sn.wsd.quality.sampling.plan'].search([
            ('standard_id', '=', self.sampling_standard_id.id),
            ('switching_mode', '=', self.switching_mode),
            ('sample_size_code', '=', range_record.sample_size_code),
            ('aql_value', '=', self.aql_value),
        ], limit=1)
        if not plan:
            raise UserError(_(
                'No AQL plan was found for standard %(standard)s, mode %(mode)s, code %(code)s, and AQL %(aql)s.',
                standard=self.sampling_standard_id.display_name,
                mode=dict(SWITCHING_MODE_SELECTION).get(self.switching_mode),
                code=range_record.sample_size_code,
                aql=self.aql_value,
            ))
        sample_size = min(plan.sample_size, lot_qty)
        return {
            'lot_qty': lot_qty,
            'sampling_standard_id': self.sampling_standard_id.id,
            'lot_qty_source': self.lot_qty_source,
            'inspection_level': self.inspection_level,
            'switching_mode': self.switching_mode,
            'aql_value': self.aql_value,
            'sample_size_code': range_record.sample_size_code,
            'sample_size': sample_size,
            'accept_qty': plan.accept_qty,
            'reject_qty': plan.reject_qty,
        }

    def _prepare_sampling_values(self, values):
        self.ensure_one()
        sampling_method = values.get('sampling_method') or self.sampling_method
        base_values = {
            'sampling_method': sampling_method,
            'sample_selection_method': values.get('sample_selection_method') or self.sample_selection_method,
        }
        if sampling_method == 'aql':
            lot_qty = self._get_lot_qty_from_values(values)
            base_values.update(self._get_aql_sampling_values(lot_qty))
        elif sampling_method == 'full':
            lot_qty = self._get_lot_qty_from_values(values)
            sample_size = max(lot_qty, 1)
            base_values.update({
                'lot_qty': lot_qty,
                'lot_qty_source': self.lot_qty_source,
                'sample_size': sample_size,
                'accept_qty': 0,
                'reject_qty': 1,
            })
        else:
            base_values.update({
                'lot_qty': int(values.get('lot_qty') or 0),
                'lot_qty_source': self.lot_qty_source,
                'sample_size': values.get('sample_size') or self.sample_size,
                'accept_qty': values.get('accept_qty') if values.get('accept_qty') is not None else self.accept_qty,
                'reject_qty': values.get('reject_qty') if values.get('reject_qty') is not None else self.reject_qty,
            })
        return base_values


class QualityInspection(models.Model):
    _inherit = 'sn.wsd.quality.inspection'

    sampling_method = fields.Selection(
        SAMPLING_METHOD_SELECTION,
        string='Sampling Method',
        default='fixed',
        required=True,
        tracking=True,
    )
    sampling_standard_id = fields.Many2one(
        'sn.wsd.quality.sampling.standard',
        string='Sampling Standard',
        check_company=True,
        readonly=True,
    )
    lot_qty_source = fields.Selection(
        LOT_QTY_SOURCE_SELECTION,
        string='Lot Quantity Source',
        readonly=True,
    )
    lot_qty = fields.Integer(string='Lot Quantity', readonly=True)
    inspection_level = fields.Selection(
        INSPECTION_LEVEL_SELECTION,
        string='Inspection Level',
        readonly=True,
    )
    switching_mode = fields.Selection(
        SWITCHING_MODE_SELECTION,
        string='Switching Mode',
        readonly=True,
    )
    aql_value = fields.Float(string='AQL', digits=(16, 3), readonly=True)
    sample_size_code = fields.Char(string='Sample Size Code', readonly=True)
    sample_selection_method = fields.Selection(
        SAMPLE_SELECTION_METHOD_SELECTION,
        string='Sample Selection',
        default='systematic',
        required=True,
        tracking=True,
    )
    sample_ids = fields.One2many(
        'sn.wsd.quality.inspection.sample',
        'inspection_id',
        string='Samples',
    )
    sample_checked_qty = fields.Integer(string='Checked Samples', compute='_compute_sample_counts', store=True)
    sample_defect_qty = fields.Integer(string='Defect Samples', compute='_compute_sample_counts', store=True)

    @api.depends('sample_ids.result')
    def _compute_sample_counts(self):
        for inspection in self:
            checked_samples = inspection.sample_ids.filtered(lambda sample: sample.result in ('pass', 'fail'))
            inspection.sample_checked_qty = len(checked_samples)
            inspection.sample_defect_qty = len(checked_samples.filtered(lambda sample: sample.result == 'fail'))

    @api.depends(
        'state',
        'line_ids.result',
        'defect_line_ids.defect_qty',
        'sample_ids.result',
        'sample_size',
        'accept_qty',
        'reject_qty',
    )
    def _compute_result(self):
        super()._compute_result()
        for inspection in self.filtered(lambda record: record.inspection_type in ('iqc', 'oqc') and record.state == 'done'):
            defect_qty = inspection.sample_defect_qty if inspection.sample_ids else inspection.defect_qty
            if defect_qty >= inspection.reject_qty:
                inspection.result = 'reject'
            elif defect_qty <= inspection.accept_qty:
                inspection.result = 'pass'

    @api.model
    def create_from_scheme(self, scheme, values):
        if scheme and not hasattr(scheme, 'ids'):
            scheme = self.env['sn.wsd.quality.inspection.scheme'].browse(int(scheme)).exists()
        if not scheme:
            raise UserError(_('No effective inspection scheme was found.'))
        values = dict(values)
        sampling_values = scheme._prepare_sampling_values(values)
        values.update({
            'inspection_type': scheme.inspection_type,
            'scheme_id': scheme.id,
            'company_id': values.get('company_id') or scheme.company_id.id,
            'line_ids': self._line_commands_from_scheme(scheme),
        })
        for key, value in sampling_values.items():
            values.setdefault(key, value)
        inspection = self.create(values)
        inspection._ensure_sample_units()
        return inspection

    def _get_candidate_sample_serials(self):
        self.ensure_one()
        serial_model = self.env['sn.wsd.internal.serial'].with_context(active_test=False)
        domain = [('active', '=', True)]
        if self.mes_order_id:
            domain.append(('mes_order_id', '=', self.mes_order_id.id))
        elif self.production_id:
            domain.append(('production_id', '=', self.production_id.id))
        else:
            return serial_model
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        return serial_model.search(domain, order='serial_no, id')

    def _select_systematic_serials(self, candidates, sample_size):
        if not candidates or sample_size <= 0:
            return candidates.browse()
        if len(candidates) <= sample_size:
            return candidates
        selected = self.env['sn.wsd.internal.serial']
        step = len(candidates) / float(sample_size)
        used_indexes = set()
        for index in range(sample_size):
            candidate_index = min(int(index * step), len(candidates) - 1)
            while candidate_index in used_indexes and candidate_index + 1 < len(candidates):
                candidate_index += 1
            used_indexes.add(candidate_index)
            selected |= candidates[candidate_index]
        return selected

    def _sample_commands_from_serials(self, serials):
        self.ensure_one()
        commands = []
        for sequence, serial in enumerate(serials, 1):
            commands.append(Command.create({
                'sequence': sequence,
                'company_id': self.company_id.id,
                'internal_serial_id': serial.id,
                'lot_id': serial.lot_id.id if 'lot_id' in serial._fields else False,
            }))
        return commands

    def _sample_commands_from_placeholders(self):
        self.ensure_one()
        return [
            Command.create({
                'sequence': sequence,
                'company_id': self.company_id.id,
                'lot_id': self.lot_id.id,
            })
            for sequence in range(1, self.sample_size + 1)
        ]

    def _ensure_sample_units(self):
        for inspection in self.filtered(lambda record: not record.sample_ids and record.sample_size > 0):
            if inspection.sample_selection_method == 'manual':
                continue
            serials = inspection._select_systematic_serials(
                inspection._get_candidate_sample_serials(),
                inspection.sample_size,
            )
            if serials:
                inspection.write({'sample_ids': inspection._sample_commands_from_serials(serials)})
            elif inspection.inspection_type in ('iqc', 'oqc'):
                inspection.write({'sample_ids': inspection._sample_commands_from_placeholders()})

    def action_done(self):
        for inspection in self:
            missing = inspection.line_ids.filtered(lambda line: line.required and line.result == 'pending')
            if missing:
                raise UserError(_('Complete all required inspection items before finishing the inspection.'))
            if inspection.inspection_type in ('iqc', 'oqc') and inspection.sample_checked_qty < inspection.sample_size:
                raise UserError(_('Complete all required samples before finishing the inspection.'))
            if inspection.inspection_type == 'oqc' and inspection.defect_line_ids.filtered(lambda line: not line.defect_code_id):
                raise UserError(_('Defect code is required on every OQC defect line.'))
            if inspection.inspection_type in ('iqc', 'oqc') and inspection.sample_ids.filtered(lambda sample: sample.result == 'fail' and not sample.defect_code_id):
                raise UserError(_('Defect code is required on every failed sample.'))
        self.write({
            'state': 'done',
            'finish_time': fields.Datetime.now(),
        })
        self._apply_quality_hold()
        return True

    def action_set_all_pass(self):
        result = super().action_set_all_pass()
        self.mapped('sample_ids').filtered(lambda sample: sample.result == 'pending').write({'result': 'pass'})
        return result


class QualityInspectionSample(models.Model):
    _name = 'sn.wsd.quality.inspection.sample'
    _description = 'WSD Quality Inspection Sample'
    _order = 'inspection_id, sequence, id'
    _check_company_auto = True

    name = fields.Char(
        string='Sample No.',
        default=lambda self: _('New'),
        readonly=True,
        copy=False,
        index=True,
    )
    sequence = fields.Integer(default=10)
    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection',
        string='Inspection',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Serial Number',
        check_company=True,
        index=True,
    )
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number', check_company=True, index=True)
    result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('fail', 'Fail'),
            ('skipped', 'Skipped'),
        ],
        string='Result',
        default='pending',
        required=True,
        index=True,
    )
    defect_code_id = fields.Many2one('sn.wsd.quality.defect.code', string='Defect Code', check_company=True)
    note = fields.Char(string='Notes')

    _sample_serial_uniq = models.Constraint(
        'unique(inspection_id, internal_serial_id)',
        'The same serial number can only be sampled once in one inspection.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.quality.inspection.sample') or _('New')
            if not vals.get('company_id') and vals.get('inspection_id'):
                inspection = self.env['sn.wsd.quality.inspection'].browse(vals['inspection_id']).exists()
                vals['company_id'] = inspection.company_id.id
        return super().create(vals_list)

    def action_set_pass(self):
        self.write({'result': 'pass'})
        return True

    def action_set_fail(self):
        self.write({'result': 'fail'})
        return True

    @api.constrains('inspection_id', 'company_id', 'internal_serial_id', 'lot_id', 'defect_code_id')
    def _check_sample_company(self):
        for sample in self:
            if sample.inspection_id.company_id != sample.company_id:
                raise ValidationError(_('The sample must belong to the same company as the inspection.'))
            related_records = [sample.internal_serial_id, sample.lot_id, sample.defect_code_id]
            for record in related_records:
                if record and record.company_id and record.company_id != sample.company_id:
                    raise ValidationError(_('Sample related records must belong to the same company.'))

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MeterQualityDefectCode(models.Model):
    _name = 'sn.wsd.quality.defect.code'
    _description = 'Meter Quality Defect Code'
    _order = 'category, code, id'
    _check_company_auto = True

    name = fields.Char(string='Defect Name', required=True)
    code = fields.Char(string='Defect Code', required=True, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    category = fields.Selection(
        [
            ('appearance', 'Appearance'),
            ('assembly', 'Assembly'),
            ('programming', 'Programming'),
            ('calibration', 'Calibration'),
            ('communication', 'Communication'),
            ('hipot', 'Hipot'),
            ('aging', 'Aging'),
            ('packaging', 'Packaging'),
            ('material', 'Material'),
            ('other', 'Other'),
        ],
        string='Category',
        required=True,
        default='other',
        index=True,
    )
    station_type = fields.Selection(
        [
            ('assembly', 'Assembly'),
            ('programming', 'Programming'),
            ('inspection', 'Inspection'),
            ('aging', 'Aging'),
            ('calibration', 'Calibration'),
            ('final_test', 'Final Test'),
            ('packaging', 'Packaging'),
            ('repair', 'Repair'),
        ],
        string='Station Type',
        index=True,
    )
    severity = fields.Selection(
        [
            ('minor', 'Minor'),
            ('major', 'Major'),
            ('critical', 'Critical'),
        ],
        string='Severity',
        required=True,
        default='major',
        index=True,
    )
    description = fields.Text(string='Description')
    root_cause_hint = fields.Text(string='Root Cause Hint')
    scrap_recommended = fields.Boolean(string='Scrap Recommended')

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The defect code must be unique per company.',
    )


class MeterQualityIssue(models.Model):
    _name = 'sn.wsd.quality.issue'
    _description = 'Meter Quality Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Issue Reference',
        default=lambda self: _('New'),
        readonly=True,
        copy=False,
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    internal_serial_id = fields.Many2one(
        'sn.wsd.internal.serial',
        string='Meter Serial',
        required=True,
        index=True,
        check_company=True,
        tracking=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='internal_serial_id.production_id',
        store=True,
        readonly=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='internal_serial_id.mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation',
        string='Route Operation',
        check_company=True,
        index=True,
        tracking=True,
    )
    test_result_id = fields.Many2one(
        'sn.wsd.mes.test.result',
        string='MES Test Result',
        check_company=True,
        index=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='MES Work Center',
        check_company=True,
        index=True,
    )
    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection',
        string='Quality Inspection',
        check_company=True,
        index=True,
    )
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='Defect Code',
        required=True,
        check_company=True,
        tracking=True,
    )
    severity = fields.Selection(
        related='defect_code_id.severity',
        string='Severity',
        store=True,
        readonly=True,
    )
    category = fields.Selection(
        related='defect_code_id.category',
        string='Category',
        store=True,
        readonly=True,
    )
    issue_source = fields.Selection(
        [
            ('test_result', 'Test Result'),
            ('manual', 'Manual'),
            ('repair', 'Repair'),
            ('oqc', 'OQC'),
            ('fqc', 'FQC'),
            ('fai', 'FAI'),
            ('iqc', 'IQC'),
            ('ipqc', 'IPQC'),
        ],
        string='Issue Source',
        required=True,
        default='manual',
        index=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ('open', 'Open'),
            ('analysis', 'Analysis'),
            ('repairing', 'Repairing'),
            ('verified', 'Verified'),
            ('closed', 'Closed'),
            ('scrapped', 'Scrapped'),
        ],
        string='Status',
        required=True,
        default='open',
        tracking=True,
        index=True,
    )
    root_cause = fields.Text(string='Root Cause')
    repair_action = fields.Text(string='Repair Action')
    disposition = fields.Selection(
        [
            ('rework', 'Rework'),
            ('use_as_is', 'Use As Is'),
            ('scrap', 'Scrap'),
            ('return_material', 'Return Material'),
        ],
        string='Disposition',
        default='rework',
        tracking=True,
    )
    responsible_user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        tracking=True,
    )
    detected_time = fields.Datetime(
        string='Detected Time',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )
    verified_time = fields.Datetime(
        string='Verified Time',
        tracking=True,
    )
    closed_time = fields.Datetime(
        string='Closed Time',
        tracking=True,
    )
    note = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.quality.issue') or _('New')
        records = super().create(vals_list)
        records._sync_meter_quality_state()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._sync_meter_quality_state()
        return result

    def _sync_meter_quality_state(self):
        for issue in self:
            meter = issue.internal_serial_id
            if not meter:
                continue
            open_issues = meter.quality_issue_ids.filtered(lambda item: item.state not in ('closed', 'scrapped'))
            if open_issues:
                meter.x_quality_hold_state = 'hold'
                if meter.final_result == 'pass':
                    meter.final_result = 'hold'
            else:
                if meter.x_quality_hold_state == 'hold':
                    meter.x_quality_hold_state = 'released'
                if meter.final_result == 'hold':
                    meter.final_result = 'pass'

    def action_start_analysis(self):
        self.write({'state': 'analysis'})
        return True

    def action_start_repair(self):
        self.write({'state': 'repairing'})
        return True

    def action_verify(self):
        self.write({
            'state': 'verified',
            'verified_time': fields.Datetime.now(),
        })
        return True

    def action_close(self):
        self.write({
            'state': 'closed',
            'closed_time': fields.Datetime.now(),
        })
        return True

    def action_scrap(self):
        self.write({
            'state': 'scrapped',
            'disposition': 'scrap',
            'closed_time': fields.Datetime.now(),
        })
        self.internal_serial_id.write({
            'state': 'scrapped',
            'final_result': 'scrap',
            'x_quality_hold_state': 'scrapped',
        })
        return True


class InternalSerial(models.Model):
    _inherit = 'sn.wsd.internal.serial'

    quality_issue_ids = fields.One2many(
        'sn.wsd.quality.issue',
        'internal_serial_id',
        string='Quality Issues',
    )
    quality_issue_count = fields.Integer(
        string='Quality Issue Count',
        compute='_compute_quality_issue_summary',
    )
    open_quality_issue_count = fields.Integer(
        string='Open Quality Issue Count',
        compute='_compute_quality_issue_summary',
    )
    x_quality_hold_state = fields.Selection(
        [
            ('released', 'Released'),
            ('hold', 'Quality Hold'),
            ('blocked', 'Blocked'),
            ('scrapped', 'Scrapped'),
        ],
        string='Quality Hold State',
        default='released',
        index=True,
    )
    x_fqc_status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('passed', 'Passed'),
            ('failed', 'Failed'),
            ('waived', 'Waived'),
        ],
        string='FQC Status',
        default='pending',
        index=True,
    )
    x_oqc_status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('passed', 'Passed'),
            ('failed', 'Failed'),
            ('waived', 'Waived'),
        ],
        string='OQC Status',
        default='pending',
        index=True,
    )

    def _compute_quality_issue_summary(self):
        for record in self:
            open_issues = record.quality_issue_ids.filtered(lambda item: item.state not in ('closed', 'scrapped'))
            record.quality_issue_count = len(record.quality_issue_ids)
            record.open_quality_issue_count = len(open_issues)

    def action_view_quality_issues(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quality Issues'),
            'res_model': 'sn.wsd.quality.issue',
            'view_mode': 'list,form',
            'domain': [('internal_serial_id', '=', self.id)],
            'context': {
                'default_internal_serial_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_mark_fqc_passed(self):
        self.write({'x_fqc_status': 'passed'})
        return True

    def action_mark_fqc_failed(self):
        self.write({
            'x_fqc_status': 'failed',
            'x_quality_hold_state': 'hold',
        })
        return True

    def action_mark_oqc_passed(self):
        self.write({'x_oqc_status': 'passed'})
        return True

    def action_mark_oqc_failed(self):
        self.write({
            'x_oqc_status': 'failed',
            'x_quality_hold_state': 'hold',
        })
        return True


class MesTestResult(models.Model):
    _inherit = 'sn.wsd.mes.test.result'

    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code',
        string='Defect Code',
        check_company=True,
        index=True,
    )
    quality_issue_ids = fields.One2many(
        'sn.wsd.quality.issue',
        'test_result_id',
        string='Quality Issues',
    )
    quality_issue_count = fields.Integer(
        string='Quality Issue Count',
        compute='_compute_quality_issue_count',
    )

    def _compute_quality_issue_count(self):
        for record in self:
            record.quality_issue_count = len(record.quality_issue_ids)

    @api.model
    def _find_default_defect_code(self, test_result):
        domain = [('company_id', '=', test_result.company_id.id)]
        route_operation = test_result.route_operation_id.operation_id if test_result.route_operation_id else self.env['mrp.routing.workcenter']
        if route_operation and route_operation.x_station_type:
            domain.append(('station_type', '=', route_operation.x_station_type))
        return self.env['sn.wsd.quality.defect.code'].search(domain, order='severity desc, id asc', limit=1)

    def _create_quality_issue_from_failure(self):
        issue_model = self.env['sn.wsd.quality.issue']
        for record in self:
            if record.result != 'fail' or not record.internal_serial_id:
                continue
            internal_serial = record.internal_serial_id
            existing = issue_model.search([
                ('test_result_id', '=', record.id),
            ], limit=1)
            if existing:
                continue
            defect_code = record.defect_code_id or self._find_default_defect_code(record)
            if not defect_code:
                continue
            issue_model.create({
                'internal_serial_id': internal_serial.id,
                'route_operation_id': record.route_operation_id.id,
                'test_result_id': record.id,
                'workcenter_id': record.workcenter_id.id,
                'defect_code_id': defect_code.id,
                'issue_source': 'test_result',
                'state': 'open',
                'detected_time': record.test_time,
                'note': record.note,
            })

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._create_quality_issue_from_failure()
        return records


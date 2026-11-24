from odoo import api, fields, models

from .eip_push import C, F, K, N, T

# Field list of one scheduled work order row (the first push may leave
# the scheduled amount empty per the interface description)
SCHEDULE_WO_SPEC = (
    F('batchCode', 'batch_code', add=True),
    F('scheduleWo', 'schedule_wo', add=True),
    F('matCode', 'mat_code', add=True),
    F('matDesc', 'mat_desc', add=True),
    F('scheduleAmount', 'schedule_amount'),
    F('scheduleUnit', 'schedule_unit', add=True),
    F('remark', 'remark'),
    N('processList', 'process_ids', PROCESS_SPEC := (
        F('processCode', 'process_code', add=True),
        F('processName', 'process_name', add=True),
        F('planStartDate', 'plan_start_date', add=True),
        F('planFinishDate', 'plan_finish_date', add=True),
        F('actualStartDate', 'actual_start_date'),
        F('actualFinishDate', 'actual_finish_date'),
        F('remark', 'remark'),
    )),
)


class EipSchedule(models.Model):
    """Production schedule pushed to the EIP platform: the short-term
    plan of one grid purchase order line, with its scheduled work
    orders and their processes below it."""
    _name = 'sn.wsd.eip.schedule'
    _description = 'EIP Production Schedule'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'schedule_code desc, id desc'
    _check_company_auto = True

    EIP_INTERFACE = 'schedule'
    EIP_SEQUENCE = 'sn.wsd.eip.schedule'
    EIP_NUMBER_FIELD = 'schedule_code'
    # the first push may leave the plan dates and duration empty per
    # the interface description, so they carry no ADD flag
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True, update=True),
        F('poItemId', 'po_item_id', add=True, update=True),
        F('scheduleCode', 'schedule_code', add=True, update=True),
        F('provCoCode', 'prov_co_code'),
        F('provCoName', 'prov_co_name'),
        F('planPeriod', 'plan_period'),
        F('actualPeriod', 'actual_period'),
        F('schedule', 'progress'),
        F('dueDate', 'due_date', add=True),
        F('planStartDate', 'plan_start_date'),
        F('planFinishDate', 'plan_finish_date'),
        F('actualStartDate', 'actual_start_date'),
        F('actualFinishDate', 'actual_finish_date'),
        F('categoryCode', 'category_id.code', add=True),
        F('subclassCode', 'subclass_id.code', add=True),
        F('remark', 'remark'),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
        N('woList', 'wo_ids', SCHEDULE_WO_SPEC),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    po_item_id = fields.Char(
        string='Grid Purchase Order Line ID', required=True, index=True)
    schedule_code = fields.Char(
        string='Schedule Code', required=True, index=True,
        copy=False, default=lambda self: self._eip_new_number())
    prov_co_code = fields.Char(string='Provincial Company Code')
    prov_co_name = fields.Char(string='Provincial Company Name')
    plan_period = fields.Char(string='Planned Duration (days)')
    actual_period = fields.Char(string='Actual Duration')
    progress = fields.Char(
        string='Progress', help='Percentage of completion.')
    due_date = fields.Date(string='Delivery Date')
    plan_start_date = fields.Date(string='Planned Start')
    plan_finish_date = fields.Date(string='Planned Finish')
    actual_start_date = fields.Date(string='Actual Start')
    actual_finish_date = fields.Date(string='Actual Finish')
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_category_id'))
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_subclass_id'))
    remark = fields.Char(string='Remark')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')
    wo_ids = fields.One2many(
        'sn.wsd.eip.schedule.wo', 'schedule_id', string='Scheduled Work Orders')

    _schedule_uniq = models.Constraint(
        'unique(company_id, schedule_code, po_item_id)',
        'The schedule code must be unique per purchase order line.',
    )

    def _eip_document_ref(self):
        self.ensure_one()
        return self.schedule_code


class EipScheduleWo(models.Model):
    """One work order row of a production schedule."""
    _name = 'sn.wsd.eip.schedule.wo'
    _description = 'EIP Schedule Work Order'
    _inherit = 'sn.wsd.eip.push.line.mixin'
    _order = 'schedule_wo, id'
    _check_company_auto = True

    EIP_LINES = SCHEDULE_WO_SPEC
    EIP_PARENT_FIELD = 'schedule_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    schedule_id = fields.Many2one(
        'sn.wsd.eip.schedule', string='Schedule', required=True,
        index=True, ondelete='cascade', check_company=True)
    batch_code = fields.Char(string='Schedule Batch No.')
    schedule_wo = fields.Char(string='Scheduled Work Order No.')
    mat_code = fields.Char(string='Material Code')
    mat_desc = fields.Char(string='Material Description')
    schedule_amount = fields.Char(string='Scheduled Quantity')
    schedule_unit = fields.Char(string='Unit of Measure')
    remark = fields.Char(string='Remark')
    process_ids = fields.One2many(
        'sn.wsd.eip.schedule.process', 'schedule_wo_id', string='Processes')


class EipScheduleProcess(models.Model):
    """One process row of a scheduled work order; changes queue the
    schedule itself (the pushed root)."""
    _name = 'sn.wsd.eip.schedule.process'
    _description = 'EIP Schedule Process'
    _inherit = 'sn.wsd.eip.push.line.mixin'
    _order = 'process_code, id'
    _check_company_auto = True

    EIP_LINES = PROCESS_SPEC
    EIP_PARENT_FIELD = 'schedule_wo_id'
    EIP_PUSH_ROOT_FIELD = 'schedule_wo_id.schedule_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    schedule_wo_id = fields.Many2one(
        'sn.wsd.eip.schedule.wo', string='Scheduled Work Order',
        required=True, index=True, ondelete='cascade', check_company=True)
    process_code_id = fields.Many2one(
        'sn.wsd.eip.process.code', string='Process Code',
        help='Picks the code; it is copied into the payload key and can '
             'also be typed freely.')
    process_code = fields.Char(string='Process Code')
    process_name = fields.Char(string='Process Name')
    plan_start_date = fields.Date(string='Planned Start')
    plan_finish_date = fields.Date(string='Planned Finish')
    actual_start_date = fields.Date(string='Actual Start')
    actual_finish_date = fields.Date(string='Actual Finish')
    remark = fields.Char(string='Remark')

    @api.onchange('process_code_id')
    def _onchange_process_code_id(self):
        if self.process_code_id:
            self.process_code = self.process_code_id.code
            if not self.process_name:
                self.process_name = self.process_code_id.name

import logging
from datetime import timedelta

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class QualityInspectionScheme(models.Model):
    _name = 'sn.wsd.quality.inspection.scheme'
    _description = 'WSD Quality Inspection Scheme'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'inspection_type, code, id'
    _check_company_auto = True

    name = fields.Char(string='Scheme Name', required=True, tracking=True)
    code = fields.Char(string='Scheme Code', required=True, index=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    inspection_type = fields.Selection(
        [
            ('fai', 'FAI - First Article Inspection'),
            ('iqc', 'IQC - Incoming Quality Control'),
            ('ipqc', 'IPQC - In-Process Quality Control'),
            ('oqc', 'OQC - Outgoing Quality Control'),
        ],
        string='Inspection Type',
        required=True,
        default='fai',
        index=True,
        tracking=True,
    )
    product_tmpl_ids = fields.Many2many(
        'product.template',
        'sn_wsd_quality_inspection_scheme_product_tmpl_rel',
        'scheme_id',
        'product_tmpl_id',
        string='Products',
        check_company=True,
    )
    product_categ_ids = fields.Many2many(
        'product.category',
        'sn_wsd_quality_inspection_scheme_product_categ_rel',
        'scheme_id',
        'categ_id',
        string='Product Categories',
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Legacy Product Template',
        check_company=True,
        index=True,
        copy=False,
    )
    operation_id = fields.Many2one(
        'sn.wsd.operation',
        string='Operation',
        check_company=True,
        index=True,
        help='Operation scope of the scheme. FAI: the first-article station '
             'samples must leave with an OK result; IPQC: the patrolled '
             'operation; OQC: the trigger-point operation. Not used by IQC '
             '(incoming material has no route).',
    )
    production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='Production Line',
        check_company=True,
        index=True,
    )
    interval_minutes = fields.Integer(string='Inspection Interval (Minutes)', default=60)
    sample_size = fields.Integer(string='Sample Size', default=1)
    accept_qty = fields.Integer(string='Accept Qty', default=0)
    reject_qty = fields.Integer(string='Reject Qty', default=1)
    responsible_user_id = fields.Many2one('res.users', string='Responsible')
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('effective', 'Effective'),
            ('obsolete', 'Obsolete'),
        ],
        string='Status',
        required=True,
        default='draft',
        tracking=True,
        index=True,
    )
    line_ids = fields.One2many(
        'sn.wsd.quality.inspection.scheme.line',
        'scheme_id',
        string='Inspection Items',
    )
    item_group_ids = fields.Many2many(
        'sn.wsd.quality.inspection.item.group',
        'sn_wsd_quality_inspection_scheme_item_group_rel',
        'scheme_id',
        'group_id',
        string='Inspection Item Groups',
        check_company=True,
    )
    note = fields.Text(string='Notes')

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The inspection scheme code must be unique per company.',
    )

    @api.constrains('inspection_type', 'operation_id')
    def _check_operation_scope(self):
        # QMS §1.1 方案维度=类别/工序/成品；除来料检外必有工序
        for scheme in self:
            if scheme.inspection_type != 'iqc' and not scheme.operation_id:
                raise ValidationError(_(
                    'Inspection schemes of type %(type)s require an '
                    'operation.', type=scheme.inspection_type))

    @api.constrains('interval_minutes', 'sample_size', 'accept_qty', 'reject_qty')
    def _check_scheme_numbers(self):
        for scheme in self:
            if scheme.interval_minutes <= 0:
                raise ValidationError(_('Inspection interval must be greater than zero.'))
            if scheme.sample_size <= 0:
                raise ValidationError(_('Sample size must be greater than zero.'))
            if scheme.accept_qty < 0 or scheme.reject_qty < 0:
                raise ValidationError(_('Accept and reject quantities must be greater than or equal to zero.'))
            if scheme.reject_qty and scheme.accept_qty > scheme.reject_qty:
                raise ValidationError(_('Accept quantity must be less than or equal to reject quantity.'))

    def action_set_effective(self):
        self.write({'state': 'effective'})
        return True

    def action_set_obsolete(self):
        self.write({'state': 'obsolete'})
        return True

    # ------------------------------------------------------------------
    # 定时巡检引擎（add-mes-ipqc-patrol V1）：活动驱动开单
    # ------------------------------------------------------------------
    def _ipqc_patrol_tick(self):
        """每小时由 ir.cron 调用：对每张生效 ipqc 方案按(产线×工序)判定
        ——到期（距上次巡检 ≥ 间隔）且自锚点后有产出活动（过站∪报工）
        才开单；停线/无产出不开；方案未配产线=该工序有活动的产线逐线开。
        锚点=该(方案,产线)最近一张巡检单的 scheduled_time（open 单在等
        视为本周期已覆盖，不重复开）。"""
        Inspection = self.env['sn.wsd.quality.inspection']
        History = self.env['sn.wsd.serial.operation.history']
        Report = self.env['sn.wsd.mes.operation.report']
        now = fields.Datetime.now()
        created = Inspection
        for scheme in self.search([
                ('inspection_type', '=', 'ipqc'),
                ('state', '=', 'effective'),
                ('operation_id', '!=', False)]):
            op = scheme.operation_id
            interval = timedelta(minutes=scheme.interval_minutes or 60)
            lines = scheme.production_line_id
            if not lines:
                # 该工序近一个间隔内有活动的产线（发现候选线）
                groups = History._read_group(
                    [('route_operation_id.operation_id', '=', op.id),
                     ('out_date', '>', now - interval)],
                    groupby=['mes_order_id.production_line_id'],
                    aggregates=['id:count'],
                )
                report_groups = Report._read_group(
                    [('route_operation_id.operation_id', '=', op.id),
                     ('create_date', '>', now - interval)],
                    groupby=['mes_order_id.production_line_id'],
                    aggregates=['id:count'],
                )
                line_ids = {g[0].id for g in groups if g[0]}                     | {g[0].id for g in report_groups if g[0]}
                lines = self.env['sn.mrp.production.line'].browse(line_ids)
            for line in lines:
                last = Inspection.search([
                    ('inspection_type', '=', 'ipqc'),
                    ('scheme_id', '=', scheme.id),
                    ('production_line_id', '=', line.id),
                ], order='scheduled_time desc', limit=1)
                if last and last.state in ('open', 'in_progress'):
                    continue  # 有单在等：本周期已覆盖
                anchor_time = last.scheduled_time if last                     else now - interval
                if now - anchor_time < interval:
                    continue  # 未到期
                activity = History.search_count([
                    ('route_operation_id.operation_id', '=', op.id),
                    ('mes_order_id.production_line_id', '=', line.id),
                    ('out_date', '>', anchor_time),
                ]) or Report.search_count([
                    ('route_operation_id.operation_id', '=', op.id),
                    ('mes_order_id.production_line_id', '=', line.id),
                    ('create_date', '>', anchor_time),
                ])
                if not activity:
                    continue  # 停线/换线间隙：无产出不开单
                inspection = Inspection.create_from_scheme(scheme, {
                    'production_line_id': line.id,
                    'scheduled_time': now,
                })
                inspection.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=(scheme.responsible_user_id
                             or self.env.user).id,
                    summary=_('Patrol inspection due'),
                    note=_('Patrol inspection of %(op)s on line %(line)s '
                           'is due; sample hint: %(count)s.',
                           op=op.display_name, line=line.display_name,
                           count=inspection.sample_size),
                )
                created |= inspection
        return created

    def action_set_draft(self):
        self.write({'state': 'draft'})
        return True

    @api.onchange('item_group_ids')
    def _onchange_item_group_ids(self):
        for scheme in self:
            scheme._append_lines_from_item_groups()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record, vals in zip(records, vals_list):
            if vals.get('item_group_ids'):
                record._append_lines_from_item_groups()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'item_group_ids' in vals:
            self._append_lines_from_item_groups()
        return result

    def _append_lines_from_item_groups(self):
        for scheme in self:
            commands = scheme._line_commands_from_item_groups()
            if commands:
                scheme.update({'line_ids': commands})
        return True

    def _line_commands_from_item_groups(self):
        self.ensure_one()
        existing_codes = {
            code
            for code in self.line_ids.mapped('item_code')
            if code
        }
        next_sequence = max(self.line_ids.mapped('sequence') or [0])
        commands = []
        group_lines = self.item_group_ids.line_ids.sorted(lambda line: (line.group_id.sequence, line.sequence, line.id))
        for group_line in group_lines.filtered(lambda line: line.item_id.active):
            item = group_line.item_id
            if item.code in existing_codes:
                continue
            next_sequence += 10
            values = self.env['sn.wsd.quality.inspection.scheme.line']._item_snapshot_values(item)
            values.update({
                'sequence': next_sequence,
                'item_id': item.id,
            })
            commands.append(Command.create(values))
            existing_codes.add(item.code)
        return commands

    def _matches_product_scope(self, product):
        self.ensure_one()
        scoped_by_product = bool(self.product_tmpl_ids or self.product_tmpl_id)
        scoped_by_category = bool(self.product_categ_ids)
        if not product:
            return not scoped_by_product and not scoped_by_category
        template = product.product_tmpl_id
        if self.product_tmpl_ids and template not in self.product_tmpl_ids:
            return False
        if self.product_tmpl_id and template != self.product_tmpl_id:
            return False
        if self.product_categ_ids:
            category = template.categ_id
            if not category:
                return False
            matching_categories = self.env['product.category'].search([
                ('id', 'child_of', self.product_categ_ids.ids),
            ])
            if category not in matching_categories:
                return False
        return True

    def _product_scope_score(self, product):
        self.ensure_one()
        if product and (self.product_tmpl_ids or self.product_tmpl_id):
            return 20
        if product and self.product_categ_ids:
            return 10
        return 0


class QualityInspectionSchemeLine(models.Model):
    _name = 'sn.wsd.quality.inspection.scheme.line'
    _description = 'WSD Quality Inspection Scheme Item'
    _order = 'scheme_id, sequence, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    scheme_id = fields.Many2one(
        'sn.wsd.quality.inspection.scheme',
        string='Inspection Scheme',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='scheme_id.company_id',
        store=True,
        readonly=True,
    )
    item_id = fields.Many2one(
        'sn.wsd.quality.inspection.item',
        string='Inspection Item',
        check_company=True,
    )
    name = fields.Char(string='Item Name', required=True)
    item_code = fields.Char(string='Item Code', required=True)
    item_type = fields.Selection(
        [
            ('numeric', 'Numeric'),
            ('pass_fail', 'Pass or Fail'),
            ('selection', 'Selection'),
            ('text', 'Text'),
        ],
        string='Item Type',
        required=True,
        default='pass_fail',
    )
    required = fields.Boolean(string='Required', default=True)
    lower_limit = fields.Float(string='Lower Limit')
    upper_limit = fields.Float(string='Upper Limit')
    expected_value = fields.Char(string='Expected Value')
    selection_values = fields.Char(string='Allowed Values')
    unit = fields.Char(string='Unit')
    instruction = fields.Text(string='Instruction')

    _plan_item_code_uniq = models.Constraint(
        'unique(scheme_id, item_code)',
        'The inspection item code must be unique within one scheme.',
    )

    @api.onchange('item_id')
    def _onchange_item_id(self):
        for line in self:
            if line.item_id:
                line._apply_item_values(line.item_id)

    @api.model_create_multi
    def create(self, vals_list):
        self._complete_item_values(vals_list)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if vals.get('item_id'):
            item = self.env['sn.wsd.quality.inspection.item'].browse(vals['item_id']).exists()
            if item:
                snapshot_values = self._item_snapshot_values(item)
                snapshot_values.update(vals)
                vals = snapshot_values
        return super().write(vals)

    @api.model
    def _complete_item_values(self, vals_list):
        item_ids = {vals.get('item_id') for vals in vals_list if vals.get('item_id')}
        item_by_id = {
            item.id: item
            for item in self.env['sn.wsd.quality.inspection.item'].browse(item_ids).exists()
        }
        for vals in vals_list:
            item = item_by_id.get(vals.get('item_id'))
            if item:
                for key, value in self._item_snapshot_values(item).items():
                    vals.setdefault(key, value)

    @api.model
    def _item_snapshot_values(self, item):
        return {
            'name': item.name,
            'item_code': item.code,
            'item_type': item.item_type,
            'required': item.required,
            'lower_limit': item.lower_limit,
            'upper_limit': item.upper_limit,
            'expected_value': item.expected_value,
            'selection_values': item.selection_values,
            'unit': item.unit,
            'instruction': item.instruction,
        }

    def _apply_item_values(self, item):
        self.ensure_one()
        values = self._item_snapshot_values(item)
        for field_name, value in values.items():
            self[field_name] = value

    @api.constrains('item_type', 'lower_limit', 'upper_limit')
    def _check_numeric_limits(self):
        for line in self.filtered(lambda item: item.item_type == 'numeric'):
            if float_compare(line.lower_limit, line.upper_limit, precision_rounding=0.0001) > 0:
                raise ValidationError(_('The lower limit must be less than or equal to the upper limit.'))


class QualityInspectionItem(models.Model):
    _name = 'sn.wsd.quality.inspection.item'
    _description = 'WSD Quality Inspection Item'
    _order = 'code, id'
    _check_company_auto = True

    name = fields.Char(string='Item Name', required=True)
    code = fields.Char(string='Item Code', required=True, index=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    item_type = fields.Selection(
        [
            ('numeric', 'Numeric'),
            ('pass_fail', 'Pass or Fail'),
            ('selection', 'Selection'),
            ('text', 'Text'),
        ],
        string='Item Type',
        required=True,
        default='pass_fail',
    )
    required = fields.Boolean(string='Required', default=True)
    lower_limit = fields.Float(string='Lower Limit')
    upper_limit = fields.Float(string='Upper Limit')
    expected_value = fields.Char(string='Expected Value')
    selection_values = fields.Char(string='Allowed Values')
    unit = fields.Char(string='Unit')
    instruction = fields.Text(string='Instruction')
    note = fields.Text(string='Notes')

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The inspection item code must be unique per company.',
    )

    @api.constrains('item_type', 'lower_limit', 'upper_limit')
    def _check_numeric_limits(self):
        for item in self.filtered(lambda record: record.item_type == 'numeric'):
            if float_compare(item.lower_limit, item.upper_limit, precision_rounding=0.0001) > 0:
                raise ValidationError(_('The lower limit must be less than or equal to the upper limit.'))


class QualityInspectionItemGroup(models.Model):
    _name = 'sn.wsd.quality.inspection.item.group'
    _description = 'WSD Quality Inspection Item Group'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, code, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Group Name', required=True, tracking=True)
    code = fields.Char(string='Group Code', required=True, index=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    line_ids = fields.One2many(
        'sn.wsd.quality.inspection.item.group.line',
        'group_id',
        string='Inspection Items',
    )
    item_count = fields.Integer(string='Item Count', compute='_compute_item_count')
    note = fields.Text(string='Notes')

    _code_company_uniq = models.Constraint(
        'unique(company_id, code)',
        'The inspection item group code must be unique per company.',
    )

    @api.depends('line_ids')
    def _compute_item_count(self):
        for group in self:
            group.item_count = len(group.line_ids)


class QualityInspectionItemGroupLine(models.Model):
    _name = 'sn.wsd.quality.inspection.item.group.line'
    _description = 'WSD Quality Inspection Item Group Line'
    _order = 'group_id, sequence, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    group_id = fields.Many2one(
        'sn.wsd.quality.inspection.item.group',
        string='Inspection Item Group',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='group_id.company_id',
        store=True,
        readonly=True,
    )
    item_id = fields.Many2one(
        'sn.wsd.quality.inspection.item',
        string='Inspection Item',
        required=True,
        check_company=True,
        domain="[('active', '=', True)]",
    )
    item_code = fields.Char(string='Item Code', related='item_id.code', store=True, readonly=True)
    name = fields.Char(string='Item Name', related='item_id.name', store=True, readonly=True)
    item_type = fields.Selection(related='item_id.item_type', string='Item Type', store=True, readonly=True)
    required = fields.Boolean(related='item_id.required', string='Required', store=True, readonly=True)
    lower_limit = fields.Float(related='item_id.lower_limit', string='Lower Limit', store=True, readonly=True)
    upper_limit = fields.Float(related='item_id.upper_limit', string='Upper Limit', store=True, readonly=True)
    expected_value = fields.Char(related='item_id.expected_value', string='Expected Value', store=True, readonly=True)
    selection_values = fields.Char(related='item_id.selection_values', string='Allowed Values', store=True, readonly=True)
    unit = fields.Char(related='item_id.unit', string='Unit', store=True, readonly=True)

    _group_item_uniq = models.Constraint(
        'unique(group_id, item_id)',
        'The inspection item must be unique within one group.',
    )

class QualityInspection(models.Model):
    _name = 'sn.wsd.quality.inspection'
    _description = 'WSD Quality Inspection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scheduled_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Inspection No.',
        default=lambda self: _('New'),
        readonly=True,
        copy=False,
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    inspection_type = fields.Selection(
        [
            ('fai', 'FAI - First Article Inspection'),
            ('iqc', 'IQC - Incoming Quality Control'),
            ('ipqc', 'IPQC - In-Process Quality Control'),
            ('oqc', 'OQC - Outgoing Quality Control'),
        ],
        string='Inspection Type',
        required=True,
        index=True,
        tracking=True,
    )
    scheme_id = fields.Many2one(
        'sn.wsd.quality.inspection.scheme',
        string='Inspection Scheme',
        check_company=True,
        index=True,
        tracking=True,
    )
    scheme_code = fields.Char(string='Scheme Code', related='scheme_id.code', store=True, readonly=True)
    state = fields.Selection(
        [
            ('open', 'Open'),
            ('in_progress', 'In Progress'),
            ('done', 'Done'),
            ('overdue', 'Overdue'),
            ('skipped', 'Skipped'),
        ],
        string='Status',
        required=True,
        default='open',
        tracking=True,
        index=True,
    )
    result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('partial', 'Partial Pass'),
            ('fail', 'Fail'),
            ('concession', 'Concession'),
            ('reject', 'Reject'),
        ],
        string='Inspection Result',
        compute='_compute_result',
        store=True,
        readonly=False,
        tracking=True,
        index=True,
    )
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', check_company=True, index=True)
    mes_order_id = fields.Many2one('sn.wsd.mes.order', string='MES Order', check_company=True, index=True)
    route_operation_id = fields.Many2one('sn.wsd.mes.order.route.operation', string='Route Operation', check_company=True, index=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', check_company=True, index=True)
    operation_id = fields.Many2one('mrp.routing.workcenter', string='Operation', check_company=True, index=True)
    production_line_id = fields.Many2one('sn.mrp.production.line', string='Production Line', check_company=True, index=True)
    product_id = fields.Many2one('product.product', string='Product', check_company=True, index=True)
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id', string='Product Template', store=True, readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Transfer', check_company=True, index=True)
    move_line_id = fields.Many2one('stock.move.line', string='Operation Line', check_company=True, index=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number', check_company=True, index=True)
    area_sn = fields.Char(string='Area SN', index=True)
    model_code = fields.Char(string='Model Code', index=True)
    scheduled_time = fields.Datetime(string='Scheduled Time', default=fields.Datetime.now, required=True, index=True)
    start_time = fields.Datetime(string='Start Time')
    finish_time = fields.Datetime(string='Finish Time')
    inspector_id = fields.Many2one('res.users', string='Inspector', default=lambda self: self.env.user, tracking=True)
    sample_window_start = fields.Datetime(string='Sample Window Start')
    sample_window_end = fields.Datetime(string='Sample Window End')
    evidence_serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='Evidence SN', check_company=True, index=True,
    )
    # FAI 样本清单（add-mes-fai）：投入登记的样本 SN / 其中过首件工序出站
    # OK 的样本；NG/报废出站的样本从清单剔除释放名额（维修回流不回补）
    x_fai_serial_ids = fields.Many2many(
        'sn.wsd.serial.identity', 'sn_quality_inspection_fai_serial_rel',
        'inspection_id', 'serial_id', string='FAI Samples',
        help='Serial numbers registered as first-article samples for this '
             'round (fed in at the start operation while quota is open).',
    )
    x_fai_arrived_serial_ids = fields.Many2many(
        'sn.wsd.serial.identity', 'sn_quality_inspection_fai_arrived_rel',
        'inspection_id', 'serial_id', string='FAI Arrived Samples',
        help='Samples that already left the first-article operation with an '
             'OK result and wait for the inspector.',
    )
    x_fai_removed_serial_ids = fields.Many2many(
        'sn.wsd.serial.identity', 'sn_quality_inspection_fai_removed_rel',
        'inspection_id', 'serial_id', string='FAI Removed Samples',
        help='Samples dropped from this round after an NG/scrap leave at '
             'the first-article operation. Reworked boards never re-enter '
             'the sample list (first articles must be untouched boards); '
             'the quota they released is refilled by fresh feeds only.',
    )
    # OQC 样本台账（oqc-entry-trigger 决策 3/5）：复用 FAI 的逐板字段族，
    # NG/报废出站的样本与 FAI 刻意分叉——不剔除、不释放名额（补位会一直
    # 抽到凑满良品、AQL 缺陷计数 d 失真），记入此名单参与 d 与到检判定
    x_oqc_ng_serial_ids = fields.Many2many(
        'sn.wsd.serial.identity', 'sn_wsd_quality_inspection_oqc_ng_rel',
        'inspection_id', 'serial_identity_id', string='OQC NG Samples',
        copy=False,
        help='Samples that left the outgoing operation with an NG or scrap '
             'result. Unlike FAI they keep their slot: refilling would '
             'distort the AQL defect count, so they stay in the sample '
             'list and count towards the defect quantity.',
    )
    # FAI 逐板检验视图（fai-matrix-form 界面重构）：扫码切换当前板
    # （过站）/ 扫不良板落行（报工）；数量三件套存储留档
    x_fai_current_sn = fields.Many2one(
        'sn.wsd.serial.identity', string='Inspecting SN', copy=False,
        help='Board currently shown in the inspection tab (switched by '
             'scanning or picking a product from the history tab).',
    )
    x_fai_scan = fields.Char(
        string='Scan SN', copy=False,
        help='Scan a board SN: station mode switches the inspected board, '
             'report mode records a defective board.',
    )
    x_fai_ok_qty = fields.Integer(
        string='OK Qty', compute='_compute_x_fai_counts', store=True,
        help='Picked products that passed this first-article round.',
    )
    x_fai_ng_qty = fields.Integer(
        string='NG Qty', compute='_compute_x_fai_counts', store=True,
        help='Picked products found defective this first-article round.',
    )

    @api.depends(
        'inspection_type', 'sample_size', 'mes_order_id.x_manage_mode',
        'cell_ids.result', 'cell_ids.serial_identity_id',
        'sample_ids.result', 'sample_ids.x_line_id',
        'x_oqc_ng_serial_ids',
    )
    def _compute_x_fai_counts(self):
        # 逐板检验计数（决策 5）：FAI/OQC 共用同一套字段与口径
        for inspection in self:
            if inspection.inspection_type not in ('fai', 'oqc'):
                inspection.x_fai_ok_qty = 0
                inspection.x_fai_ng_qty = 0
                continue
            if inspection.mes_order_id.x_manage_mode == 'report':
                ng = len(inspection.sample_ids.filtered(lambda s: s.result == 'fail'))
            elif inspection.inspection_type == 'oqc':
                # OQC 过站矩阵：不良 = fail 格的样本 SN 去重 ∪ NG 出站名单
                ng = len(inspection._oqc_bad_serial_ids())
            else:
                fail_cells = inspection.cell_ids.filtered(lambda c: c.result == 'fail')
                ng = len(set(fail_cells.mapped('serial_identity_id').ids))
            inspection.x_fai_ng_qty = ng
            inspection.x_fai_ok_qty = max(0, (inspection.sample_size or 0) - ng)

    @api.onchange('x_fai_scan')
    def _onchange_x_fai_scan(self):
        # 扫码=异常驱动的入口：过站切换当前检验板；报工记不良板
        # （FAI/OQC 共用，决策 5）
        code = (self.x_fai_scan or '').strip()
        self.x_fai_scan = False
        if not code or self.inspection_type not in ('fai', 'oqc') or not self.mes_order_id:
            return
        serial = self.env['sn.wsd.serial.identity'].search(
            [('name', '=', code)], limit=1)
        if self.mes_order_id.x_manage_mode == 'report':
            if not serial:
                raise UserError(_('Unknown serial number "%s": defective '
                                  'boards must carry a registered SN.', code))
            if serial in self.sample_ids.serial_identity_id:
                raise UserError(_('%s is already recorded as defective.', code))
            self.sample_ids = [Command.create({
                'serial_identity_id': serial.id,
                'result': 'fail',
            })]
        elif self.inspection_type == 'oqc':
            # OQC 合法域 = 本轮已登记样本（x_fai_serial_ids）：单据可在
            # 板还在途时开始检验；FAI 仍要求已到检（首件必须先过站）
            if not serial or serial not in self.x_fai_serial_ids:
                raise UserError(_(
                    '"%s" is not one of this round\'s picked products.', code))
            self.x_fai_current_sn = serial.id
        else:
            if not serial or serial not in self.x_fai_arrived_serial_ids:
                raise UserError(_(
                    '"%s" is not one of this round\'s picked products '
                    '(boards must reach the first-article operation first).', code))
            self.x_fai_current_sn = serial.id

    def _oqc_station_mode(self):
        """OQC 过站矩阵模式的判别式：挂在制令单上且非报工模式。
        闸门/矩阵展开/d 口径只认"有制令单的过站单"；手工建的无制令单
        OQC 单不进新状态机，保持单据级清单行为（决策 6）。"""
        self.ensure_one()
        return bool(
            self.inspection_type == 'oqc'
            and self.mes_order_id
            and self.mes_order_id.x_manage_mode != 'report'
        )

    def _oqc_bad_serial_ids(self):
        """OQC 不良样本口径（决策 3）：存在 fail 结果格的样本 SN，
        并上 NG/报废出站名单（去重）。NG 板占名额不补位，d 以此为准。"""
        self.ensure_one()
        fail_cells = self.cell_ids.filtered(lambda c: c.result == 'fail')
        return fail_cells.mapped('serial_identity_id') | self.x_oqc_ng_serial_ids

    sample_size = fields.Integer(string='Sample Size', default=1)
    inspected_qty = fields.Integer(string='Inspected Qty', compute='_compute_inspection_counts', store=True)
    defect_qty = fields.Integer(string='Defect Qty', compute='_compute_inspection_counts', store=True)
    accept_qty = fields.Integer(string='Accept Qty', default=0)
    reject_qty = fields.Integer(string='Reject Qty', default=1)
    line_ids = fields.One2many('sn.wsd.quality.inspection.line', 'inspection_id', string='Inspection Items')
    defect_line_ids = fields.One2many('sn.wsd.quality.inspection.defect.line', 'inspection_id', string='Defect Lines')
    # FAI 检验矩阵（add-mes-fai-matrix）：样本 × 检验项的结果格
    cell_ids = fields.One2many('sn.wsd.quality.inspection.cell', 'inspection_id', string='Result Cells')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'sn_wsd_quality_inspection_attachment_rel',
        'inspection_id',
        'attachment_id',
        string='Attachments',
    )
    note = fields.Text(string='Notes')

    @api.depends('state', 'line_ids.result', 'defect_line_ids.defect_qty', 'sample_size', 'accept_qty', 'reject_qty')
    def _compute_result(self):
        for inspection in self:
            if inspection.result in ('concession', 'reject') and inspection.state == 'done':
                continue
            if not inspection.line_ids:
                inspection.result = 'pending'
                continue
            results = set(inspection.line_ids.mapped('result'))
            if results.intersection({'pending'}):
                inspection.result = 'pending'
            elif results == {'pass'} or results == {'pass', 'na'} or results == {'na'}:
                inspection.result = 'pass'
            elif 'pass' in results and 'fail' in results:
                inspection.result = 'partial'
            elif 'fail' in results:
                inspection.result = 'fail'
            else:
                inspection.result = 'pending'
            if inspection.inspection_type == 'oqc' and inspection.state == 'done':
                if inspection.defect_qty >= inspection.reject_qty:
                    inspection.result = 'reject'
                elif inspection.defect_qty <= inspection.accept_qty:
                    inspection.result = 'pass'

    @api.depends('line_ids.result', 'defect_line_ids.defect_qty',
                 'cell_ids.result', 'cell_ids.serial_identity_id',
                 'x_oqc_ng_serial_ids')
    def _compute_inspection_counts(self):
        for inspection in self:
            inspection.inspected_qty = len(inspection.line_ids.filtered(lambda line: line.result not in ('pending', 'na')))
            if inspection._oqc_station_mode():
                # OQC 过站矩阵：d = 缺陷行数量合计 + 不良样本 SN 去重台数
                # （fail 格的 SN ∪ NG 出站名单，决策 3）；报工模式保持
                # 现状口径（缺陷行 + fail 项目行）
                inspection.defect_qty = sum(
                    inspection.defect_line_ids.mapped('defect_qty')
                ) + len(inspection._oqc_bad_serial_ids())
            else:
                inspection.defect_qty = sum(inspection.defect_line_ids.mapped('defect_qty')) + len(
                    inspection.line_ids.filtered(lambda line: line.result == 'fail')
                )

    x_patrol_operation_id = fields.Many2one(
        related='scheme_id.operation_id', string='Patrol Operation',
        store=True, readonly=True, index=True,
        help='Operation the patrol scheme watches (from the scheme).',
    )
    # 巡检实际抽取数（add-mes-ipqc-patrol 重构）：异常驱动录入下无不良
    # 零录入，已检样本数以此为准（预填方案样本量提示，检验员可改）
    x_picked_qty = fields.Integer(
        string='Picked Qty', copy=False,
        help='How many boards the inspector actually picked for this patrol. '
             'Defaults to the scheme sample size hint and stays editable.',
    )
    # 巡检历史页签：同产线×同巡检工序的过往巡检单（只读趋势视图）
    x_ipqc_history_ids = fields.Many2many(
        'sn.wsd.quality.inspection', string='Recent Inspections',
        compute='_compute_x_ipqc_history',
        help='Previous patrol inspections of the same production line and '
             'operation, newest first.',
    )

    @api.depends('inspection_type', 'company_id', 'production_line_id',
                 'x_patrol_operation_id')
    def _compute_x_ipqc_history(self):
        for inspection in self:
            inspection.x_ipqc_history_ids = False
            if inspection.inspection_type != 'ipqc':
                continue
            inspection.x_ipqc_history_ids = self.search([
                ('inspection_type', '=', 'ipqc'),
                ('company_id', '=', inspection.company_id.id),
                ('production_line_id', '=', inspection.production_line_id.id),
                ('x_patrol_operation_id', '=',
                 inspection.x_patrol_operation_id.id),
                ('id', '!=', inspection.id),
            ], order='scheduled_time desc, id desc', limit=15)

    @api.onchange('scheme_id')
    def _onchange_scheme_id(self):
        # 手动开单（add-mes-ipqc-patrol V0）：选方案即带模板行快照与样本量，
        # 与 create_from_scheme 同口径（cron 开单不走此处）
        if self.scheme_id:
            self.line_ids = self._line_commands_from_scheme(self.scheme_id)
            self.sample_size = self.scheme_id.sample_size
            self.x_picked_qty = self.scheme_id.sample_size
            if self.inspection_type == 'fai':
                # FAI 检验项默认合格：选方案展开快照即预填，只改异常项
                self.line_ids._set_pass_values()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                inspection_type = vals.get('inspection_type') or 'quality'
                vals['name'] = self.env['ir.sequence'].next_by_code(f'sn.wsd.quality.inspection.{inspection_type}') or _('New')
            if not vals.get('mes_order_id'):
                workorder = self.env['sn.wsd.mes.order.route.operation'].browse(vals.get('route_operation_id')).exists() if vals.get('route_operation_id') else self.env['sn.wsd.mes.order.route.operation']
                production = self.env['mrp.production'].browse(vals.get('production_id')).exists() if vals.get('production_id') else (workorder.mes_order_id.production_id if workorder else False)
                mes_order = (
                    (workorder.mes_order_id if workorder else False)
                    or (production.x_mes_order_id if production else False)
                )
                if mes_order:
                    vals['mes_order_id'] = mes_order.id
        return super().create(vals_list)

    @api.model
    def _find_scheme(self, inspection_type, product=False, route_operation=False, production=False, move_line=False):
        company = self.env.company
        if production and production.company_id:
            company = production.company_id
        elif route_operation and route_operation.company_id:
            company = route_operation.company_id
        elif move_line and move_line.company_id:
            company = move_line.company_id
        domain = [
            ('company_id', '=', company.id),
            ('inspection_type', '=', inspection_type),
            ('state', '=', 'effective'),
            ('active', '=', True),
        ]
        candidates = self.env['sn.wsd.quality.inspection.scheme'].search(domain, order='id asc')
        matched_schemes = []
        for scheme in candidates:
            if not scheme._matches_product_scope(product):
                continue
            if scheme.operation_id and route_operation and scheme.operation_id != route_operation.operation_id:
                continue
            if scheme.production_line_id:
                target_line = (
                    (route_operation.mes_order_id.production_line_id if route_operation else False)
                    or (production.x_production_line_id if production else False)
                    or (move_line.picking_id.picking_type_id.warehouse_id if move_line else False)
                )
                if target_line != scheme.production_line_id:
                    continue
            matched_schemes.append(scheme)
        if matched_schemes:
            return max(matched_schemes, key=lambda scheme: (
                scheme._product_scope_score(product),
                4 if scheme.operation_id else 0,
                1 if scheme.production_line_id else 0,
                -scheme.id,
            ))
        return self.env['sn.wsd.quality.inspection.scheme']

    @api.model
    def _line_commands_from_scheme(self, scheme):
        return [
            Command.create({
                'sequence': line.sequence,
                'name': line.name,
                'item_code': line.item_code,
                'item_type': line.item_type,
                'required': line.required,
                'lower_limit': line.lower_limit,
                'upper_limit': line.upper_limit,
                'expected_value': line.expected_value,
                'selection_values': line.selection_values,
                'unit': line.unit,
                'instruction': line.instruction,
            })
            for line in scheme.line_ids
        ]

    @api.model
    def create_from_scheme(self, scheme, values):
        if scheme and not hasattr(scheme, 'ids'):
            scheme = self.env['sn.wsd.quality.inspection.scheme'].browse(int(scheme)).exists()
        if not scheme:
            raise UserError(_('No effective inspection scheme was found.'))
        values = dict(values)
        values.update({
            'inspection_type': scheme.inspection_type,
            'scheme_id': scheme.id,
            'company_id': values.get('company_id') or scheme.company_id.id,
            'sample_size': values.get('sample_size') or scheme.sample_size,
            'accept_qty': values.get('accept_qty') if values.get('accept_qty') is not None else scheme.accept_qty,
            'reject_qty': values.get('reject_qty') if values.get('reject_qty') is not None else scheme.reject_qty,
            'line_ids': self._line_commands_from_scheme(scheme),
        })
        return self.create(values)

    def action_start(self):
        self.write({
            'state': 'in_progress',
            'start_time': fields.Datetime.now(),
        })
        return True

    def action_set_all_pass(self):
        for inspection in self:
            if inspection.inspection_type in ('fai', 'oqc') and inspection.mes_order_id \
                    and inspection.mes_order_id.x_manage_mode != 'report':
                # 过站 FAI/OQC 矩阵（决策 4）：逐格置 pass，项目行结果随格派生
                inspection.cell_ids._set_pass_values()
            else:
                inspection.line_ids._set_pass_values()
        return True

    def action_batch_set_pass(self):
        active_inspections = self.filtered(lambda inspection: inspection.state in ('open', 'in_progress'))
        if not active_inspections:
            raise UserError(_('Select at least one open inspection.'))
        active_inspections.action_set_all_pass()
        active_inspections.action_done()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_done(self):
        for inspection in self:
            missing = inspection.line_ids.filtered(lambda line: line.required and line.result == 'pending')
            if missing:
                raise UserError(_('Complete all required inspection items before finishing the inspection.'))
            # 完检齐套口径按模式分叉：过站矩阵模式的样本台账在 m2m 字段
            # 上（到检 ∪ NG ≥ n，由 mes_order_oqc 的 action_done 校验），
            # 单据级 inspected_qty 只对非矩阵（含报工/手工）OQC 生效
            if inspection.inspection_type == 'oqc' \
                    and not inspection._oqc_station_mode() \
                    and inspection.inspected_qty < inspection.sample_size:
                raise UserError(_('The OQC sample inspection is not complete.'))
            if inspection.inspection_type == 'oqc' and inspection.defect_line_ids.filtered(lambda line: not line.defect_code_id):
                raise UserError(_('Defect code is required on every OQC defect line.'))
        self.write({
            'state': 'done',
            'finish_time': fields.Datetime.now(),
        })
        self._apply_quality_hold()
        return True

    def action_mark_concession(self):
        self.write({
            'result': 'concession',
            'state': 'done',
            'finish_time': fields.Datetime.now(),
        })
        return True

    def action_reset_open(self):
        self.write({'state': 'open', 'finish_time': False})
        return True

    def action_open_form(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def _apply_quality_hold(self):
        issue_model = self.env['sn.wsd.quality.issue']
        for inspection in self.filtered(lambda item: item.result in ('fail', 'reject')):
            default_defect_code = self.env['sn.wsd.quality.defect.code'].search([
                ('company_id', '=', inspection.company_id.id),
            ], order='severity desc, id asc', limit=1)
            serial_defects = []
            for defect_line in inspection.defect_line_ids.filtered('serial_identity_id'):
                serial_defects.append((defect_line.serial_identity_id, defect_line.defect_code_id or default_defect_code))
            if inspection.evidence_serial_identity_id:
                serial_defects.append((inspection.evidence_serial_identity_id, default_defect_code))
            for identity, defect_code in serial_defects:
                identity.x_quality_hold_state = 'hold'
                if defect_code and not issue_model.search([
                    ('serial_identity_id', '=', identity.id),
                    ('inspection_id', '=', inspection.id),
                ], limit=1):
                    issue_model.create({
                        'serial_identity_id': identity.id,
                        'route_operation_id': inspection.route_operation_id.id,
                        'workcenter_id': inspection.workcenter_id.id,
                        'defect_code_id': defect_code.id,
                        'issue_source': inspection.inspection_type,
                        'state': 'open',
                        'detected_time': fields.Datetime.now(),
                        'inspection_id': inspection.id,
                        'note': inspection.name,
                    })

    def _fai_expand_result_cells(self):
        # 到检逐台展开矩阵：每个已到检 SN × 每个检验项补缺失的结果格（幂等）。
        # FAI/OQC 共用（决策 4/5）：OQC 到检走同一条展开链
        Cell = self.env['sn.wsd.quality.inspection.cell']
        for inspection in self:
            if inspection.inspection_type not in ('fai', 'oqc'):
                continue
            if not inspection.mes_order_id or inspection.mes_order_id.x_manage_mode == 'report':
                continue  # 报工模式无 SN：保持单据级结果，不展开矩阵
            existing = {
                (cell.serial_identity_id.id, cell.line_id.id)
                for cell in inspection.cell_ids
            }
            cell_values = [
                {
                    'inspection_id': inspection.id,
                    'company_id': inspection.company_id.id,
                    'serial_identity_id': serial.id,
                    'line_id': line.id,
                }
                for serial in inspection.x_fai_arrived_serial_ids
                for line in inspection.line_ids
                if (serial.id, line.id) not in existing
            ]
            if cell_values:
                cells = Cell.create(cell_values)
                # 检验项默认都是 OK：展开即预填合格值（数值=区间中值/
                # 文本=期望值/判定式=manual pass），检验员只改异常格
                cells._set_pass_values()
        return True

    @api.model
    def create_fai_for_production(self, production):
        product = production.product_id
        mes_order = production.x_mes_order_id
        route_operation = mes_order.x_route_operation_ids.sorted('sequence')[:1] if mes_order else self.env['sn.wsd.mes.order.route.operation']
        scheme = self._find_scheme('fai', product=product, route_operation=route_operation, production=production)
        if not scheme:
            return self.env['sn.wsd.quality.inspection']
        existing = self.search([
            ('inspection_type', '=', 'fai'),
            ('production_id', '=', production.id),
            ('state', 'in', ('open', 'in_progress')),
        ], limit=1)
        if existing:
            return existing
        return self.create_from_scheme(scheme, {
            'production_id': production.id,
            'route_operation_id': route_operation.id,
            'workcenter_id': route_operation.workcenter_id.id if route_operation else False,
            'production_line_id': production.x_production_line_id.id,
            'product_id': product.id,
            'area_sn': production.x_production_line_id.code,
            'model_code': production.x_meter_model or product.default_code,
            'scheduled_time': fields.Datetime.now(),
        })

    @api.model
    def create_iqc_for_move_line(self, move_line):
        if not move_line or not move_line.picking_id:
            return self.browse()
        return self.create_iqc_for_picking_product(
            move_line.picking_id,
            move_line.product_id,
            move_line=move_line,
        )

    @api.model
    def create_iqc_for_picking_product(self, picking, product, move=False, move_line=False):
        if not picking or not product:
            return self.browse()

        scheme = self._find_scheme(
            'iqc',
            product=product,
            move_line=move_line,
        )
        if not scheme:
            return self.browse()

        existing = self.search([
            ('inspection_type', '=', 'iqc'),
            ('picking_id', '=', picking.id),
            ('product_id', '=', product.id),
            ('scheme_id', '=', scheme.id),
            ('state', '!=', 'skipped'),
        ], limit=1)
        if existing:
            return existing

        if move_line:
            lot_qty = int(round(move_line.quantity_product_uom))
        elif move:
            lot_qty = int(round(
                move.product_uom._compute_quantity(
                    move.product_uom_qty,
                    product.uom_id,
                )
            ))
        else:
            lot_qty = 0

        return self.create_from_scheme(scheme, {
            'picking_id': picking.id,
            'move_line_id': move_line.id if move_line else False,
            'product_id': product.id,
            'lot_qty': lot_qty,
            'scheduled_time': picking.scheduled_date,
        })

    @api.model
    def cron_generate_ipqc_inspections(self):
        _logger.info('IPQC cron generation is disabled.')
        return True


class QualityInspectionLine(models.Model):
    _name = 'sn.wsd.quality.inspection.line'
    _description = 'WSD Quality Inspection Line'
    _order = 'inspection_id, sequence, id'
    _check_company_auto = True

    sequence = fields.Integer(default=10)
    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection',
        string='Inspection',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='inspection_id.company_id',
        store=True,
        readonly=True,
    )
    name = fields.Char(string='Item Name', required=True)
    item_code = fields.Char(string='Item Code', required=True)
    item_type = fields.Selection(
        [
            ('numeric', 'Numeric'),
            ('pass_fail', 'Pass or Fail'),
            ('selection', 'Selection'),
            ('text', 'Text'),
        ],
        string='Item Type',
        required=True,
        default='pass_fail',
    )
    required = fields.Boolean(string='Required', default=True)
    lower_limit = fields.Float(string='Lower Limit')
    upper_limit = fields.Float(string='Upper Limit')
    expected_value = fields.Char(string='Expected Value')
    selection_values = fields.Char(string='Allowed Values')
    unit = fields.Char(string='Unit')
    instruction = fields.Text(string='Instruction')
    is_checked = fields.Boolean(string='Checked')
    measured_value = fields.Float(string='Measured Value')
    text_value = fields.Char(string='Text Value')
    manual_result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('fail', 'Fail'),
            ('na', 'N/A'),
        ],
        string='Manual Result',
        default='pending',
    )
    result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('fail', 'Fail'),
            ('na', 'N/A'),
        ],
        string='Result',
        compute='_compute_result',
        store=True,
        readonly=False,
        index=True,
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'sn_wsd_quality_inspection_line_attachment_rel',
        'line_id',
        'attachment_id',
        string='Attachments',
    )
    note = fields.Char(string='Notes')
    # FAI 检验矩阵：该项目行下的样本结果格
    cell_ids = fields.One2many('sn.wsd.quality.inspection.cell', 'line_id', string='Result Cells')

    def _set_pass_values(self):
        for line in self:
            vals = {
                'is_checked': True,
                'manual_result': 'pass',
            }
            if line.item_type == 'numeric':
                vals['measured_value'] = line._get_pass_numeric_value()
            elif line.item_type in ('selection', 'text'):
                vals['text_value'] = line._get_pass_text_value()
            line.write(vals)
        return True

    def _get_pass_numeric_value(self):
        self.ensure_one()
        if float_compare(self.lower_limit, self.upper_limit, precision_rounding=0.0001) <= 0:
            return (self.lower_limit + self.upper_limit) / 2.0
        return self.measured_value

    def _get_pass_text_value(self):
        self.ensure_one()
        if self.item_type == 'selection':
            allowed = [value.strip() for value in (self.selection_values or '').split(',') if value.strip()]
            return allowed[0] if allowed else (self.text_value or self.expected_value)
        return self.expected_value or self.text_value

    @api.model
    def _judge_item_value(self, item_type, measured=0.0, text='', expected='',
                          allowed='', lower=0.0, upper=0.0, manual=False):
        """判定口径（FAI 检验矩阵抽取）：单据级 line 与样本级 cell 共用，
        只做纯值判定；line._compute_result 的行为与抽取前完全等价。"""
        if item_type == 'numeric':
            if float_compare(measured, lower, precision_rounding=0.0001) < 0:
                return 'fail'
            if float_compare(measured, upper, precision_rounding=0.0001) > 0:
                return 'fail'
            return 'pass'
        if item_type == 'selection':
            values = [value.strip() for value in (allowed or '').split(',') if value.strip()]
            return 'pass' if not values or text in values else 'fail'
        if item_type == 'text':
            return 'pass' if not expected or text == expected else 'fail'
        return manual or 'pending'

    @api.depends('item_type', 'is_checked', 'measured_value', 'lower_limit', 'upper_limit',
                 'text_value', 'expected_value', 'manual_result', 'cell_ids.result',
                 'inspection_id.sample_ids.result', 'inspection_id.sample_ids.x_line_id')
    def _compute_result(self):
        for line in self:
            if line.inspection_id.inspection_type in ('fai', 'oqc') \
                    and line.inspection_id.mes_order_id \
                    and line.inspection_id.mes_order_id.x_manage_mode != 'report':
                # 过站 FAI/OQC 矩阵（决策 4）：行结果由结果格派生（任一格
                # fail 即 fail），跳过原有单据级手填逻辑
                results = set(line.cell_ids.mapped('result'))
                if 'fail' in results:
                    line.result = 'fail'
                elif line.cell_ids and results == {'pass'}:
                    line.result = 'pass'
                else:
                    line.result = 'pending'
                continue
            if line.inspection_id.inspection_type == 'fai' \
                    and line.inspection_id.sample_ids.filtered(
                        lambda s: s.result == 'fail' and s.x_line_id == line):
                # 报工 FAI：扫过不良板的项目行自动判 fail（快照默认合格，
                # 检验员只扫不良板，行结果随不良行翻转）
                line.result = 'fail'
                continue
            if not line.is_checked:
                line.result = 'pending'
                continue
            line.result = self._judge_item_value(
                line.item_type,
                measured=line.measured_value,
                text=line.text_value,
                expected=line.expected_value,
                allowed=line.selection_values,
                lower=line.lower_limit,
                upper=line.upper_limit,
                manual=line.manual_result,
            )


class QualityInspectionCell(models.Model):
    """FAI 检验矩阵结果格（add-mes-fai-matrix）：样本 × 检验项一格，
    过站模式齐套后自动展开；判定口径与 line 共用 _judge_item_value。"""

    _name = 'sn.wsd.quality.inspection.cell'
    _description = 'WSD Quality Inspection Result Cell'
    _order = 'inspection_id, serial_identity_id, line_id, id'
    _check_company_auto = True

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
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity',
        string='SN',
        required=True,
        check_company=True,
        index=True,
    )
    line_id = fields.Many2one(
        'sn.wsd.quality.inspection.line',
        string='Inspection Item',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    measured_value = fields.Float(string='Measured Value')
    text_value = fields.Char(string='Text Value')
    manual_result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('fail', 'Fail'),
            ('na', 'N/A'),
        ],
        string='Manual Result',
        default='pending',
    )
    result = fields.Selection(
        [
            ('pending', 'Pending'),
            ('pass', 'Pass'),
            ('fail', 'Fail'),
            ('na', 'N/A'),
        ],
        string='Result',
        compute='_compute_result',
        store=True,
        index=True,
    )
    note = fields.Char(string='Notes')
    defect_code_id = fields.Many2one(
        'sn.wsd.quality.defect.code', string='Defect Code',
        check_company=True, index=True,
        help='Defect code of the failing check on this board.',
    )
    item_type = fields.Selection(related='line_id.item_type', string='Item Type', readonly=True)
    lower_limit = fields.Float(related='line_id.lower_limit', string='Lower Limit', readonly=True)
    upper_limit = fields.Float(related='line_id.upper_limit', string='Upper Limit', readonly=True)

    _sample_line_uniq = models.Constraint(
        'unique(inspection_id, serial_identity_id, line_id)',
        'Each sample and inspection item pair can only have one result cell in one inspection.',
    )

    @api.depends('manual_result', 'measured_value', 'text_value',
                 'line_id.item_type', 'line_id.lower_limit', 'line_id.upper_limit',
                 'line_id.expected_value', 'line_id.selection_values')
    def _compute_result(self):
        for cell in self:
            line = cell.line_id
            if cell.manual_result == 'pending' \
                    and not cell.measured_value and not cell.text_value:
                # 未录入的空格保持 pending，避免数值空值被上下限判成 fail
                cell.result = 'pending'
                continue
            cell.result = line._judge_item_value(
                line.item_type,
                measured=cell.measured_value,
                text=cell.text_value,
                expected=line.expected_value,
                allowed=line.selection_values,
                lower=line.lower_limit,
                upper=line.upper_limit,
                manual=cell.manual_result,
            )

    def _set_pass_values(self):
        # 参照 line._set_pass_values：预填合格值并置 pass，行结果随格派生
        for cell in self:
            line = cell.line_id
            vals = {'manual_result': 'pass'}
            if line.item_type == 'numeric':
                vals['measured_value'] = line._get_pass_numeric_value()
            elif line.item_type in ('selection', 'text'):
                vals['text_value'] = line._get_pass_text_value()
            cell.write(vals)
        return True


class QualityInspectionDefectLine(models.Model):
    _name = 'sn.wsd.quality.inspection.defect.line'
    _description = 'WSD Quality Inspection Defect Line'
    _order = 'inspection_id, id'
    _check_company_auto = True

    inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection',
        string='Inspection',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='inspection_id.company_id',
        store=True,
        readonly=True,
    )
    defect_code_id = fields.Many2one('sn.wsd.quality.defect.code', string='Defect Code', check_company=True, index=True)
    serial_identity_id = fields.Many2one('sn.wsd.serial.identity', string='SN', check_company=True, index=True)
    defect_qty = fields.Integer(string='Defect Qty', default=1)
    position = fields.Char(string='Position')
    description = fields.Text(string='Description')

    @api.constrains('defect_qty')
    def _check_defect_qty(self):
        for line in self:
            if line.defect_qty <= 0:
                raise ValidationError(_('Defect quantity must be greater than zero.'))


class QualityInspectionSkip(models.Model):
    _name = 'sn.wsd.quality.inspection.skip'
    _description = 'WSD Quality Inspection Skip'
    _order = 'scheduled_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Skip No.', default=lambda self: _('New'), readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company, index=True)
    scheme_id = fields.Many2one('sn.wsd.quality.inspection.scheme', string='Inspection Scheme', check_company=True, index=True)
    production_line_id = fields.Many2one('sn.mrp.production.line', string='Production Line', check_company=True, index=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', check_company=True, index=True)
    operation_id = fields.Many2one('sn.wsd.operation', string='Operation', check_company=True, index=True)
    area_sn = fields.Char(string='Area SN', index=True)
    model_code = fields.Char(string='Model Code', index=True)
    scheduled_time = fields.Datetime(string='Scheduled Time', required=True, default=fields.Datetime.now, index=True)
    reason = fields.Selection(
        [
            ('no_active_production', 'No Active Production'),
            ('incomplete_plan', 'Incomplete Scheme'),
            ('duplicate_open', 'Duplicate Open Inspection'),
        ],
        string='Reason',
        required=True,
        default='no_active_production',
        index=True,
    )
    note = fields.Char(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sn.wsd.quality.inspection.skip') or _('New')
        return super().create(vals_list)

    @api.model
    def create_from_scheme(self, scheme, scheduled_time, reason):
        try:
            return self.create({
                'company_id': scheme.company_id.id,
                'scheme_id': scheme.id,
                'production_line_id': scheme.production_line_id.id,
                'workcenter_id': scheme.workcenter_id.id,
                'operation_id': scheme.operation_id.id,
                'area_sn': scheme.production_line_id.code,
                'model_code': False,
                'scheduled_time': scheduled_time,
                'reason': reason,
            })
        except Exception:
            _logger.warning('Failed to create IPQC skip record for scheme %s', scheme.display_name, exc_info=True)
            return self.env['sn.wsd.quality.inspection.skip']


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_quality_inspection_ids = fields.One2many(
        'sn.wsd.quality.inspection',
        'production_id',
        string='Quality Inspections',
        readonly=True,
    )
    x_quality_inspection_count = fields.Integer(string='Quality Inspection Count', compute='_compute_x_quality_inspection_count')

    def _compute_x_quality_inspection_count(self):
        for production in self:
            production.x_quality_inspection_count = len(production.x_quality_inspection_ids)

    def action_open_quality_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quality Inspections'),
            'res_model': 'sn.wsd.quality.inspection',
            'view_mode': 'list,form',
            'domain': [('production_id', '=', self.id)],
            'context': {'default_production_id': self.id},
        }

    def action_create_fai_inspection(self):
        raise UserError(_('Manual quality inspection creation is disabled.'))


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    x_quality_inspection_ids = fields.One2many(
        'sn.wsd.quality.inspection',
        'move_line_id',
        string='Quality Inspections',
        readonly=True,
    )
    x_quality_inspection_count = fields.Integer(string='Quality Inspection Count', compute='_compute_x_quality_inspection_count')

    def _compute_x_quality_inspection_count(self):
        for line in self:
            line.x_quality_inspection_count = len(line.x_quality_inspection_ids)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        return records

    def write(self, vals):
        result = super().write(vals)
        return result

    def _auto_create_iqc_inspections(self):
        inspections = self.env['sn.wsd.quality.inspection']
        for move_line in self.filtered(
            lambda line: line.picking_id
            and line.picking_id._is_iqc_control_picking()
            and line.product_id
            and line.product_id.is_storable
            and line.quantity_product_uom > 0
        ):
            inspections |= inspections.create_iqc_for_move_line(move_line)
        return inspections

    def action_create_iqc_inspection(self):
        self.ensure_one()
        inspection = self._auto_create_iqc_inspections()
        return inspection.action_open_form() if inspection else False


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_quality_inspection_count = fields.Integer(string='Quality Inspection Count', compute='_compute_x_quality_inspection_count')

    def _compute_x_quality_inspection_count(self):
        for move in self:
            move.x_quality_inspection_count = len(
                move.move_line_ids.x_quality_inspection_ids
            )

    def _get_iqc_target_move_lines(self):
        self.ensure_one()
        return self.move_line_ids.filtered(
            lambda line: line.quantity_product_uom > 0
        )

    def action_create_iqc_inspection(self):
        self.ensure_one()
        inspection = self._get_iqc_target_move_lines()._auto_create_iqc_inspections()
        return inspection.action_open_form() if inspection else False


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_quality_inspection_ids = fields.One2many(
        'sn.wsd.quality.inspection',
        'picking_id',
        string='Quality Inspections',
        readonly=True,
    )
    x_iqc_inspection_count = fields.Integer(
        string='IQC Inspection Count',
        compute='_compute_x_iqc_inspection_count',
    )

    def _compute_x_iqc_inspection_count(self):
        for picking in self:
            picking.x_iqc_inspection_count = len(
                picking.x_quality_inspection_ids.filtered(
                    lambda inspection: inspection.inspection_type == 'iqc'
                )
            )

    def _is_iqc_control_picking(self):
        self.ensure_one()
        return bool(
            self.picking_type_code == 'incoming'
            and not self.return_id
        )

    def _get_iqc_required_move_lines(self):
        self.ensure_one()
        return self.move_line_ids.filtered(
            lambda line: line.product_id
            and line.product_id.is_storable
            and line.quantity_product_uom > 0
        )

    def _get_iqc_required_moves_without_lines(self):
        self.ensure_one()
        return self.move_ids.filtered(
            lambda move: move.state not in ('cancel', 'done')
            and move.product_id
            and move.product_id.is_storable
            and move.product_uom_qty > 0
            and not move.move_line_ids
        )

    def _create_iqc_inspections(self):
        inspection_model = self.env['sn.wsd.quality.inspection']
        inspections = inspection_model
        for picking in self.filtered(lambda record: record._is_iqc_control_picking()):
            product_sources = {}
            for move_line in picking._get_iqc_required_move_lines():
                product_sources.setdefault(move_line.product_id, {
                    'move_lines': self.env['stock.move.line'],
                    'moves': self.env['stock.move'],
                })
                product_sources[move_line.product_id]['move_lines'] |= move_line
            for move in picking._get_iqc_required_moves_without_lines():
                product_sources.setdefault(move.product_id, {
                    'move_lines': self.env['stock.move.line'],
                    'moves': self.env['stock.move'],
                })
                product_sources[move.product_id]['moves'] |= move

            for product, sources in product_sources.items():
                move_lines = sources['move_lines']
                scheme = inspection_model._find_scheme(
                    'iqc',
                    product=product,
                    move_line=move_lines[:1],
                )
                if not scheme:
                    continue
                existing = inspection_model.search([
                    ('inspection_type', '=', 'iqc'),
                    ('picking_id', '=', picking.id),
                    ('product_id', '=', product.id),
                    ('scheme_id', '=', scheme.id),
                    ('state', '!=', 'skipped'),
                ], limit=1)
                if existing:
                    inspections |= existing
                    continue

                if move_lines:
                    lot_qty = sum(move_lines.mapped('quantity_product_uom'))
                else:
                    lot_qty = sum(
                        move.product_uom._compute_quantity(
                            move.product_uom_qty,
                            product.uom_id,
                        )
                        for move in sources['moves']
                    )
                inspections |= inspection_model.create_from_scheme(scheme, {
                    'picking_id': picking.id,
                    'move_line_id': move_lines.id if len(move_lines) == 1 else False,
                    'product_id': product.id,
                    'lot_qty': int(round(lot_qty)),
                    'scheduled_time': picking.scheduled_date,
                })
        return inspections

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        return records

    def write(self, vals):
        result = super().write(vals)
        return result

    def action_confirm(self):
        result = super().action_confirm()
        self._create_iqc_inspections()
        return result

    def action_assign(self):
        return super().action_assign()

    def _check_iqc_before_validate(self):
        inspection_model = self.env['sn.wsd.quality.inspection']
        for picking in self.filtered(lambda record: record._is_iqc_control_picking()):
            incoming_products = (
                picking._get_iqc_required_move_lines().mapped('product_id')
                | picking._get_iqc_required_moves_without_lines().mapped('product_id')
            )
            required_products = incoming_products.filtered(
                lambda product: inspection_model._find_scheme('iqc', product=product)
            )
            inspections = inspection_model.search([
                ('inspection_type', '=', 'iqc'),
                ('picking_id', '=', picking.id),
                ('product_id', 'in', required_products.ids),
                ('state', '!=', 'skipped'),
            ])
            missing_products = required_products - inspections.mapped('product_id')
            if missing_products:
                raise UserError(_(
                    'IQC inspections are required for these products before validating %s: %s',
                    picking.display_name,
                    ', '.join(missing_products.mapped('display_name')),
                ))
            incomplete = inspections.filtered(
                lambda inspection: inspection.state != 'done'
                or inspection.result not in ('pass', 'concession')
            )
            if incomplete:
                raise UserError(_(
                    'Complete and pass all IQC inspections before validating %s: %s',
                    picking.display_name,
                    ', '.join(incomplete.mapped('display_name')),
                ))
        return True

    def _pre_action_done_hook(self):
        result = super()._pre_action_done_hook()
        if result is not True:
            return result
        self._create_iqc_inspections()
        self._check_iqc_before_validate()
        return True

    def button_validate(self):
        return super().button_validate()

    def action_open_iqc_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('IQC Inspections'),
            'res_model': 'sn.wsd.quality.inspection',
            'view_mode': 'list,form',
            'domain': [
                ('picking_id', '=', self.id),
                ('inspection_type', '=', 'iqc'),
            ],
            'context': {
                'default_picking_id': self.id,
                'default_inspection_type': 'iqc',
            },
        }

    def action_create_iqc_inspections(self):
        self.ensure_one()
        self._create_iqc_inspections()
        return self.action_open_iqc_inspections()

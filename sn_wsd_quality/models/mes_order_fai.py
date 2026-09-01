from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

FAI_CONFIRM_MINUTES = 30


class MesOrderFai(models.Model):
    """首件检验（FAI）接线（add-mes-fai）：首台投入/首次合格报工惰性
    建单、投入限流、出站登记、判定联动。全部钩子在质量模块继承制令单
    实现，sn_wsd_mrp 主链不感知 FAI。"""

    _inherit = 'sn.wsd.mes.order'

    x_fai_inspection_ids = fields.One2many(
        'sn.wsd.quality.inspection', 'mes_order_id',
        string='First Article Inspections',
        domain=[('inspection_type', '=', 'fai')],
    )
    x_fai_state = fields.Selection(
        [('none', 'None'), ('in_progress', 'In Progress'),
         ('passed', 'Passed')],
        string='First Article State', compute='_compute_x_fai',
    )
    x_fai_round = fields.Integer(
        string='First Article Round', compute='_compute_x_fai',
    )
    x_fai_inspection_id = fields.Many2one(
        'sn.wsd.quality.inspection', string='Current FAI Inspection',
        compute='_compute_x_fai',
    )
    x_fai_sample_count = fields.Integer(
        string='FAI Samples Fed', compute='_compute_x_fai',
    )
    x_fai_sample_done = fields.Integer(
        string='FAI Samples Arrived', compute='_compute_x_fai',
    )
    x_fai_inspection_count = fields.Integer(
        string='FAI Inspection Count', compute='_compute_x_fai',
    )
    # 上线时刻的轮次基线（oqc-entry-trigger）：惰性建单判定"再上线后
    # 是否需要新一轮"用 计数>基线 而非时间戳比较——datetime 秒级精度
    # 区分不了"本轮上线内判完"与"再上线前判完"的同秒场景
    x_fai_online_round_base = fields.Integer(
        string='FAI Online Round Base', copy=False, default=0,
    )

    @api.depends('x_fai_inspection_ids.state',
                 'x_fai_inspection_ids.result',
                 'x_fai_inspection_ids.x_fai_serial_ids',
                 'x_fai_inspection_ids.x_fai_arrived_serial_ids',
                 'x_fai_inspection_ids.x_fai_reported_qty')
    def _compute_x_fai(self):
        # inspection._order = scheduled_time desc, id desc → 列表首个即最新轮
        for order in self:
            inspections = order.x_fai_inspection_ids
            current = inspections.filtered(lambda i: i.state != 'done')[:1] \
                or inspections[:1]
            if not inspections:
                state = 'none'
            elif current.state == 'done' and current.result == 'pass':
                state = 'passed'
            else:
                state = 'in_progress'
            order.x_fai_state = state
            order.x_fai_round = len(inspections)
            order.x_fai_inspection_id = current
            if order.x_manage_mode == 'report':
                # 报工模式：样本口径 = 首件工序报工合格台数（add-mes-fai-report）
                order.x_fai_sample_count = current.x_fai_reported_qty
                order.x_fai_sample_done = current.x_fai_reported_qty
            else:
                order.x_fai_sample_count = len(current.x_fai_serial_ids)
                order.x_fai_sample_done = len(current.x_fai_arrived_serial_ids)
            order.x_fai_inspection_count = len(inspections)

    # ------------------------------------------------------------------
    # 触发：首台投入 / 首件工序首次合格报工惰性建单（含同单再次上线→新一轮）
    # ------------------------------------------------------------------
    def action_online(self):
        # 上线不再建单（oqc-entry-trigger D1：有产出才建单，上线时首件
        # 尚不存在，空单无意义）；只记轮次基线——"再上线后是否需要新
        # 一轮"用计数对比判定而非时间戳（datetime 秒级精度无法区分
        # "本轮上线内完成"与"再上线前完成"的同秒场景，
        # x_fai_reported_base 同源陷阱）
        res = super().action_online()
        for order in self:
            order.x_fai_online_round_base = len(order.x_fai_inspection_ids)
        return res

    def _fai_maybe_open_round(self, route_operation=False):
        Inspection = self.env['sn.wsd.quality.inspection']
        for order in self:
            if not order.x_online_date:
                continue  # 下线状态不建单
            scheme = Inspection._find_scheme(
                'fai', product=order.production_id.product_id,
                production=order.production_id)
            if not scheme or not scheme.operation_id:
                continue  # 未命中方案 / 方案未配首件工序 → 不触发
            # 双面产品 T/B 各配一套方案（同产品同工序字典不同面）：
            # 只认首件工序在本单路线上的方案——面别不对的方案对这张单
            # 永远等不到样本到位，属于错配
            order_op_ids = set(
                order.x_mes_route_id.operation_ids.mapped('operation_id').ids)
            if scheme.operation_id.id not in order_op_ids:
                alt = Inspection.search([
                    ('inspection_type', '=', 'fai'),
                    ('state', '=', 'effective'),
                    ('active', '=', True),
                    ('operation_id', 'in', list(order_op_ids)),
                ]).filtered(lambda s: s._matches_product_scope(
                    order.production_id.product_id) and s.operation_id)
                scheme = alt[:1]
                if not scheme:
                    continue
            if route_operation \
                    and route_operation.operation_id != scheme.operation_id:
                continue  # 报工模式：非首件工序的合格报工不建单
            inspections = order.x_fai_inspection_ids
            if inspections.filtered(lambda i: i.state != 'done'):
                continue  # 已有未完成轮 → 无需新开
            if len(inspections) > order.x_fai_online_round_base:
                # 本轮上线内已有判完的轮（通过即放行；判退轮在
                # action_done 已即时接续）→ 不是新一轮的时机
                continue
            order._fai_create_round(scheme)

    def _fai_create_round(self, scheme):
        self.ensure_one()
        route_op = self.x_route_operation_ids.filtered(
            lambda r: r.operation_id == scheme.operation_id)[:1]
        inspection = self.env['sn.wsd.quality.inspection'].create_from_scheme(
            scheme, {
                'mes_order_id': self.id,
                'production_id': self.production_id.id,
                'product_id': self.production_id.product_id.id,
                'production_line_id': self.production_line_id.id,
                'route_operation_id': route_op.id,
                # 基线快照：本轮已存在的首件工序合格报工量（见字段 help）
                'x_fai_reported_base': self._fai_existing_reported_base(scheme),
            })
        # 30 分钟首件确认提醒（不硬拦，add-mes-fai 决策）；
        # 接收人：方案负责人 > 检验员（add-mes-fai-report 修正）
        inspection.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=self._fai_activity_user(inspection).id,
            date_deadline=fields.Date.context_today(
                self) + timedelta(days=1),
            summary=_('First article confirmation'),
            note=_('Confirm round %(round)s of %(order)s within 30 minutes.',
                   round=inspection.x_fai_round_number, order=self.name),
        )
        return inspection

    # ------------------------------------------------------------------
    # 投入限流：首台建单、样本未满 N 放行并登记，满 N 且未判定通过则拦
    # ------------------------------------------------------------------
    def enter_station(self, serial_identity, route_operation,
                      workcenter=False):
        self.ensure_one()
        if self.x_manage_mode == 'station' and route_operation.x_allow_entry:
            self._fai_gate_feeding(serial_identity)
        res = super().enter_station(
            serial_identity, route_operation, workcenter=workcenter)
        if self.x_manage_mode == 'station' and route_operation.x_allow_entry:
            # 建单在前、登记紧随 → 首台投入即建轮且该台登记为样本 1
            self._fai_maybe_open_round()
            self._fai_register_sample(serial_identity)
        return res

    def must_hold_for_fai(self, serial_identity, next_route_operation):
        """First-article hold: a sample board that has (just) completed the
        first-article operation must wait for the round verdict -- the
        operation directly downstream of the first-article operation may
        not take it over yet. Returns the open inspection when the hold
        applies, else an empty recordset. The one-scan kernel calls this
        BEFORE parking a board downstream so the arrival registration
        (the first-article OK written by the same pull) is not rolled back.
        """
        self.ensure_one()
        if self.x_manage_mode != 'station':
            return self.env['sn.wsd.quality.inspection']
        inspection = self.x_fai_inspection_id
        if not inspection or inspection.state == 'done':
            return self.env['sn.wsd.quality.inspection']
        first_article_op = inspection.scheme_id.operation_id
        if not first_article_op:
            return self.env['sn.wsd.quality.inspection']
        if next_route_operation.operation_id == first_article_op:
            return self.env['sn.wsd.quality.inspection']
        if first_article_op not in next_route_operation.blocked_by_ids.mapped(
                'operation_id'):
            return self.env['sn.wsd.quality.inspection']
        if serial_identity in inspection.x_fai_serial_ids \
                or serial_identity in inspection.x_fai_arrived_serial_ids:
            return inspection
        return self.env['sn.wsd.quality.inspection']

    def fai_hold_message(self, serial_identity, inspection):
        self.ensure_one()
        return _(
            'First article confirmation is in progress on MES order '
            '%(order)s: SN %(sn)s passed the first-article operation '
            '%(op)s and waits for the inspection result before the next '
            'operation can take it over.',
            order=self.name, sn=serial_identity.name,
            op=inspection.scheme_id.operation_id.display_name)

    def _fai_gate_feeding(self, serial_identity):
        self.ensure_one()
        inspection = self.x_fai_inspection_id
        if not inspection or inspection.state == 'done':
            return
        if serial_identity in inspection.x_fai_serial_ids:
            return
        if serial_identity in inspection.x_fai_removed_serial_ids:
            return  # 维修回流板复测：放行进站，但不再登记样本
        if len(inspection.x_fai_serial_ids) >= inspection.sample_size:
            raise ValidationError(_(
                'First article confirmation is in progress on MES order '
                '%(order)s: wait for the inspection result before feeding '
                'more serial numbers.', order=self.name))

    def _fai_register_sample(self, serial_identity):
        self.ensure_one()
        inspection = self.x_fai_inspection_id
        if not inspection or inspection.state == 'done':
            return
        if serial_identity not in inspection.x_fai_serial_ids                 and serial_identity not in inspection.x_fai_removed_serial_ids:
            inspection.x_fai_serial_ids = [(4, serial_identity.id)]

    # ------------------------------------------------------------------
    # 出站登记：首件工序 OK→到位；NG/报废→剔除释放名额（维修回流不回补）
    # ------------------------------------------------------------------
    def leave_station(self, serial_identity, result, scrap_reason=False,
                      ng_defect=False, operator_code=False):
        self.ensure_one()
        # super 之后 WIP 已流转，工序实例要在之前取
        wip = self.env['sn.wsd.serial.wip'].search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ], limit=1)
        route_operation = wip.route_operation_id if wip else False
        res = super().leave_station(
            serial_identity, result, scrap_reason=scrap_reason,
            ng_defect=ng_defect, operator_code=operator_code)
        if route_operation:
            self._fai_on_leave(serial_identity, result, route_operation)
        return res

    def _fai_on_leave(self, serial_identity, result, route_operation):
        self.ensure_one()
        inspection = self.x_fai_inspection_id
        if not inspection or inspection.state == 'done':
            return
        if serial_identity not in inspection.x_fai_serial_ids:
            return
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return  # 非首件工序的出站不参与样本判定
        if result == 'ok':
            if serial_identity not in inspection.x_fai_arrived_serial_ids:
                inspection.x_fai_arrived_serial_ids = [(4, serial_identity.id)]
            # 到检即展开该样本 × 全部检验项的结果格（幂等，仅过站模式；
            # 逐台累铺，齐套时矩阵自然完整）
            inspection._fai_expand_result_cells()
            if len(inspection.x_fai_arrived_serial_ids) >= inspection.sample_size \
                    and inspection.state == 'open':
                inspection.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=self._fai_activity_user(inspection).id,
                    summary=_('First article samples ready'),
                    note=_('%(count)s samples reached the first-article '
                           'operation of %(order)s; inspection can start.',
                           count=inspection.sample_size, order=self.name),
                )
        else:
            # NG/报废：从样本清单剔除（名额立即释放，投入站自动放行新板
            # 补位）；维修回流后重过 OK 不会回补——首件样本必须是不经
            # 返修的直通板（add-mes-fai spec）
            inspection.x_fai_serial_ids = [(3, serial_identity.id)]
            inspection.x_fai_arrived_serial_ids = [(3, serial_identity.id)]
            inspection.x_fai_removed_serial_ids = [(4, serial_identity.id)]

    def _fai_existing_reported_base(self, scheme):
        self.ensure_one()
        if self.x_manage_mode != 'report' or not scheme.operation_id:
            return 0.0
        reports = self.env['sn.wsd.mes.operation.report'].search([
            ('mes_order_id', '=', self.id),
            ('route_operation_id.operation_id', '=', scheme.operation_id.id),
        ])
        return sum(reports.mapped('qty_ok'))

    def _fai_activity_user(self, inspection):
        inspection.ensure_one()
        return (inspection.scheme_id.responsible_user_id
                or inspection.inspector_id or self.env.user)

    # ------------------------------------------------------------------
    # 报工模式数量收集器（add-mes-fai-report）：闸在 super 前、齐套在后
    # ------------------------------------------------------------------
    def report_operation_qty(self, route_operation, qty_ok, qty_ng=0.0,
                             qty_scrap=0.0, scrap_reason=False):
        self.ensure_one()
        self._fai_gate_report(route_operation, qty_ok)
        res = super().report_operation_qty(
            route_operation, qty_ok, qty_ng=qty_ng, qty_scrap=qty_scrap,
            scrap_reason=scrap_reason)
        self._fai_report_ready_notify(route_operation, qty_ok)
        return res

    def _fai_gate_report(self, route_operation, qty_ok):
        self.ensure_one()
        if self.x_manage_mode != 'report' or qty_ok <= 0:
            return  # 纯 NG/报废报工：调机记账，不占样本名额
        inspection = self.x_fai_inspection_id
        if not inspection or inspection.state == 'done':
            # 建单延迟到首件工序首次合格报工（oqc-entry-trigger）：先开轮，
            # 本轮基数快照自然为 0，当次报工即计入已报首件台数
            self._fai_maybe_open_round(route_operation)
            inspection = self.x_fai_inspection_id
            if not inspection or inspection.state == 'done':
                return
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return  # D1：只拦首件工序的报工
        remaining = inspection.sample_size - inspection.x_fai_reported_qty
        if qty_ok > remaining + 0.0001:
            raise ValidationError(_(
                'First article confirmation is in progress on MES order '
                '%(order)s: report at most %(remaining)s OK unit(s) in '
                'this batch.', order=self.name, remaining=max(remaining, 0.0)))

    def _fai_report_ready_notify(self, route_operation, qty_ok):
        self.ensure_one()
        if self.x_manage_mode != 'report' or qty_ok <= 0:
            return
        inspection = self.x_fai_inspection_id
        if not inspection or inspection.state != 'open':
            return
        if route_operation.operation_id != inspection.scheme_id.operation_id:
            return
        if inspection.x_fai_reported_qty < inspection.sample_size:
            return
        if inspection.activity_ids.filtered(
                lambda a: a.summary == 'First article samples ready'):
            return
        inspection.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=self._fai_activity_user(inspection).id,
            summary=_('First article samples ready'),
            note=_('%(count)s first-article units were reported on '
                   '%(order)s; inspection can start.',
                   count=inspection.sample_size, order=self.name),
        )

    # ------------------------------------------------------------------
    # 可见性：首件检验单入口
    # ------------------------------------------------------------------
    def action_open_fai_inspections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('First Article Inspections'),
            'res_model': 'sn.wsd.quality.inspection',
            'view_mode': 'list,form',
            'domain': [('mes_order_id', '=', self.id),
                       ('inspection_type', '=', 'fai')],
            'context': {'default_mes_order_id': self.id,
                        'default_inspection_type': 'fai'},
        }


class QualityInspectionFai(models.Model):
    """FAI 判定联动（add-mes-fai）：done+fail 开新一轮；FAI 严格校验。"""

    _inherit = 'sn.wsd.quality.inspection'

    x_fai_round_number = fields.Integer(
        string='FAI Round', compute='_compute_x_fai_round_number',
    )
    x_fai_reported_qty = fields.Float(
        string='FAI Reported Qty', compute='_compute_x_fai_reported_qty',
        help='First-article units accumulated on the first-article '
             'operation since this round opened. Truth source: OK '
             'quantities of the operation reports of this MES order '
             '(report mode has no serial identities).',
    )
    x_fai_reported_base = fields.Float(
        string='FAI Reported Base',
        help='OK quantity already reported on the first-article operation '
             'when this round opened; current round = total - base. '
             'Snapshot instead of timestamps: datetime columns are '
             'second-precise and rounds can open within the same second.',
    )

    def _fai_reported_total(self):
        self.ensure_one()
        order = self.mes_order_id
        if not order or not self.scheme_id.operation_id:
            return 0.0
        reports = self.env['sn.wsd.mes.operation.report'].search([
            ('mes_order_id', '=', order.id),
            ('route_operation_id.operation_id', '=',
             self.scheme_id.operation_id.id),
        ])
        return sum(reports.mapped('qty_ok'))

    @api.depends('mes_order_id.sn_report_ids.qty_ok',
                 'mes_order_id.sn_report_ids.route_operation_id',
                 'scheme_id', 'x_fai_reported_base')
    def _compute_x_fai_reported_qty(self):
        for inspection in self:
            if inspection.mes_order_id.x_manage_mode == 'report':
                inspection.x_fai_reported_qty =                     inspection._fai_reported_total()                     - inspection.x_fai_reported_base
            else:
                inspection.x_fai_reported_qty = 0.0

    @api.depends('mes_order_id', 'mes_order_id.x_fai_inspection_ids')
    def _compute_x_fai_round_number(self):
        for inspection in self:
            rounds = inspection.mes_order_id.x_fai_inspection_ids
            inspection.x_fai_round_number = len(rounds)

    def action_done(self):
        for inspection in self.filtered(
                lambda i: i.inspection_type == 'fai' and i.state != 'done'):
            pending = inspection.line_ids.filtered(
                lambda line: line.result == 'pending')
            if pending:
                raise UserError(_(
                    'First article inspection: complete every item '
                    '(required or not) before finishing.'))
            if inspection.mes_order_id.x_manage_mode == 'report':
                arrived = inspection.x_fai_reported_qty
            else:
                arrived = len(inspection.x_fai_arrived_serial_ids)
            if arrived < inspection.sample_size:
                raise UserError(_(
                    'First article inspection: only %(arrived)s of %(need)s '
                    'samples reached the first-article operation; wait for '
                    'the full sample set.', arrived=arrived,
                    need=inspection.sample_size))
        res = super().action_done()
        # FAI 二元判定：非 pass 即判退（含 partial——任一项不符即 NG），
        # 保持投入限流并开新一轮（每轮一张新单，FPY 可算）
        for inspection in self.filtered(
                lambda i: i.inspection_type == 'fai' and i.mes_order_id
                and i.result != 'pass'):
            inspection.mes_order_id._fai_create_round(inspection.scheme_id)
        return res

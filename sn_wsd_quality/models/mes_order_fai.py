from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

FAI_CONFIRM_MINUTES = 30


class MesOrderFai(models.Model):
    """首件检验（FAI）接线（add-mes-fai）：上线触发、投入限流、
    出站登记、判定联动。全部钩子在质量模块继承制令单实现，
    sn_wsd_mrp 主链不感知 FAI。"""

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

    @api.depends('x_fai_inspection_ids.state',
                 'x_fai_inspection_ids.result',
                 'x_fai_inspection_ids.x_fai_serial_ids',
                 'x_fai_inspection_ids.x_fai_arrived_serial_ids')
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
            order.x_fai_sample_count = len(current.x_fai_serial_ids)
            order.x_fai_sample_done = len(current.x_fai_arrived_serial_ids)
            order.x_fai_inspection_count = len(inspections)

    # ------------------------------------------------------------------
    # 触发：上线（每次上线必检，含同单再次上线→新一轮）
    # ------------------------------------------------------------------
    def action_online(self):
        res = super().action_online()
        self.filtered(
            lambda o: o.x_manage_mode == 'station')._fai_on_online()
        return res

    def _fai_on_online(self):
        Inspection = self.env['sn.wsd.quality.inspection']
        for order in self:
            scheme = Inspection._find_scheme(
                'fai', product=order.production_id.product_id,
                production=order.production_id)
            if not scheme or not scheme.x_fai_operation_id:
                continue  # 未命中方案 / 方案未配首件工序 → 不触发
            order._fai_create_round(scheme)

    def _fai_create_round(self, scheme):
        self.ensure_one()
        route_op = self.x_route_operation_ids.filtered(
            lambda r: r.operation_id == scheme.x_fai_operation_id)[:1]
        inspection = self.env['sn.wsd.quality.inspection'].create_from_scheme(
            scheme, {
                'mes_order_id': self.id,
                'production_id': self.production_id.id,
                'product_id': self.production_id.product_id.id,
                'production_line_id': self.production_line_id.id,
                'route_operation_id': route_op.id,
            })
        # 30 分钟首件确认提醒（不硬拦，add-mes-fai 决策）
        inspection.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=inspection.inspector_id.id or self.env.user.id,
            date_deadline=fields.Date.context_today(
                self) + timedelta(days=1),
            summary=_('First article confirmation'),
            note=_('Confirm round %(round)s of %(order)s within 30 minutes.',
                   round=inspection.x_fai_round_number, order=self.name),
        )
        return inspection

    # ------------------------------------------------------------------
    # 投入限流：样本未满 N 放行并登记，满 N 且未判定通过则拦
    # ------------------------------------------------------------------
    def enter_station(self, serial_identity, route_operation,
                      workcenter=False):
        self.ensure_one()
        if self.x_manage_mode == 'station' and route_operation.x_allow_entry:
            self._fai_gate_feeding(serial_identity)
        res = super().enter_station(
            serial_identity, route_operation, workcenter=workcenter)
        if self.x_manage_mode == 'station' and route_operation.x_allow_entry:
            self._fai_register_sample(serial_identity)
        return res

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
        if route_operation.operation_id != inspection.scheme_id.x_fai_operation_id:
            return  # 非首件工序的出站不参与样本判定
        if result == 'ok':
            if serial_identity not in inspection.x_fai_arrived_serial_ids:
                inspection.x_fai_arrived_serial_ids = [(4, serial_identity.id)]
            if len(inspection.x_fai_arrived_serial_ids) >= inspection.sample_size \
                    and inspection.state == 'open':
                inspection.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=inspection.inspector_id.id or self.env.user.id,
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

from odoo import _, api, fields, models, tools

_SETTLE_CTE = """
    s_amt AS (
        SELECT s.mes_order_id, s.route_operation_id,
               SUM(CASE WHEN COALESCE(s.x_rate_type, 'piece') = 'piece' THEN sp.amount ELSE 0 END) AS piece_amount,
               SUM(CASE WHEN s.x_rate_type = 'hour' THEN sp.amount ELSE 0 END) AS hour_amount
          FROM sn_wsd_piece_settlement_participant sp
          JOIN sn_wsd_piece_settlement s ON s.id = sp.settlement_id
         WHERE s.state = 'confirmed'
         GROUP BY 1, 2
    )"""


class SnWsdLaborAnalysis(models.Model):
    """工时分析（制令单 × 工序）：实际工时 vs 标准工时、小时产出、人均效率、人工金额。

    实际人工工时 = 已确认的生产/返修/试产工时（停机/异常单列，不计入）；
    标准工时 = 合格数 × 工序标准节拍(秒/件) ÷ 3600（标准节拍取工艺路线工序）；
    工时效率 = 标准工时 ÷ 实际人工工时；人均小时产出 = 合格数 ÷ 实际人工工时；
    人工金额 = 已确认结算单的参与人实得金额（计件 + 计时）。"""
    _name = 'sn.wsd.labor.analysis'
    _description = '工时分析'
    _auto = False
    _order = 'mes_order_id desc, sequence'

    mes_order_id = fields.Many2one('sn.wsd.mes.order', string='制令单', readonly=True)
    route_operation_id = fields.Many2one('sn.wsd.mes.order.route.operation', string='工序', readonly=True)
    sequence = fields.Integer(string='序号', readonly=True)
    company_id = fields.Many2one('res.company', string='公司', readonly=True)
    product_id = fields.Many2one('product.product', string='产品', readonly=True)
    production_line_id = fields.Many2one('sn.mrp.production.line', string='线体', readonly=True)
    rate_type = fields.Char(string='计酬方式', readonly=True)
    qty_ok = fields.Float(string='合格数', digits=(12, 0), readonly=True)
    headcount = fields.Integer(string='人数', readonly=True, aggregator='max')
    man_hours = fields.Float(string='实际工时', digits=(10, 2), readonly=True)
    rework_hours = fields.Float(string='返修工时', digits=(10, 2), readonly=True)
    std_seconds = fields.Float(string='标准节拍(秒/件)', digits=(10, 1), readonly=True, aggregator=None)
    std_hours = fields.Float(string='标准工时', digits=(10, 2), readonly=True)
    diff_hours = fields.Float(string='差异工时', digits=(10, 2), readonly=True,
                              help='实际工时 − 标准工时，正数表示超出标准')
    efficiency = fields.Float(string='工时效率(%)', digits=(6, 1), readonly=True, aggregator='avg')
    uph = fields.Float(string='人均小时产出', digits=(10, 1), readonly=True, aggregator='avg')
    piece_amount = fields.Float(string='计件金额', digits=(12, 2), readonly=True)
    hour_amount = fields.Float(string='计时金额', digits=(12, 2), readonly=True)
    labor_amount = fields.Float(string='人工金额', digits=(12, 2), readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
            WITH t AS (
                SELECT e.mes_order_id, e.route_operation_id,
                       SUM(CASE WHEN e.category IN ('production', 'trial') THEN e.hours ELSE 0 END) AS man_hours,
                       SUM(CASE WHEN e.category = 'rework' THEN e.hours ELSE 0 END) AS rework_hours,
                       SUM(CASE WHEN e.category IN ('production', 'trial') THEN e.qty_ok ELSE 0 END) AS qty_ok,
                       COUNT(DISTINCT e.employee_id) AS headcount
                  FROM sn_wsd_time_entry e
                 WHERE e.state = 'confirmed' AND e.category != 'downtime'
                   AND e.route_operation_id IS NOT NULL
                 GROUP BY 1, 2
            ), %s,
            k AS (
                SELECT mes_order_id, route_operation_id FROM t
                UNION SELECT mes_order_id, route_operation_id FROM s_amt
            )
            SELECT ro.id AS id, k.mes_order_id, k.route_operation_id, ro.sequence,
                   o.company_id, o.product_id, o.production_line_id,
                   op.x_pay_label AS rate_type,
                   COALESCE(t.qty_ok, 0) AS qty_ok,
                   COALESCE(t.headcount, 0) AS headcount,
                   COALESCE(t.man_hours, 0) AS man_hours,
                   COALESCE(t.rework_hours, 0) AS rework_hours,
                   COALESCE(ro.time_cycle_manual, 0) AS std_seconds,
                   COALESCE(t.qty_ok, 0) * COALESCE(ro.time_cycle_manual, 0) / 3600.0 AS std_hours,
                   COALESCE(t.man_hours, 0)
                       - COALESCE(t.qty_ok, 0) * COALESCE(ro.time_cycle_manual, 0) / 3600.0 AS diff_hours,
                   CASE WHEN COALESCE(t.man_hours, 0) > 0
                        THEN COALESCE(t.qty_ok, 0) * COALESCE(ro.time_cycle_manual, 0) / 36.0 / t.man_hours
                        ELSE 0 END AS efficiency,
                   CASE WHEN COALESCE(t.man_hours, 0) > 0 THEN t.qty_ok / t.man_hours ELSE 0 END AS uph,
                   COALESCE(s.piece_amount, 0) AS piece_amount,
                   COALESCE(s.hour_amount, 0) AS hour_amount,
                   COALESCE(s.piece_amount, 0) + COALESCE(s.hour_amount, 0) AS labor_amount
              FROM k
              JOIN sn_wsd_mes_order o ON o.id = k.mes_order_id
              JOIN sn_wsd_mes_order_route_operation ro ON ro.id = k.route_operation_id
              LEFT JOIN LATERAL (
                  SELECT CASE MAX(r.x_rate_type) WHEN 'hour' THEN '计时' ELSE '计件' END AS x_pay_label
                    FROM sn_wsd_piece_rate r
                   WHERE r.product_id = o.product_id AND r.operation_id = ro.operation_id
                     AND r.company_id = o.company_id
              ) op ON TRUE
              LEFT JOIN t ON t.mes_order_id = k.mes_order_id AND t.route_operation_id = k.route_operation_id
              LEFT JOIN s_amt s ON s.mes_order_id = k.mes_order_id
                               AND s.route_operation_id = k.route_operation_id
            )""" % (self._table, _SETTLE_CTE))

    def action_view_entries(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('工时记录'),
                'res_model': 'sn.wsd.time.entry', 'view_mode': 'list,form',
                'domain': [('mes_order_id', '=', self.mes_order_id.id),
                           ('route_operation_id', '=', self.route_operation_id.id)]}


class SnWsdLaborCost(models.Model):
    """制令单人工成本：工时 + 计件/计时金额 → 单位人工成本、单位工时。

    单位人工成本 = 人工金额（计件 + 计时）÷ 完工数量（产出工序合格数）；
    停机/异常工时单列，只做分析，不计薪、不摊进单件人工成本。"""
    _name = 'sn.wsd.labor.cost'
    _description = '制令单人工成本'
    _auto = False
    _order = 'mes_order_id desc'

    mes_order_id = fields.Many2one('sn.wsd.mes.order', string='制令单', readonly=True)
    company_id = fields.Many2one('res.company', string='公司', readonly=True)
    product_id = fields.Many2one('product.product', string='产品', readonly=True)
    production_line_id = fields.Many2one('sn.mrp.production.line', string='线体', readonly=True)
    man_hours = fields.Float(string='生产工时', digits=(10, 2), readonly=True)
    rework_hours = fields.Float(string='返修工时', digits=(10, 2), readonly=True)
    std_hours = fields.Float(string='标准工时', digits=(10, 2), readonly=True)
    downtime_hours = fields.Float(string='停机/异常工时', digits=(10, 2), readonly=True)
    piece_amount = fields.Float(string='计件金额', digits=(12, 2), readonly=True)
    hour_amount = fields.Float(string='计时金额', digits=(12, 2), readonly=True)
    labor_amount = fields.Float(string='人工金额合计', digits=(12, 2), readonly=True)
    completed_qty = fields.Float(string='完工数量', digits=(12, 0), compute='_compute_unit')
    unit_cost = fields.Float(string='单位人工成本(元/件)', digits=(12, 4), compute='_compute_unit')
    unit_hours = fields.Float(string='单位工时(分钟/件)', digits=(10, 2), compute='_compute_unit',
                              help='(生产工时 + 返修工时) × 60 ÷ 完工数量')
    efficiency = fields.Float(string='工时效率(%)', digits=(6, 1), compute='_compute_unit')

    @api.depends('mes_order_id', 'labor_amount', 'man_hours', 'rework_hours')
    def _compute_unit(self):
        for row in self:
            qty = row.mes_order_id.x_output_qty if row.mes_order_id else 0.0
            row.completed_qty = qty
            row.unit_cost = round(row.labor_amount / qty, 4) if qty else 0.0
            row.unit_hours = round((row.man_hours + row.rework_hours) * 60.0 / qty, 2) if qty else 0.0
            row.efficiency = round(row.std_hours / row.man_hours * 100.0, 1) if row.man_hours else 0.0

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
            WITH t AS (
                SELECT e.mes_order_id,
                       SUM(CASE WHEN e.category IN ('production', 'trial') THEN e.hours ELSE 0 END) AS man_hours,
                       SUM(CASE WHEN e.category = 'rework' THEN e.hours ELSE 0 END) AS rework_hours,
                       SUM(CASE WHEN e.category IN ('production', 'trial')
                                THEN e.qty_ok * COALESCE(ro.time_cycle_manual, 0) / 3600.0 ELSE 0 END) AS std_hours,
                       SUM(CASE WHEN e.category = 'downtime' THEN e.hours ELSE 0 END) AS downtime_hours
                  FROM sn_wsd_time_entry e
                  LEFT JOIN sn_wsd_mes_order_route_operation ro ON ro.id = e.route_operation_id
                 WHERE e.state = 'confirmed' AND e.mes_order_id IS NOT NULL
                 GROUP BY 1
            ), %s,
            s AS (SELECT mes_order_id, SUM(piece_amount) piece_amount, SUM(hour_amount) hour_amount
                    FROM s_amt GROUP BY 1)
            SELECT o.id AS id, o.id AS mes_order_id, o.company_id, o.product_id, o.production_line_id,
                   COALESCE(t.man_hours, 0) AS man_hours,
                   COALESCE(t.rework_hours, 0) AS rework_hours,
                   COALESCE(t.std_hours, 0) AS std_hours,
                   COALESCE(t.downtime_hours, 0) AS downtime_hours,
                   COALESCE(s.piece_amount, 0) AS piece_amount,
                   COALESCE(s.hour_amount, 0) AS hour_amount,
                   COALESCE(s.piece_amount, 0) + COALESCE(s.hour_amount, 0) AS labor_amount
              FROM sn_wsd_mes_order o
              LEFT JOIN t ON t.mes_order_id = o.id
              LEFT JOIN s ON s.mes_order_id = o.id
             WHERE t.mes_order_id IS NOT NULL OR s.mes_order_id IS NOT NULL
            )""" % (self._table, _SETTLE_CTE))

    def action_view_analysis(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('工时分析：%s', self.mes_order_id.name),
                'res_model': 'sn.wsd.labor.analysis', 'view_mode': 'list',
                'domain': [('mes_order_id', '=', self.mes_order_id.id)]}

    def action_view_entries(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('工时记录'),
                'res_model': 'sn.wsd.time.entry', 'view_mode': 'list,form',
                'domain': [('mes_order_id', '=', self.mes_order_id.id)]}

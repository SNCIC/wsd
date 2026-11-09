from odoo import fields, models
from odoo.tools import SQL


class SnWsdMesOrderStats(models.Model):
    """Read-time execution figures of the MES orders (SQL view).

    The order record itself no longer stores its execution quantities: a
    station pass only writes its own history/wip row, so parallel scans on the
    same order never contend for a shared row. Reporting reads this view
    instead -- the aggregation happens in the database, once per query, and
    stays usable as a pivot/graph measure (Odoo requires stored columns for
    those, which a plain non-stored compute cannot provide).

    Same counting rules as the order fields: station mode counts distinct SNs
    at the counter operations (entry = history + wip, output = OK passes),
    report mode sums the reported quantities there.
    """

    _name = 'sn.wsd.mes.order.stats'
    _description = 'MES Order Execution Statistics'
    _rec_name = 'mes_order_id'
    _order = 'date_plan desc, id desc'
    _auto = False

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', readonly=True,
    )
    date_plan = fields.Date(string='Plan Date', readonly=True)
    production_line_id = fields.Many2one(
        'mrp.workcenter', string='Production Line', readonly=True,
    )
    state = fields.Selection(
        [('released', 'Released'),
         ('picked', 'Picked'),
         ('in_progress', 'In Progress'),
         ('done', 'Done'),
         ('cancelled', 'Cancelled')],
        string='State', readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', readonly=True,
    )
    planned_qty = fields.Float(string='Planned Quantity', readonly=True)
    picked_qty = fields.Float(string='Picked Quantity', readonly=True)
    x_input_qty = fields.Float(string='Input Quantity', readonly=True)
    x_output_qty = fields.Float(string='Output Quantity', readonly=True)
    produced_qty = fields.Float(string='Produced Quantity', readonly=True)

    @property
    def _table_query(self):
        return SQL("""
            WITH entered AS (
                SELECT route_operation_id,
                       COUNT(DISTINCT serial_identity_id) AS qty
                  FROM (
                        SELECT route_operation_id, serial_identity_id
                          FROM sn_wsd_serial_operation_history
                        UNION
                        SELECT route_operation_id, serial_identity_id
                          FROM sn_wsd_serial_wip
                       ) reached
                 GROUP BY route_operation_id
            ), passed AS (
                SELECT route_operation_id,
                       COUNT(DISTINCT serial_identity_id) AS qty
                  FROM sn_wsd_serial_operation_history
                 WHERE result = 'ok'
                 GROUP BY route_operation_id
            ), reported AS (
                SELECT route_operation_id,
                       COALESCE(SUM(qty_ok), 0) AS ok_qty,
                       COALESCE(SUM(qty_ok + qty_ng + qty_scrap), 0) AS all_qty
                  FROM sn_wsd_mes_operation_report
                 GROUP BY route_operation_id
            )
            SELECT o.id,
                   o.id AS mes_order_id,
                   o.date_plan,
                   o.production_line_id,
                   o.state,
                   o.company_id,
                   o.planned_qty,
                   o.picked_qty,
                   CASE WHEN o.x_manage_mode = 'report'
                        THEN COALESCE(ri.all_qty, 0)
                        ELSE COALESCE(ei.qty, 0) END AS x_input_qty,
                   CASE WHEN o.x_manage_mode = 'report'
                        THEN COALESCE(ro.ok_qty, 0)
                        ELSE COALESCE(po.qty, 0) END AS x_output_qty,
                   CASE WHEN o.x_manage_mode = 'report'
                        THEN COALESCE(ro.ok_qty, 0)
                        ELSE COALESCE(po.qty, 0) END AS produced_qty
              FROM sn_wsd_mes_order o
              LEFT JOIN sn_wsd_mes_order_route r
                     ON r.id = o.x_mes_route_id
              LEFT JOIN entered ei
                     ON ei.route_operation_id = r.x_daily_input_operation_id
              LEFT JOIN passed po
                     ON po.route_operation_id = r.x_daily_output_operation_id
              LEFT JOIN reported ri
                     ON ri.route_operation_id = r.x_daily_input_operation_id
              LEFT JOIN reported ro
                     ON ro.route_operation_id = r.x_daily_output_operation_id
        """)

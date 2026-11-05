from odoo import _, fields, models
from odoo.tools import drop_view_if_exists

# SNs stuck at an operation: their pass count (OK and NG alike, counted
# after the latest closed repair order -- the cutoff that restarts the
# counters) reached the operation's pass cap AND the latest pass was NG
# (the board never passed). End/output operations are always capped at 1.
# The cap semantics mirror enter_station in sn_wsd_mrp.
_PENDING_SQL = """
    SELECT MAX(h.id) AS id,
           h.serial_identity_id,
           si.name AS serial_name,
           h.mes_order_id,
           h.route_operation_id,
           ro.name AS operation_name,
           COUNT(h.id) AS pass_count,
           CASE WHEN ro.x_allow_exit THEN 1 ELSE o.x_max_test_count END
               AS pass_cap,
           (ARRAY_AGG(h.result ORDER BY h.out_date, h.id))[COUNT(h.id)]
               AS last_result,
           MAX(h.out_date) AS last_pass_time,
           mo.company_id
      FROM sn_wsd_serial_operation_history h
      JOIN sn_wsd_serial_identity si ON si.id = h.serial_identity_id
      JOIN sn_wsd_mes_order_route_operation ro ON ro.id = h.route_operation_id
      JOIN sn_wsd_operation o ON o.id = ro.operation_id
      JOIN sn_wsd_mes_order mo ON mo.id = h.mes_order_id
     WHERE h.result IN ('ok', 'ng')
       AND mo.state NOT IN ('cancelled', 'done')
       AND NOT EXISTS (
               SELECT 1 FROM sn_wsd_repair_order r
                WHERE r.state NOT IN ('done', 'scrapped', 'cancel')
                  AND r.serial_identity_id = h.serial_identity_id)
       AND NOT EXISTS (
               SELECT 1 FROM sn_wsd_quality_issue q
                WHERE q.state IN ('open', 'analysis', 'repairing', 'verified')
                  AND q.serial_identity_id = h.serial_identity_id)
       -- > not >=: an NG written in the same second as the repair
       -- close precedes it (second-granular timestamps)
       AND h.out_date > COALESCE((
               SELECT MAX(r2.repair_time) FROM sn_wsd_repair_order r2
                WHERE r2.state = 'done' AND r2.result = 'ok'
                  AND r2.serial_identity_id = h.serial_identity_id),
               TIMESTAMP '-infinity')
     GROUP BY h.serial_identity_id, si.name, h.mes_order_id,
              h.route_operation_id, ro.name, ro.x_allow_exit,
              o.x_max_test_count, mo.company_id
    HAVING COUNT(h.id) >= CASE WHEN ro.x_allow_exit THEN 1
                               ELSE o.x_max_test_count END
       AND (ARRAY_AGG(h.result ORDER BY h.out_date, h.id))[COUNT(h.id)] = 'ng'
"""


class SnWsdRepairPending(models.Model):
    _name = 'sn.wsd.repair.pending'
    _description = 'SNs Waiting for Repair'
    _auto = False
    _order = 'last_pass_time desc'

    serial_name = fields.Char(string='SN', readonly=True)
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='Physical SN', readonly=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', readonly=True)
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Failed Operation',
        readonly=True)
    operation_name = fields.Char(string='Operation', readonly=True)
    pass_count = fields.Integer(string='Pass Count', readonly=True)
    pass_cap = fields.Integer(string='Pass Cap', readonly=True)
    last_result = fields.Char(string='Last Result', readonly=True)
    last_pass_time = fields.Datetime(string='Last Pass Time', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            'CREATE OR REPLACE VIEW %s AS (%s)' % (self._table, _PENDING_SQL))

    def action_create_repair_order(self):
        """Open the repair order form prefilled from the failed passes."""
        self.ensure_one()
        History = self.env['sn.wsd.serial.operation.history']
        defect_lines = []
        seen = set()
        for row in History.search([
            ('serial_identity_id', '=', self.serial_identity_id.id),
            ('route_operation_id', '=', self.route_operation_id.id),
            ('result', '=', 'ng'),
            ('defect_code_id', '!=', False),
        ], order='out_date desc', limit=10):
            if row.defect_code_id.id in seen:
                continue
            seen.add(row.defect_code_id.id)
            defect_lines.append((0, 0, {
                'defect_code_id': row.defect_code_id.id,
                'qty': 1,
            }))
        context = {
            'default_serial_no': self.serial_name,
            'default_mes_order_id': self.mes_order_id.id,
            'default_route_operation_id': self.route_operation_id.id,
            'default_repair_entry_route_operation_id':
                self.route_operation_id.id,
            'default_repair_mode':
                'sn' if self.mes_order_id.x_manage_mode == 'station'
                else 'qty',
            'default_defect_qty': 1.0,
            'default_repair_qty': 1.0,
        }
        if defect_lines:
            context['default_defect_line_ids'] = defect_lines
        context['default_serial_identity_id'] = self.serial_identity_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Repair Order'),
            'res_model': 'sn.wsd.repair.order',
            'view_mode': 'form',
            'target': 'current',
            'context': context,
        }

"""SN full-trace timeline: one read-only SQL view, one SN, every event.

UNION ALL of the nine traceability sources into common columns so a single
search on the SN answers: which order, which operation, when, which device,
who, which materials. Test items stay out of the timeline (the test row's
summary shows item/NG counts; open the source record for details). Sources
whose tables are absent (module not installed) are skipped at view creation.
"""

from odoo import fields, models
from odoo.tools.sql import drop_view_if_exists, table_exists

EVENT_TYPE_SELECTION = [
    ('station', 'Station Pass'),
    ('test', 'Test'),
    ('material', 'Material'),
    ('component', 'Component'),
    ('nameplate', 'Nameplate'),
    ('pack', 'Pack'),
    ('quality', 'Quality'),
    ('repair', 'Repair'),
    ('scrap', 'Scrap'),
]

_ID_BASE = 1000000000

# shared joins: identity + operation/workcenter names through the MES route
_HIST_JOIN = """
    JOIN sn_wsd_serial_identity i ON i.id = {src}.serial_identity_id
    LEFT JOIN sn_wsd_mes_order_route_operation ro ON ro.id = {src}.route_operation_id
    LEFT JOIN sn_wsd_operation op ON op.id = ro.operation_id
    LEFT JOIN mrp_workcenter wc ON wc.id = {src}.workcenter_id
    LEFT JOIN sn_wsd_mes_order mo ON mo.id = {src}.mes_order_id
"""

_BRANCHES = [
    # (source number, required tables, SQL)
    (1, ['sn_wsd_serial_operation_history'], f"""
        SELECT {_ID_BASE} + h.id AS id,
               h.serial_identity_id AS serial_identity_id,
               i.name AS sn,
               COALESCE(h.out_date, h.in_date, h.create_date) AS event_time,
               'station' AS event_type,
               mo.name AS order_no,
               op.name AS operation,
               wc.name AS station,
               h.operator_code AS operator,
               '' AS object_ref,
               '' AS summary,
               h.result AS result,
               to_char(COALESCE(h.out_date, h.in_date, h.create_date), 'HH24:MI:SS') AS time_of_day,
               CASE WHEN h.result = 'ng' THEN 1 ELSE 0 END AS is_ng,
               'sn.wsd.serial.operation.history' AS source_model,
               h.id AS source_id,
               h.company_id AS company_id
        FROM sn_wsd_serial_operation_history h
        LEFT JOIN mrp_workcenter wc ON wc.id = h.workcenter_id
        LEFT JOIN sn_wsd_mes_order_route_operation ro ON ro.id = h.route_operation_id
        LEFT JOIN sn_wsd_operation op ON op.id = ro.operation_id
        LEFT JOIN sn_wsd_mes_order mo ON mo.id = h.mes_order_id
        JOIN sn_wsd_serial_identity i ON i.id = h.serial_identity_id
    """),
    (2, ['sn_wsd_mes_test_result'], f"""
        SELECT {2 * _ID_BASE} + t.id, t.serial_identity_id, i.name, t.test_time,
               'test', mo.name, op.name,
               COALESCE(NULLIF(t.equipment_sn, ''), wc.name),
               t.operator_code,
               COALESCE(NULLIF(t.tooling_sns, ''), ''),
               (SELECT CASE WHEN count(*) = 0 THEN '' ELSE
                       count(*) || ' items (' ||
                       coalesce(sum((d.result = 'ng')::int), 0) || ' NG)'
                    END
                FROM sn_wsd_mes_test_result_detail d
                WHERE d.test_result_id = t.id),
               t.result, to_char(t.test_time, 'HH24:MI:SS'), CASE WHEN t.result = 'ng' THEN 1 ELSE 0 END,
               'sn.wsd.mes.test.result', t.id, t.company_id
        FROM sn_wsd_mes_test_result t
        LEFT JOIN sn_wsd_mes_order mo ON mo.id = t.mes_order_id
        LEFT JOIN sn_wsd_mes_order_route_operation ro ON ro.id = t.route_operation_id
        LEFT JOIN sn_wsd_operation op ON op.id = ro.operation_id
        LEFT JOIN mrp_workcenter wc ON wc.id = t.workcenter_id
        JOIN sn_wsd_serial_identity i ON i.id = t.serial_identity_id
    """),
    (3, ['sn_smt_material_consumption', 'sn_smt_online_material'], f"""
        SELECT {3 * _ID_BASE} + c.id, c.serial_identity_id, i.name, c.consumed_at,
               'material', mo.name, op.name,
               'DEV' || om.device_seq || '.' || om.table_no,
               c.operator_code,
               COALESCE(NULLIF(om.required_item_code, ''), '') || ' / ' ||
                   COALESCE(c.material_sn, ''),
               c.point_qty || ' pt',
               '', to_char(c.consumed_at, 'HH24:MI:SS'), 0,
               'sn.smt.material.consumption', c.id, c.company_id
        FROM sn_smt_material_consumption c
        LEFT JOIN sn_smt_online_material om ON om.id = c.online_material_id
        LEFT JOIN sn_wsd_mes_order mo ON mo.id = c.mes_order_id
        LEFT JOIN sn_wsd_mes_order_route_operation ro ON ro.id = c.route_operation_id
        LEFT JOIN sn_wsd_operation op ON op.id = ro.operation_id
        JOIN sn_wsd_serial_identity i ON i.id = c.serial_identity_id
    """),
    (4, ['sn_wsd_meter_component_binding'], f"""
        SELECT {4 * _ID_BASE} + b.id, b.serial_identity_id, i.name, b.event_time,
               'component', mo.name, op.name, wc.name,
               b.operator_code,
               b.component_sn || ' (' || b.component_type || ')',
               '', b.event_type, to_char(b.event_time, 'HH24:MI:SS'), 0,
               'sn.wsd.meter.component.binding', b.id, b.company_id
        FROM sn_wsd_meter_component_binding b
        LEFT JOIN mrp_workcenter wc ON wc.id = b.workcenter_id
        LEFT JOIN sn_wsd_mes_order_route_operation ro ON ro.id = b.route_operation_id
        LEFT JOIN sn_wsd_operation op ON op.id = ro.operation_id
        LEFT JOIN sn_wsd_mes_order mo ON mo.id = ro.mes_order_id
        JOIN sn_wsd_serial_identity i ON i.id = b.serial_identity_id
    """),
    (5, ['sn_wsd_serial_binding'], f"""
        SELECT {5 * _ID_BASE} + sb.id, sb.bound_serial_identity_id, i2.name,
               sb.binding_date,
               'nameplate', '', '', '', '',
               i1.name || ' -> ' || i2.name,
               CASE WHEN sb.is_current THEN 'current' ELSE 'history' END,
               '', to_char(sb.binding_date, 'HH24:MI:SS'), 0,
               'sn.wsd.serial.binding', sb.id, sb.company_id
        FROM sn_wsd_serial_binding sb
        JOIN sn_wsd_serial_identity i1 ON i1.id = sb.serial_identity_id
        JOIN sn_wsd_serial_identity i2 ON i2.id = sb.bound_serial_identity_id
        WHERE sb.binding_type = 'nameplate'
    """),
    (6, ['sn_wsd_meter_pack_record'], f"""
        SELECT {6 * _ID_BASE} + p.id, p.serial_identity_id, i.name, p.pack_time,
               'pack', mo.name, op.name, '',
               p.operator_code,
               trim(both ' /' from
                    COALESCE('Box ' || NULLIF(p.carton_no, '') || ' / ', '') ||
                    COALESCE('Pallet ' || NULLIF(p.pallet_no, ''), '')),
               '', p.scan_check_result, to_char(p.pack_time, 'HH24:MI:SS'), CASE WHEN p.scan_check_result = 'fail' THEN 1 ELSE 0 END,
               'sn.wsd.meter.pack.record', p.id, p.company_id
        FROM sn_wsd_meter_pack_record p
        LEFT JOIN sn_wsd_mes_order_route_operation ro ON ro.id = p.pack_route_operation_id
        LEFT JOIN sn_wsd_operation op ON op.id = ro.operation_id
        LEFT JOIN sn_wsd_mes_order mo ON mo.id = ro.mes_order_id
        JOIN sn_wsd_serial_identity i ON i.id = p.serial_identity_id
    """),
    (7, ['sn_wsd_quality_issue'], f"""
        SELECT {7 * _ID_BASE} + q.id, q.serial_identity_id, i.name, q.create_date,
               'quality', q.name, '', '', '', '', '', q.state, to_char(q.create_date, 'HH24:MI:SS'), 0,
               'sn.wsd.quality.issue', q.id, q.company_id
        FROM sn_wsd_quality_issue q
        JOIN sn_wsd_serial_identity i ON i.id = q.serial_identity_id
    """),
    (8, ['sn_wsd_repair_order'], f"""
        SELECT {8 * _ID_BASE} + r.id, r.serial_identity_id, i.name, r.create_date,
               'repair', r.name, '', '', '', '', '', r.state, to_char(r.create_date, 'HH24:MI:SS'), 0,
               'sn.wsd.repair.order', r.id, r.company_id
        FROM sn_wsd_repair_order r
        JOIN sn_wsd_serial_identity i ON i.id = r.serial_identity_id
    """),
    (9, ['sn_wsd_scrap_record'], f"""
        SELECT {9 * _ID_BASE} + s.id, s.serial_identity_id, i.name, s.scrap_time,
               'scrap', s.name, '', '', '', '', '', s.state, to_char(s.scrap_time, 'HH24:MI:SS'), 0,
               'sn.wsd.scrap.record', s.id, s.company_id
        FROM sn_wsd_scrap_record s
        JOIN sn_wsd_serial_identity i ON i.id = s.serial_identity_id
    """),
]


class SnTraceEvent(models.Model):
    _name = 'sn.wsd.trace.event'
    _description = 'SN Trace Event'
    _auto = False
    _order = 'event_time asc, id asc'
    _rec_name = 'sn'

    serial_identity_id = fields.Many2one('sn.wsd.serial.identity', readonly=True)
    sn = fields.Char(string='SN', readonly=True)
    event_time = fields.Datetime(string='Event Time', readonly=True)
    event_type = fields.Selection(
        EVENT_TYPE_SELECTION, string='Event Type', readonly=True)
    order_no = fields.Char(
        string='Order / Document', readonly=True,
        help='MES order for production events; the document number of the '
             'quality/repair/scrap ticket for those.')
    operation = fields.Char(string='Operation', readonly=True)
    station = fields.Char(
        string='Station / Device', readonly=True,
        help='Work center for passes, device SN for tests, '
             'machine.table for material deductions.')
    operator = fields.Char(string='Operator', readonly=True)
    object_ref = fields.Char(
        string='Object', readonly=True,
        help='Material reel, component SN, nameplate mapping or box/pallet '
             'involved in the event.')
    summary = fields.Char(string='Summary', readonly=True)
    result = fields.Char(string='Result', readonly=True)
    time_of_day = fields.Char(
        string='Time', readonly=True,
        help='HH:MM:SS part of the event time; group by day for the date.')
    is_ng = fields.Integer(
        string='NG', readonly=True,
        help='1 when the event result is NG/fail; sums as the NG count in '
             'group headers.')
    source_model = fields.Char(string='Source Model', readonly=True)
    source_id = fields.Integer(string='Source ID', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        # only union the branches whose source tables exist, so the view
        # stays valid without some optional modules installed
        branches = []
        for _num, tables, sql in _BRANCHES:
            if all(table_exists(self.env.cr, t) for t in tables):
                branches.append(sql)
        if not branches:
            return
        self.env.cr.execute(
            'CREATE OR REPLACE VIEW %s AS (%s)'
            % (self._table, '\nUNION ALL\n'.join(branches)))

    def action_open_source(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.source_model,
            'res_id': self.source_id,
            'views': [[False, 'form']],
            'target': 'current',
        }

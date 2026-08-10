from odoo import api, fields, models, _
from odoo.tools import drop_view_if_exists
from odoo.tools.sql import table_exists


def _tables_exist(cr, *table_names):
    return all(table_exists(cr, table_name) for table_name in table_names)


class SnWsdProductionProgressReport(models.Model):
    _name = 'sn.wsd.production.progress.report'
    _description = 'Production Progress Report'
    _auto = False
    _order = 'production_id desc'

    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    production_name = fields.Char(string='Manufacturing Reference', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    route_id = fields.Many2one('sn.wsd.process.route', string='Process Route', readonly=True)
    product_qty = fields.Float(string='Order Qty', readonly=True)
    qty_output_total = fields.Float(string='Cumulative Output Qty', readonly=True)
    qty_pass = fields.Float(string='Pass Qty', readonly=True)
    qty_fail = fields.Float(string='Fail Qty', readonly=True)
    qty_scrap = fields.Float(string='Scrap Qty', readonly=True)
    qty_rework = fields.Float(string='Rework Qty', readonly=True)
    progress_rate = fields.Float(string='Progress Rate (%)', readonly=True)
    pass_rate = fields.Float(string='Pass Rate (%)', readonly=True)
    open_workorder_count = fields.Integer(string='Open Workorders', readonly=True)
    done_workorder_count = fields.Integer(string='Done Workorders', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    p.id AS id,
                    p.id AS production_id,
                    p.name AS production_name,
                    p.company_id,
                    p.product_id,
                    p.x_process_route_id AS route_id,
                    p.product_qty,
                    COALESCE(SUM(wo.qty_produced), 0.0) AS qty_output_total,
                    COALESCE(SUM(wo.x_meter_qty_pass), 0.0) AS qty_pass,
                    COALESCE(SUM(wo.x_meter_qty_fail), 0.0) AS qty_fail,
                    COALESCE(SUM(wo.x_meter_qty_scrap), 0.0) AS qty_scrap,
                    COALESCE(SUM(wo.x_meter_qty_rework), 0.0) AS qty_rework,
                    CASE
                        WHEN p.product_qty = 0 THEN 0.0
                        ELSE ROUND((COALESCE(MAX(wo.qty_produced), 0.0) / p.product_qty * 100.0)::numeric, 2)
                    END AS progress_rate,
                    CASE
                        WHEN COALESCE(SUM(wo.qty_produced), 0.0) = 0 THEN 0.0
                        ELSE ROUND((COALESCE(SUM(wo.x_meter_qty_pass), 0.0) / NULLIF(SUM(wo.qty_produced), 0.0) * 100.0)::numeric, 2)
                    END AS pass_rate,
                    COUNT(*) FILTER (WHERE wo.state NOT IN ('done', 'cancel')) AS open_workorder_count,
                    COUNT(*) FILTER (WHERE wo.state = 'done') AS done_workorder_count
                FROM mrp_production p
                LEFT JOIN mrp_workorder wo ON wo.production_id = p.id
                GROUP BY p.id, p.name, p.company_id, p.product_id, p.x_process_route_id, p.product_qty
            )
        """)


class SnWsdOperationDailyReport(models.Model):
    _name = 'sn.wsd.operation.daily.report'
    _description = 'Operation Daily Report'
    _auto = False
    _order = 'report_date desc, workcenter_code, workorder_id'

    report_date = fields.Date(string='Report Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Workorder', readonly=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Execution Work Center', readonly=True)
    operation_id = fields.Many2one('mrp.routing.workcenter', string='Operation', readonly=True)
    mes_workcenter_id = fields.Many2one('mrp.workcenter', string='MES Work Center', readonly=True)
    workcenter_code = fields.Char(string='Work Center Code', readonly=True)
    operation_type = fields.Selection(related='workorder_id.x_meter_operation_type', string='Operation Type', readonly=True)
    qty_in = fields.Float(string='Input Qty', readonly=True)
    qty_ok = fields.Float(string='Pass Qty', readonly=True)
    qty_ng = fields.Float(string='NG Qty', readonly=True)
    qty_scrap = fields.Float(string='Scrap Qty', readonly=True)
    qty_repair = fields.Float(string='Repair Qty', readonly=True)
    qty_rework = fields.Float(string='Rework Qty', readonly=True)
    qty_out = fields.Float(string='Cumulative Output Qty', readonly=True)
    pass_rate = fields.Float(string='Pass Rate (%)', readonly=True)
    ng_rate = fields.Float(string='NG Rate (%)', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(r.id) AS id,
                    DATE(r.event_time) AS report_date,
                    r.company_id,
                    r.production_id,
                    mp.product_id,
                    r.workorder_id,
                    r.workcenter_id,
                    r.operation_id,
                    wc.id AS mes_workcenter_id,
                    COALESCE(r.payload->>'workcenter_code', r.payload->>'station_code', wo.x_meter_workcenter_code, wc.code) AS workcenter_code,
                    SUM(r.qty_in) AS qty_in,
                    SUM(r.qty_ok) AS qty_ok,
                    SUM(r.qty_ng) AS qty_ng,
                    SUM(r.qty_scrap) AS qty_scrap,
                    SUM(r.qty_repair) AS qty_repair,
                    SUM(r.qty_rework) AS qty_rework,
                    SUM(r.qty_out) AS qty_out,
                    CASE
                        WHEN SUM(r.qty_out) = 0 THEN 0.0
                        ELSE ROUND((SUM(r.qty_ok) / NULLIF(SUM(r.qty_out), 0.0) * 100.0)::numeric, 2)
                    END AS pass_rate,
                    CASE
                        WHEN SUM(r.qty_out) = 0 THEN 0.0
                        ELSE ROUND((SUM(r.qty_ng) / NULLIF(SUM(r.qty_out), 0.0) * 100.0)::numeric, 2)
                    END AS ng_rate
                FROM mrp_workorder_report r
                JOIN mrp_workorder wo ON wo.id = r.workorder_id
                LEFT JOIN mrp_production mp ON mp.id = r.production_id
                LEFT JOIN mrp_workcenter wc ON wc.id = wo.x_mes_workcenter_id
                WHERE r.state != 'cancelled'
                GROUP BY DATE(r.event_time), r.company_id, r.production_id, mp.product_id, r.workorder_id, r.workcenter_id, r.operation_id, wc.id, COALESCE(r.payload->>'workcenter_code', r.payload->>'station_code', wo.x_meter_workcenter_code, wc.code)
            )
        """)


class SnWsdTestPassRateReport(models.Model):
    _name = 'sn.wsd.test.pass.rate.report'
    _description = 'Test Pass Rate Report'
    _auto = False
    _order = 'report_date desc, test_type, workcenter_code'

    report_date = fields.Date(string='Report Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Workorder', readonly=True)
    mes_workcenter_id = fields.Many2one('mrp.workcenter', string='MES Work Center', readonly=True)
    workcenter_code = fields.Char(string='Work Center Code', readonly=True)
    test_type = fields.Selection(
        [('programming', 'Programming'), ('inspection', 'Inspection'), ('aging', 'Aging'), ('calibration', 'Calibration'), ('final_test', 'Final Test'), ('packaging', 'Packaging')],
        string='Test Type',
        readonly=True,
    )
    total_count = fields.Integer(string='Total Count', readonly=True)
    pass_count = fields.Integer(string='Pass Count', readonly=True)
    fail_count = fields.Integer(string='Fail Count', readonly=True)
    hold_count = fields.Integer(string='Hold Count', readonly=True)
    pass_rate = fields.Float(string='Pass Rate (%)', readonly=True)
    avg_cycle_time_sec = fields.Float(string='Avg Cycle Time (sec)', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(t.id) AS id,
                    DATE(t.test_time) AS report_date,
                    t.company_id,
                    t.production_id,
                    t.workorder_id,
                    t.workcenter_id AS mes_workcenter_id,
                    t.workcenter_code,
                    t.test_type,
                    COUNT(*) AS total_count,
                    COUNT(*) FILTER (WHERE t.result = 'pass') AS pass_count,
                    COUNT(*) FILTER (WHERE t.result = 'fail') AS fail_count,
                    COUNT(*) FILTER (WHERE t.result = 'hold') AS hold_count,
                    CASE
                        WHEN COUNT(*) = 0 THEN 0.0
                        ELSE ROUND(COUNT(*) FILTER (WHERE t.result = 'pass')::numeric / COUNT(*)::numeric * 100.0, 2)
                    END AS pass_rate,
                    AVG(COALESCE(t.cycle_time_sec, 0.0)) AS avg_cycle_time_sec
                FROM sn_wsd_mes_test_result t
                GROUP BY DATE(t.test_time), t.company_id, t.production_id, t.workorder_id, t.workcenter_id, t.workcenter_code, t.test_type
            )
        """)


class SnWsdAgingLossReport(models.Model):
    _name = 'sn.wsd.aging.loss.report'
    _description = 'Aging Loss Report'
    _auto = False
    _order = 'start_date desc, batch_id desc'

    batch_id = fields.Many2one('sn.wsd.meter.aging.batch', string='Aging Batch', readonly=True)
    batch_name = fields.Char(string='Batch', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Workorder', readonly=True)
    equipment_id = fields.Many2one('maintenance.equipment', string='Equipment', readonly=True)
    start_date = fields.Date(string='Start Date', readonly=True)
    planned_hours = fields.Float(string='Planned Hours', readonly=True)
    actual_hours = fields.Float(string='Actual Hours', readonly=True)
    load_qty = fields.Integer(string='Load Qty', readonly=True)
    pass_qty = fields.Integer(string='Pass Qty', readonly=True)
    fail_qty = fields.Integer(string='Fail Qty', readonly=True)
    hold_qty = fields.Integer(string='Hold Qty', readonly=True)
    loss_qty = fields.Integer(string='Loss Qty', readonly=True)
    loss_rate = fields.Float(string='Loss Rate (%)', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    b.id AS id,
                    b.id AS batch_id,
                    b.name AS batch_name,
                    b.company_id,
                    b.production_id,
                    b.workorder_id,
                    b.equipment_id,
                    DATE(b.start_time) AS start_date,
                    b.planned_hours,
                    b.actual_hours,
                    COUNT(l.id) AS load_qty,
                    COUNT(l.id) FILTER (WHERE l.result = 'pass') AS pass_qty,
                    COUNT(l.id) FILTER (WHERE l.result = 'fail') AS fail_qty,
                    COUNT(l.id) FILTER (WHERE l.result = 'hold') AS hold_qty,
                    COUNT(l.id) FILTER (WHERE l.result IN ('fail', 'hold')) AS loss_qty,
                    CASE
                        WHEN COUNT(l.id) = 0 THEN 0.0
                        ELSE ROUND(COUNT(l.id) FILTER (WHERE l.result IN ('fail', 'hold'))::numeric / COUNT(l.id)::numeric * 100.0, 2)
                    END AS loss_rate
                FROM sn_wsd_meter_aging_batch b
                LEFT JOIN sn_wsd_meter_aging_batch_line l ON l.batch_id = b.id
                GROUP BY b.id, b.name, b.company_id, b.production_id, b.workorder_id, b.equipment_id, DATE(b.start_time), b.planned_hours, b.actual_hours
            )
        """)


class SnWsdRepairClosureReport(models.Model):
    _name = 'sn.wsd.repair.closure.report'
    _description = 'Repair Closure Report'
    _auto = False
    _order = 'report_date desc, workorder_id'

    report_date = fields.Date(string='Report Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Source Workorder', readonly=True)
    defect_code_id = fields.Many2one('sn.wsd.quality.defect.code', string='Defect Code', readonly=True)
    repair_mode = fields.Selection([('sn', 'SN Pass Repair'), ('qty', 'Quantity Repair')], string='Repair Mode', readonly=True)
    reported_count = fields.Integer(string='Reported Count', readonly=True)
    closed_ok_count = fields.Integer(string='Repair OK Count', readonly=True)
    scrapped_count = fields.Integer(string='Repair Scrap Count', readonly=True)
    open_count = fields.Integer(string='Open Count', readonly=True)
    closure_rate = fields.Float(string='Closure Rate (%)', readonly=True)
    repair_qty_total = fields.Float(string='Repair Qty', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        if not _tables_exist(self.env.cr, 'sn_wsd_repair_order'):
            self.env.cr.execute(f"""
                CREATE OR REPLACE VIEW {self._table} AS (
                    SELECT
                        NULL::integer AS id,
                        NULL::date AS report_date,
                        NULL::integer AS company_id,
                        NULL::integer AS production_id,
                        NULL::integer AS workorder_id,
                        NULL::integer AS defect_code_id,
                        NULL::varchar AS repair_mode,
                        0::integer AS reported_count,
                        0::integer AS closed_ok_count,
                        0::integer AS scrapped_count,
                        0::integer AS open_count,
                        0.0::double precision AS closure_rate,
                        0.0::double precision AS repair_qty_total
                    WHERE FALSE
                )
            """)
            return
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(r.id) AS id,
                    DATE(r.reported_time) AS report_date,
                    r.company_id,
                    r.production_id,
                    r.workorder_id,
                    r.defect_code_id,
                    r.repair_mode,
                    COUNT(*) AS reported_count,
                    COUNT(*) FILTER (WHERE r.state = 'done' AND r.result = 'ok') AS closed_ok_count,
                    COUNT(*) FILTER (WHERE r.state = 'scrapped' OR r.result = 'scrap') AS scrapped_count,
                    COUNT(*) FILTER (WHERE r.state NOT IN ('done', 'scrapped', 'cancel')) AS open_count,
                    CASE
                        WHEN COUNT(*) = 0 THEN 0.0
                        ELSE ROUND(COUNT(*) FILTER (WHERE r.state IN ('done', 'scrapped'))::numeric / COUNT(*)::numeric * 100.0, 2)
                    END AS closure_rate,
                    SUM(r.repair_qty) AS repair_qty_total
                FROM sn_wsd_repair_order r
                GROUP BY DATE(r.reported_time), r.company_id, r.production_id, r.workorder_id, r.defect_code_id, r.repair_mode
            )
        """)


class SnWsdSerialTraceSummaryReport(models.Model):
    _name = 'sn.wsd.serial.trace.summary.report'
    _description = 'Serial Trace Summary Report'
    _auto = False
    _order = 'production_date desc, serial_id desc'

    serial_id = fields.Many2one('sn.wsd.internal.serial', string='Meter Serial', readonly=True)
    serial_no = fields.Char(string='Serial No', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    current_workorder_id = fields.Many2one('mrp.workorder', string='Current Workorder', readonly=True)
    final_result = fields.Selection(selection=lambda self: self.env['sn.wsd.internal.serial']._fields['final_result'].selection, string='Final Result', readonly=True)
    production_date = fields.Datetime(string='Production Date', readonly=True)
    verification_date = fields.Datetime(string='Verification Date', readonly=True)
    pack_date = fields.Datetime(string='Pack Date', readonly=True)
    travel_count = fields.Integer(string='Travel Count', readonly=True)
    test_result_count = fields.Integer(string='Test Result Count', readonly=True)
    quality_issue_count = fields.Integer(string='Quality Issue Count', readonly=True)
    repair_order_count = fields.Integer(string='Repair Order Count', readonly=True)
    latest_workcenter_code = fields.Char(string='Latest Work Center', readonly=True)
    latest_event_type = fields.Char(string='Latest Event', readonly=True)
    latest_event_time = fields.Datetime(string='Latest Event Time', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        repair_order_count_sql = """
                    COALESCE((
                        SELECT COUNT(*) FROM sn_wsd_repair_order r
                        WHERE r.serial_id = s.id
                    ), 0) AS repair_order_count,
        """ if table_exists(self.env.cr, 'sn_wsd_repair_order') else """
                    0::integer AS repair_order_count,
        """
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH latest_travel AS (
                    SELECT DISTINCT ON (t.internal_serial_id)
                        t.internal_serial_id,
                        t.workcenter_code,
                        t.event_type,
                        t.event_time
                    FROM sn_wsd_mes_sn_travel t
                    ORDER BY t.internal_serial_id, t.event_time DESC, t.id DESC
                )
                SELECT
                    s.id AS id,
                    s.id AS serial_id,
                    s.serial_no,
                    s.company_id,
                    s.production_id,
                    s.product_id,
                    s.current_workorder_id,
                    s.final_result,
                    s.production_date,
                    s.verification_date,
                    s.pack_date,
                    COALESCE((
                        SELECT COUNT(*) FROM sn_wsd_mes_sn_travel t
                        WHERE t.internal_serial_id = s.id
                    ), 0) AS travel_count,
                    COALESCE((
                        SELECT COUNT(*) FROM sn_wsd_mes_test_result t
                        WHERE t.internal_serial_id = s.id
                    ), 0) AS test_result_count,
                    COALESCE((
                        SELECT COUNT(*) FROM sn_wsd_quality_issue q
                        WHERE q.internal_serial_id = s.id
                    ), 0) AS quality_issue_count,
{repair_order_count_sql}
                    lt.workcenter_code AS latest_workcenter_code,
                    lt.event_type AS latest_event_type,
                    lt.event_time AS latest_event_time
                FROM sn_wsd_internal_serial s
                LEFT JOIN latest_travel lt ON lt.internal_serial_id = s.id
            )
        """)


class SnWsdSerialTraceDetailReport(models.Model):
    _name = 'sn.wsd.serial.trace.detail.report'
    _description = 'Serial Trace Detail Report'
    _auto = False
    _order = 'event_time desc, event_source, id desc'

    event_time = fields.Datetime(string='Event Time', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    serial_id = fields.Many2one('sn.wsd.internal.serial', string='Meter Serial', readonly=True)
    serial_no = fields.Char(string='Serial No', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Workorder', readonly=True)
    mes_workcenter_id = fields.Many2one('mrp.workcenter', string='MES Work Center', readonly=True)
    workcenter_code = fields.Char(string='Work Center Code', readonly=True)
    equipment_id = fields.Many2one('maintenance.equipment', string='Equipment', readonly=True)
    event_source = fields.Char(string='Event Source', readonly=True)
    event_type = fields.Char(string='Event Type', readonly=True)
    result = fields.Char(string='Result', readonly=True)
    quantity = fields.Float(string='Quantity', readonly=True)
    reference_name = fields.Char(string='Reference', readonly=True)
    note = fields.Char(string='Note', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        scrap_union_sql = """
                    UNION ALL

                    SELECT
                        r.id AS src_id,
                        r.scrap_time AS event_time,
                        r.company_id,
                        r.serial_id,
                        r.serial_no,
                        r.production_id,
                        r.workorder_id,
                        wo.x_mes_workcenter_id AS mes_workcenter_id,
                        COALESCE(wo.x_meter_workcenter_code, '') AS workcenter_code,
                        NULL::integer AS equipment_id,
                        'scrap'::text AS event_source,
                        'scrap'::text AS event_type,
                        r.state::text AS result,
                        r.scrap_qty AS quantity,
                        r.name AS reference_name,
                        r.note
                    FROM sn_wsd_scrap_record r
                    LEFT JOIN mrp_workorder wo ON wo.id = r.workorder_id
        """ if table_exists(self.env.cr, 'sn_wsd_scrap_record') else ""
        repair_union_sql = """
                    UNION ALL

                    SELECT
                        r.id AS src_id,
                        r.reported_time AS event_time,
                        r.company_id,
                        r.serial_id,
                        r.serial_no,
                        r.production_id,
                        r.workorder_id,
                        wo.x_mes_workcenter_id AS mes_workcenter_id,
                        COALESCE(wo.x_meter_workcenter_code, '') AS workcenter_code,
                        NULL::integer AS equipment_id,
                        'repair'::text AS event_source,
                        r.repair_mode::text AS event_type,
                        r.state::text AS result,
                        r.repair_qty AS quantity,
                        r.name AS reference_name,
                        r.note
                    FROM sn_wsd_repair_order r
                    LEFT JOIN mrp_workorder wo ON wo.id = r.workorder_id
        """ if table_exists(self.env.cr, 'sn_wsd_repair_order') else ""
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    row_number() OVER (ORDER BY src.event_time DESC, src.event_source, src.src_id DESC) AS id,
                    src.event_time,
                    src.company_id,
                    src.serial_id,
                    src.serial_no,
                    src.production_id,
                    src.workorder_id,
                    src.mes_workcenter_id,
                    src.workcenter_code,
                    src.equipment_id,
                    src.event_source,
                    src.event_type,
                    src.result,
                    src.quantity,
                    src.reference_name,
                    src.note
                FROM (
                    SELECT
                        t.id AS src_id,
                        t.event_time,
                        t.company_id,
                        s.id AS serial_id,
                        s.serial_no,
                        t.production_id,
                        t.workorder_id,
                        t.workcenter_id AS mes_workcenter_id,
                        t.workcenter_code,
                        t.equipment_id,
                        'travel'::text AS event_source,
                        t.event_type::text AS event_type,
                        COALESCE(t.result::text, '') AS result,
                        1.0 AS quantity,
                        t.name AS reference_name,
                        t.note
                    FROM sn_wsd_mes_sn_travel t
                    LEFT JOIN sn_wsd_internal_serial s ON s.id = t.internal_serial_id

                    UNION ALL

                    SELECT
                        r.id AS src_id,
                        r.test_time AS event_time,
                        r.company_id,
                        s.id AS serial_id,
                        s.serial_no,
                        r.production_id,
                        r.workorder_id,
                        r.workcenter_id AS mes_workcenter_id,
                        r.workcenter_code,
                        r.equipment_id,
                        'test'::text AS event_source,
                        r.test_type::text AS event_type,
                        r.result::text AS result,
                        1.0 AS quantity,
                        r.name AS reference_name,
                        r.note
                    FROM sn_wsd_mes_test_result r
                    LEFT JOIN sn_wsd_internal_serial s ON s.id = r.internal_serial_id

{scrap_union_sql}
{repair_union_sql}

                    UNION ALL

                    SELECT
                        p.id AS src_id,
                        p.pack_time AS event_time,
                        p.company_id,
                        p.serial_id,
                        s.serial_no,
                        p.production_id,
                        p.pack_workorder_id AS workorder_id,
                        wo.x_mes_workcenter_id AS mes_workcenter_id,
                        COALESCE(wo.x_meter_workcenter_code, '') AS workcenter_code,
                        NULL::integer AS equipment_id,
                        'pack'::text AS event_source,
                        'packed'::text AS event_type,
                        p.scan_check_result::text AS result,
                        1.0 AS quantity,
                        p.name AS reference_name,
                        p.note
                    FROM sn_wsd_meter_pack_record p
                    LEFT JOIN sn_wsd_internal_serial s ON s.id = p.serial_id
                    LEFT JOIN mrp_workorder wo ON wo.id = p.pack_workorder_id

                    UNION ALL

                    SELECT
                        l.id AS src_id,
                        l.load_time AS event_time,
                        b.company_id,
                        l.serial_id,
                        s.serial_no,
                        b.production_id,
                        b.workorder_id,
                        wo.x_mes_workcenter_id AS mes_workcenter_id,
                        COALESCE(wo.x_meter_workcenter_code, '') AS workcenter_code,
                        b.equipment_id AS equipment_id,
                        'aging_load'::text AS event_source,
                        'load'::text AS event_type,
                        l.result::text AS result,
                        1.0 AS quantity,
                        b.name AS reference_name,
                        l.note
                    FROM sn_wsd_meter_aging_batch_line l
                    JOIN sn_wsd_meter_aging_batch b ON b.id = l.batch_id
                    LEFT JOIN sn_wsd_internal_serial s ON s.id = l.serial_id
                    LEFT JOIN mrp_workorder wo ON wo.id = b.workorder_id

                    UNION ALL

                    SELECT
                        l.id AS src_id,
                        l.unload_time AS event_time,
                        b.company_id,
                        l.serial_id,
                        s.serial_no,
                        b.production_id,
                        b.workorder_id,
                        wo.x_mes_workcenter_id AS mes_workcenter_id,
                        COALESCE(wo.x_meter_workcenter_code, '') AS workcenter_code,
                        b.equipment_id AS equipment_id,
                        'aging_unload'::text AS event_source,
                        'unload'::text AS event_type,
                        l.result::text AS result,
                        1.0 AS quantity,
                        b.name AS reference_name,
                        l.note
                    FROM sn_wsd_meter_aging_batch_line l
                    JOIN sn_wsd_meter_aging_batch b ON b.id = l.batch_id
                    LEFT JOIN sn_wsd_internal_serial s ON s.id = l.serial_id
                    LEFT JOIN mrp_workorder wo ON wo.id = b.workorder_id
                    WHERE l.unload_time IS NOT NULL
                ) src
                WHERE src.serial_id IS NOT NULL
            )
        """)


class SnWsdTestHistoryReport(models.Model):
    _name = 'sn.wsd.test.history.report'
    _description = 'Test History Report'
    _auto = False
    _order = 'test_time desc, id desc'

    test_time = fields.Datetime(string='Test Time', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    serial_id = fields.Many2one('sn.wsd.internal.serial', string='Meter Serial', readonly=True)
    serial_no = fields.Char(string='Serial No', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Workorder', readonly=True)
    mes_workcenter_id = fields.Many2one('mrp.workcenter', string='MES Work Center', readonly=True)
    workcenter_code = fields.Char(string='Work Center Code', readonly=True)
    equipment_id = fields.Many2one('maintenance.equipment', string='Equipment', readonly=True)
    test_type = fields.Selection(
        [('programming', 'Programming'), ('inspection', 'Inspection'), ('aging', 'Aging'), ('calibration', 'Calibration'), ('final_test', 'Final Test'), ('packaging', 'Packaging')],
        string='Test Type',
        readonly=True,
    )
    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail'), ('hold', 'Hold')], string='Result', readonly=True)
    cycle_time_sec = fields.Float(string='Cycle Time (sec)', readonly=True)
    operator_code = fields.Char(string='Operator', readonly=True)
    tester_channel = fields.Char(string='Tester Channel', readonly=True)
    basic_error = fields.Float(string='Basic Error', readonly=True)
    phase_error = fields.Float(string='Phase Error', readonly=True)
    aging_temp_c = fields.Float(string='Aging Temp C', readonly=True)
    travel_id = fields.Many2one('sn.wsd.mes.sn.travel', string='Travel', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    t.id AS id,
                    t.test_time,
                    t.company_id,
                    s.id AS serial_id,
                    s.serial_no,
                    t.product_id,
                    t.production_id,
                    t.workorder_id,
                    t.workcenter_id AS mes_workcenter_id,
                    t.workcenter_code,
                    t.equipment_id,
                    t.test_type,
                    t.result,
                    t.cycle_time_sec,
                    t.operator_code,
                    t.tester_channel,
                    t.basic_error,
                    t.phase_error,
                    t.aging_temp_c,
                    t.travel_id
                FROM sn_wsd_mes_test_result t
                LEFT JOIN sn_wsd_internal_serial s ON s.id = t.internal_serial_id
            )
        """)


class SnWsdStationEfficiencyReport(models.Model):
    _name = 'sn.wsd.station.efficiency.report'
    _description = 'Station Efficiency Report'
    _auto = False
    _order = 'report_date desc, mes_workcenter_id'

    report_date = fields.Date(string='Report Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    mes_workcenter_id = fields.Many2one('mrp.workcenter', string='MES Work Center', readonly=True)
    workcenter_code = fields.Char(string='Work Center Code', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Workorder', readonly=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Execution Work Center', readonly=True)
    output_qty = fields.Float(string='Cumulative Output Qty', readonly=True)
    pass_qty = fields.Float(string='Pass Qty', readonly=True)
    total_cycle_time_sec = fields.Float(string='Total Cycle Time (sec)', readonly=True)
    avg_cycle_time_sec = fields.Float(string='Avg Cycle Time (sec)', readonly=True)
    theoretical_cycle_time_min = fields.Float(string='Planned Cycle Time (min)', readonly=True)
    efficiency_rate = fields.Float(string='Efficiency Rate (%)', readonly=True)
    travel_event_count = fields.Integer(string='Travel Event Count', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(r.id) AS id,
                    DATE(r.event_time) AS report_date,
                    r.company_id,
                    wo.x_mes_workcenter_id AS mes_workcenter_id,
                    wo.x_meter_workcenter_code AS workcenter_code,
                    r.workorder_id,
                    r.workcenter_id,
                    SUM(r.qty_out) AS output_qty,
                    SUM(r.qty_ok) AS pass_qty,
                    COALESCE(SUM(t.cycle_time_sec), 0.0) AS total_cycle_time_sec,
                    COALESCE(AVG(t.cycle_time_sec), 0.0) AS avg_cycle_time_sec,
                    COALESCE(op.time_cycle_manual, 0.0) AS theoretical_cycle_time_min,
                    CASE
                        WHEN COALESCE(AVG(t.cycle_time_sec), 0.0) = 0 OR COALESCE(op.time_cycle_manual, 0.0) = 0 THEN 0.0
                        ELSE ROUND(((op.time_cycle_manual * 60.0) / NULLIF(AVG(t.cycle_time_sec), 0.0) * 100.0)::numeric, 2)
                    END AS efficiency_rate,
                    COALESCE(COUNT(tr.id), 0) AS travel_event_count
                FROM mrp_workorder_report r
                JOIN mrp_workorder wo ON wo.id = r.workorder_id
                LEFT JOIN mrp_routing_workcenter op ON op.id = wo.operation_id
                LEFT JOIN sn_wsd_mes_test_result t ON t.workorder_id = r.workorder_id AND DATE(t.test_time) = DATE(r.event_time)
                LEFT JOIN sn_wsd_mes_sn_travel tr ON tr.workorder_id = r.workorder_id AND DATE(tr.event_time) = DATE(r.event_time)
                WHERE r.state != 'cancelled'
                GROUP BY DATE(r.event_time), r.company_id, wo.x_mes_workcenter_id, wo.x_meter_workcenter_code, r.workorder_id, r.workcenter_id, op.time_cycle_manual
            )
        """)


class SnWsdMesDashboardService(models.AbstractModel):
    _name = 'sn.wsd.mes.dashboard.service'
    _description = 'MES Dashboard Service'

    @api.model
    def get_big_screen_data(self):
        progress_model = self.env['sn.wsd.production.progress.report']
        daily_model = self.env['sn.wsd.operation.daily.report']
        test_rate_model = self.env['sn.wsd.test.pass.rate.report']
        test_history_model = self.env['sn.wsd.test.history.report']
        aging_model = self.env['sn.wsd.aging.loss.report']
        repair_model = self.env['sn.wsd.repair.closure.report']
        trace_model = self.env['sn.wsd.serial.trace.detail.report']
        efficiency_model = self.env['sn.wsd.station.efficiency.report']

        progress_records = progress_model.search([], order='production_id desc', limit=8)
        daily_records = daily_model.search([], order='report_date desc, workcenter_code', limit=12)
        test_rate_records = test_rate_model.search([], order='report_date desc, test_type', limit=12)
        test_history_records = test_history_model.search([], order='test_time desc', limit=12)
        aging_records = aging_model.search([], order='start_date desc, batch_id desc', limit=8)
        repair_records = repair_model.search([], order='report_date desc, workorder_id', limit=8)
        trace_records = trace_model.search([], order='event_time desc', limit=12)
        efficiency_records = efficiency_model.search([], order='report_date desc, mes_workcenter_id', limit=12)
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        today = fields.Date.context_today(self)
        today_daily_records = daily_records.filtered(lambda rec: rec.report_date == today)
        today_efficiency_records = efficiency_records.filtered(lambda rec: rec.report_date == today)
        abnormal_station_rows = []
        congestion_rows = []

        for rec in today_daily_records:
            abnormal_qty = (rec.qty_ng or 0.0) + (rec.qty_scrap or 0.0)
            output_qty = rec.qty_out or 0.0
            abnormal_rate = round(abnormal_qty / output_qty * 100.0, 2) if output_qty else 0.0
            backlog_qty = max((rec.qty_in or 0.0) - (rec.qty_out or 0.0), 0.0)
            abnormal_station_rows.append({
                'station_code': rec.workcenter_code or '-',
                'qty_ng': rec.qty_ng,
                'qty_scrap': rec.qty_scrap,
                'abnormal_qty': abnormal_qty,
                'abnormal_rate': abnormal_rate,
                'qty_out': output_qty,
            })
            congestion_rows.append({
                'station_code': rec.workcenter_code or '-',
                'qty_in': rec.qty_in,
                'qty_out': rec.qty_out,
                'backlog_qty': backlog_qty,
                'pass_rate': rec.pass_rate,
            })

        efficiency_map = {
            rec.workcenter_code: rec
            for rec in today_efficiency_records
            if rec.workcenter_code
        }
        for row in congestion_rows:
            efficiency_rec = efficiency_map.get(row['station_code'])
            efficiency_rate = efficiency_rec.efficiency_rate if efficiency_rec else 0.0
            avg_cycle_time_sec = efficiency_rec.avg_cycle_time_sec if efficiency_rec else 0.0
            row['efficiency_rate'] = efficiency_rate
            row['avg_cycle_time_sec'] = avg_cycle_time_sec
            row['alert_level'] = (
                'danger' if row['backlog_qty'] >= 20 or efficiency_rate < 70.0
                else 'warning' if row['backlog_qty'] >= 5 or efficiency_rate < 85.0
                else 'normal'
            )

        abnormal_station_rows.sort(key=lambda item: (item['abnormal_qty'], item['abnormal_rate']), reverse=True)
        congestion_rows.sort(key=lambda item: (item['backlog_qty'], -item['efficiency_rate']), reverse=True)
        open_alert_count = len([row for row in congestion_rows if row['alert_level'] != 'normal'])

        return {
            'summary': {
                'production_count': progress_model.search_count([]),
                'open_progress_count': len(progress_records.filtered(lambda rec: rec.progress_rate < 100.0)),
                'today_output_total': sum(today_daily_records.mapped('qty_out')),
                'today_pass_total': sum(today_daily_records.mapped('qty_ok')),
                'today_test_count': len(test_history_records.filtered(lambda rec: rec.test_time and rec.test_time.date() == today)),
                'today_date': fields.Date.to_string(today),
                'refresh_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'station_alert_count': open_alert_count,
            },
            'production_progress': [
                {
                    'production_name': rec.production_name,
                    'product_qty': rec.product_qty,
                    'qty_output_total': rec.qty_output_total,
                    'qty_pass': rec.qty_pass,
                    'qty_fail': rec.qty_fail,
                    'qty_scrap': rec.qty_scrap,
                    'progress_rate': rec.progress_rate,
                    'pass_rate': rec.pass_rate,
                    'progress_status': (
                        'danger' if rec.progress_rate < 60.0
                        else 'warning' if rec.progress_rate < 90.0
                        else 'normal'
                    ),
                }
                for rec in progress_records
            ],
            'operation_daily': [
                {
                    'report_date': rec.report_date,
                    'station_code': rec.workcenter_code,
                    'operation_type': rec.operation_type,
                    'qty_in': rec.qty_in,
                    'qty_ok': rec.qty_ok,
                    'qty_ng': rec.qty_ng,
                    'qty_scrap': rec.qty_scrap,
                    'qty_out': rec.qty_out,
                    'pass_rate': rec.pass_rate,
                    'abnormal_qty': (rec.qty_ng or 0.0) + (rec.qty_scrap or 0.0),
                }
                for rec in daily_records
            ],
            'test_pass_rates': [
                {
                    'report_date': rec.report_date,
                    'station_code': rec.workcenter_code,
                    'test_type': rec.test_type,
                    'total_count': rec.total_count,
                    'pass_count': rec.pass_count,
                    'fail_count': rec.fail_count,
                    'pass_rate': rec.pass_rate,
                    'status': (
                        'danger' if rec.pass_rate < 85.0
                        else 'warning' if rec.pass_rate < 95.0
                        else 'normal'
                    ),
                }
                for rec in test_rate_records
            ],
            'aging_losses': [
                {
                    'start_date': rec.start_date,
                    'batch_name': rec.batch_name,
                    'load_qty': rec.load_qty,
                    'pass_qty': rec.pass_qty,
                    'loss_qty': rec.loss_qty,
                    'loss_rate': rec.loss_rate,
                    'status': (
                        'danger' if rec.loss_rate >= 10.0
                        else 'warning' if rec.loss_rate >= 3.0
                        else 'normal'
                    ),
                }
                for rec in aging_records
            ],
            'repair_closures': [
                {
                    'report_date': rec.report_date,
                    'repair_mode': rec.repair_mode,
                    'reported_count': rec.reported_count,
                    'closed_ok_count': rec.closed_ok_count,
                    'scrapped_count': rec.scrapped_count,
                    'open_count': rec.open_count,
                    'closure_rate': rec.closure_rate,
                    'status': (
                        'danger' if rec.open_count > 0 and rec.closure_rate < 70.0
                        else 'warning' if rec.open_count > 0
                        else 'normal'
                    ),
                }
                for rec in repair_records
            ],
            'station_efficiency': [
                {
                    'report_date': rec.report_date,
                    'station_code': rec.workcenter_code,
                    'output_qty': rec.output_qty,
                    'pass_qty': rec.pass_qty,
                    'avg_cycle_time_sec': rec.avg_cycle_time_sec,
                    'efficiency_rate': rec.efficiency_rate,
                    'status': (
                        'danger' if rec.efficiency_rate < 70.0
                        else 'warning' if rec.efficiency_rate < 85.0
                        else 'normal'
                    ),
                }
                for rec in efficiency_records
            ],
            'test_history': [
                {
                    'test_time': rec.test_time,
                    'serial_no': rec.serial_no,
                    'test_type': rec.test_type,
                    'result': rec.result,
                    'station_code': rec.workcenter_code,
                    'operator_code': rec.operator_code,
                    'cycle_time_sec': rec.cycle_time_sec,
                    'status': 'danger' if rec.result == 'fail' else 'warning' if rec.result == 'hold' else 'normal',
                }
                for rec in test_history_records
            ],
            'serial_trace': [
                {
                    'event_time': rec.event_time,
                    'serial_no': rec.serial_no,
                    'event_source': rec.event_source,
                    'event_type': rec.event_type,
                    'station_code': rec.workcenter_code,
                    'result': rec.result,
                    'quantity': rec.quantity,
                    'reference_name': rec.reference_name,
                    'status': 'danger' if rec.result in ('fail', 'scrapped', 'scrap') else 'warning' if rec.result in ('hold', 'reported', 'repairing') else 'normal',
                }
                for rec in trace_records
            ],
            'top_abnormal_stations': abnormal_station_rows[:6],
            'station_congestion': congestion_rows[:6],
        }

    @api.model
    def action_open_big_screen(self):
        client_action = self.env.ref(
            'sn_wsd_report.action_sn_wsd_mes_big_screen_client',
            raise_if_not_found=False,
        )
        if client_action:
            action = client_action.read()[0]
            action['name'] = _('MES Big Screen')
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'sn_wsd_mes_big_screen_action',
            'name': _('MES Big Screen'),
            'target': 'fullscreen',
            'path': 'sn-wsd-mes-big-screen-display',
            'context': {},
        }

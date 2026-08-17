from odoo import api, fields, models
from odoo.tools import drop_view_if_exists


class SnWsdWipSnapshot(models.Model):
    _name = 'sn.wsd.wip.snapshot'
    _description = 'Manufacturing WIP Snapshot'
    _order = 'production_id, step_sequence, workorder_id'
    _check_company_auto = True

    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        index=True,
        ondelete='cascade',
        check_company=True,
    )
    manufacturing_batch_id = fields.Many2one(
        'sn.wsd.manufacturing.batch', string='Manufacturing Batch',
        related='production_id.x_manufacturing_batch_id', store=True, readonly=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='production_id.company_id',
        store=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='production_id.product_id',
        store=True,
        readonly=True,
    )
    route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Process Route',
        related='production_id.x_route_id',
        store=True,
        readonly=True,
    )
    workorder_id = fields.Many2one(
        'mrp.workorder',
        string='Work Order',
        required=True,
        index=True,
        ondelete='cascade',
        check_company=True,
    )
    route_step_id = fields.Many2one(
        'sn.wsd.process.route.operation',
        string='Process Step',
        check_company=True,
        index=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        related='workorder_id.workcenter_id',
        store=True,
        readonly=True,
    )
    step_sequence = fields.Integer(string='Step Sequence', index=True)
    step_code = fields.Char(string='Step Code')
    step_name = fields.Char(string='Step Name')
    data_source = fields.Selection(
        [('sn', 'SN Travel'), ('qty', 'Quantity Reporting')],
        string='Data Source',
        required=True,
    )
    input_qty = fields.Float(string='Input Qty')
    start_qty = fields.Float(string='Start Qty')
    pass_qty = fields.Float(string='Passed Qty')
    fail_qty = fields.Float(string='Fail Qty')
    scrap_qty = fields.Float(string='Scrap Qty')
    pending_qty = fields.Float(string='Pending Qty')
    wip_qty = fields.Float(string='WIP Qty')
    snapshot_time = fields.Datetime(string='Snapshot Time', required=True, default=fields.Datetime.now, index=True)

    _production_workorder_uniq = models.Constraint(
        'unique(production_id, workorder_id)',
        'Each work order can only have one active WIP snapshot per manufacturing order.',
    )


class SnWsdWipReport(models.Model):
    _name = 'sn.wsd.wip.report'
    _description = 'Manufacturing WIP Report'
    _auto = False
    _order = 'production_id, step_sequence, workorder_id'

    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    manufacturing_batch_id = fields.Many2one('sn.wsd.manufacturing.batch', string='Manufacturing Batch', readonly=True)
    production_name = fields.Char(string='Manufacturing Reference', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', readonly=True)
    workorder_name = fields.Char(string='Work Order Reference', readonly=True)
    workcenter_id = fields.Many2one('mrp.workcenter', string='Work Center', readonly=True)
    route_id = fields.Many2one('sn.wsd.process.route', string='Process Route', readonly=True)
    route_step_id = fields.Many2one('sn.wsd.process.route.operation', string='Process Step', readonly=True)
    step_sequence = fields.Integer(string='Step Sequence', readonly=True)
    step_code = fields.Char(string='Step Code', readonly=True)
    step_name = fields.Char(string='Step Name', readonly=True)
    data_source = fields.Selection(
        [('sn', 'SN Travel'), ('qty', 'Quantity Reporting')],
        string='Data Source',
        readonly=True,
    )
    input_qty = fields.Float(string='Input Qty', readonly=True)
    start_qty = fields.Float(string='Start Qty', readonly=True)
    pass_qty = fields.Float(string='Passed Qty', readonly=True)
    fail_qty = fields.Float(string='Fail Qty', readonly=True)
    scrap_qty = fields.Float(string='Scrap Qty', readonly=True)
    pending_qty = fields.Float(string='Pending Qty', readonly=True)
    wip_qty = fields.Float(string='WIP Qty', readonly=True)
    snapshot_time = fields.Datetime(string='Snapshot Time', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    snapshot.id,
                    snapshot.production_id,
                    snapshot.manufacturing_batch_id,
                    production.name AS production_name,
                    snapshot.company_id,
                    snapshot.product_id,
                    snapshot.workorder_id,
                    workorder.name AS workorder_name,
                    snapshot.workcenter_id,
                    snapshot.route_id,
                    snapshot.route_step_id,
                    snapshot.step_sequence,
                    snapshot.step_code,
                    snapshot.step_name,
                    snapshot.data_source,
                    snapshot.input_qty,
                    snapshot.start_qty,
                    snapshot.pass_qty,
                    snapshot.fail_qty,
                    snapshot.scrap_qty,
                    snapshot.pending_qty,
                    snapshot.wip_qty,
                    snapshot.snapshot_time
                FROM sn_wsd_wip_snapshot snapshot
                JOIN mrp_production production ON production.id = snapshot.production_id
                JOIN mrp_workorder workorder ON workorder.id = snapshot.workorder_id
            )
        """)


class SnWsdWipBatchReport(models.Model):
    _name = 'sn.wsd.wip.batch.report'
    _description = 'Manufacturing Batch WIP Report'
    _auto = False
    _order = 'manufacturing_batch_id, step_sequence, route_step_id'

    manufacturing_batch_id = fields.Many2one('sn.wsd.manufacturing.batch', string='Manufacturing Batch', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    route_id = fields.Many2one('sn.wsd.process.route', string='Process Route', readonly=True)
    route_step_id = fields.Many2one('sn.wsd.process.route.operation', string='Process Step', readonly=True)
    step_sequence = fields.Integer(string='Step Sequence', readonly=True)
    step_code = fields.Char(string='Step Code', readonly=True)
    step_name = fields.Char(string='Step Name', readonly=True)
    workorder_count = fields.Integer(string='Work Order Count', readonly=True)
    production_count = fields.Integer(string='Manufacturing Order Count', readonly=True)
    input_qty = fields.Float(string='Input Qty', readonly=True)
    start_qty = fields.Float(string='Start Qty', readonly=True)
    pass_qty = fields.Float(string='Passed Qty', readonly=True)
    fail_qty = fields.Float(string='Fail Qty', readonly=True)
    scrap_qty = fields.Float(string='Scrap Qty', readonly=True)
    pending_qty = fields.Float(string='Pending Qty', readonly=True)
    wip_qty = fields.Float(string='WIP Qty', readonly=True)
    snapshot_time = fields.Datetime(string='Snapshot Time', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(snapshot.id) AS id,
                    snapshot.manufacturing_batch_id,
                    MIN(snapshot.company_id) AS company_id,
                    MIN(snapshot.product_id) AS product_id,
                    MIN(snapshot.route_id) AS route_id,
                    snapshot.route_step_id,
                    MIN(snapshot.step_sequence) AS step_sequence,
                    MIN(snapshot.step_code) AS step_code,
                    MIN(snapshot.step_name) AS step_name,
                    COUNT(DISTINCT snapshot.workorder_id) AS workorder_count,
                    COUNT(DISTINCT snapshot.production_id) AS production_count,
                    SUM(snapshot.input_qty) AS input_qty,
                    SUM(snapshot.start_qty) AS start_qty,
                    SUM(snapshot.pass_qty) AS pass_qty,
                    SUM(snapshot.fail_qty) AS fail_qty,
                    SUM(snapshot.scrap_qty) AS scrap_qty,
                    SUM(snapshot.pending_qty) AS pending_qty,
                    SUM(snapshot.wip_qty) AS wip_qty,
                    MAX(snapshot.snapshot_time) AS snapshot_time
                FROM sn_wsd_wip_snapshot snapshot
                WHERE snapshot.manufacturing_batch_id IS NOT NULL
                GROUP BY snapshot.manufacturing_batch_id, snapshot.route_step_id
            )
        """)


class SnWsdWipProductionOverview(models.Model):
    _name = 'sn.wsd.wip.production.overview'
    _description = 'Manufacturing WIP Production Overview'
    _auto = False
    _order = 'production_name, production_id'

    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    manufacturing_batch_id = fields.Many2one('sn.wsd.manufacturing.batch', string='Manufacturing Batch', readonly=True)
    production_name = fields.Char(string='Manufacturing Reference', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    route_id = fields.Many2one('sn.wsd.process.route', string='Process Route', readonly=True)
    step_count = fields.Integer(string='Step Count', readonly=True)
    total_input_qty = fields.Float(string='Input Qty', readonly=True)
    total_start_qty = fields.Float(string='Started Qty', readonly=True)
    total_pass_qty = fields.Float(string='Passed Qty', readonly=True)
    total_fail_qty = fields.Float(string='Fail Qty', readonly=True)
    total_scrap_qty = fields.Float(string='Scrap Qty', readonly=True)
    total_pending_qty = fields.Float(string='Pending Qty', readonly=True)
    total_wip_qty = fields.Float(string='Current WIP Qty', readonly=True)
    max_step_wip_qty = fields.Float(string='Max Step WIP Qty', readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(snapshot.id) AS id,
                    snapshot.production_id,
                    MIN(snapshot.manufacturing_batch_id) AS manufacturing_batch_id,
                    MIN(production.name) AS production_name,
                    MIN(snapshot.company_id) AS company_id,
                    MIN(snapshot.product_id) AS product_id,
                    MIN(snapshot.route_id) AS route_id,
                    COUNT(snapshot.id) AS step_count,
                    MAX(snapshot.input_qty) AS total_input_qty,
                    SUM(snapshot.start_qty) AS total_start_qty,
                    SUM(snapshot.pass_qty) AS total_pass_qty,
                    SUM(snapshot.fail_qty) AS total_fail_qty,
                    SUM(snapshot.scrap_qty) AS total_scrap_qty,
                    SUM(snapshot.pending_qty) AS total_pending_qty,
                    SUM(snapshot.wip_qty) AS total_wip_qty,
                    MAX(snapshot.wip_qty) AS max_step_wip_qty
                FROM sn_wsd_wip_snapshot snapshot
                JOIN mrp_production production ON production.id = snapshot.production_id
                GROUP BY snapshot.production_id
            )
        """)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    x_wip_snapshot_ids = fields.One2many(
        'sn.wsd.wip.snapshot',
        'production_id',
        string='WIP Snapshots',
        readonly=True,
    )
    x_wip_report_line_ids = fields.One2many(
        'sn.wsd.wip.report',
        'production_id',
        string='WIP Report Lines',
        readonly=True,
    )
    x_wip_report_line_count = fields.Integer(
        string='WIP Step Count',
        compute='_compute_x_wip_report_summary',
    )
    x_wip_current_total = fields.Float(
        string='Current WIP Total',
        compute='_compute_x_wip_report_summary',
    )
    x_wip_overview_id = fields.Many2one(
        'sn.wsd.wip.production.overview',
        string='WIP Overview',
        compute='_compute_x_wip_report_summary',
    )

    def _compute_x_wip_report_summary(self):
        report_model = self.env['sn.wsd.wip.report']
        overview_model = self.env['sn.wsd.wip.production.overview']
        for production in self:
            lines = report_model.search([('production_id', '=', production.id)])
            production.x_wip_report_line_count = len(lines)
            production.x_wip_current_total = sum(lines.mapped('wip_qty'))
            production.x_wip_overview_id = overview_model.search([('production_id', '=', production.id)], limit=1)

    def _build_wip_snapshot_line_values(self, workorders):
        self.ensure_one()
        travel_model = self.env['sn.wsd.mes.sn.travel']
        issue_model = self.env['sn.wsd.quality.issue']
        values_list = []
        previous_pass_qty = 0.0
        ordered_workorders = workorders.sorted(lambda workorder: (workorder.x_route_operation_id.sequence or workorder.sequence, workorder.sequence, workorder.id))
        for index, workorder in enumerate(ordered_workorders):
            step = workorder.x_route_operation_id
            travel_domain = [('workorder_id', '=', workorder.id)]
            travel_count = travel_model.search_count(travel_domain)
            if travel_count:
                data_source = 'sn'
                start_qty = travel_model.search_count(travel_domain + [('event_type', '=', 'start')])
                pass_qty = travel_model.search_count(travel_domain + [('event_type', 'in', ['complete', 'pass']), ('result', '!=', 'fail')])
                fail_qty = travel_model.search_count(travel_domain + ['|', ('event_type', '=', 'fail'), ('result', '=', 'fail')])
                scrap_qty = issue_model.search_count([
                    ('workorder_id', '=', workorder.id),
                    '|',
                    ('disposition', '=', 'scrap'),
                    ('state', '=', 'scrapped'),
                ])
            else:
                data_source = 'qty'
                pass_qty = max(workorder.x_wip_qty_pass_snapshot, workorder.x_meter_qty_pass)
                fail_qty = max(workorder.x_wip_qty_fail_snapshot, workorder.x_meter_qty_fail)
                scrap_qty = max(workorder.x_wip_qty_scrap_snapshot, workorder.x_meter_qty_scrap)
                start_qty = max(
                    workorder.x_wip_qty_start_snapshot,
                    workorder.x_meter_qty_input,
                    workorder.qty_producing,
                    pass_qty + fail_qty + scrap_qty,
                )
            input_qty = self.product_qty if index == 0 else previous_pass_qty
            pending_qty = max(input_qty - start_qty, 0.0)
            wip_qty = max(input_qty - pass_qty, 0.0)
            values_list.append({
                'production_id': self.id,
                'workorder_id': workorder.id,
                'route_step_id': step.id if step else False,
                'step_sequence': step.sequence if step else workorder.sequence,
                'step_code': step.x_step_code if step else (workorder.operation_id.name or workorder.name),
                'step_name': step.name if step else (workorder.operation_id.name or workorder.name),
                'data_source': data_source,
                'input_qty': input_qty,
                'start_qty': start_qty,
                'pass_qty': pass_qty,
                'fail_qty': fail_qty,
                'scrap_qty': scrap_qty,
                'pending_qty': pending_qty,
                'wip_qty': wip_qty,
                'snapshot_time': fields.Datetime.now(),
            })
            previous_pass_qty = pass_qty
        return values_list

    def action_refresh_wip_snapshot(self):
        snapshot_model = self.env['sn.wsd.wip.snapshot'].sudo()
        for production in self:
            workorders = production.workorder_ids.sorted(lambda workorder: (workorder.x_route_operation_id.sequence or workorder.sequence, workorder.sequence, workorder.id))
            snapshot_model.search([('production_id', '=', production.id)]).unlink()
            values_list = production._build_wip_snapshot_line_values(workorders)
            if values_list:
                snapshot_model.create(values_list)
        return True

    def action_open_wip_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'WIP Report',
            'res_model': 'sn.wsd.wip.report',
            'view_mode': 'graph,list,pivot',
            'domain': [('production_id', '=', self.id)],
            'context': {
                'search_default_group_by_step': 1,
                'default_production_id': self.id,
            },
        }

    def action_open_wip_overview(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'WIP Overview',
            'res_model': 'sn.wsd.wip.production.overview',
            'view_mode': 'form',
            'res_id': self.x_wip_overview_id.id,
        }


class SnManufacturingBatch(models.Model):
    _inherit = 'sn.wsd.manufacturing.batch'

    x_wip_report_line_count = fields.Integer(string='WIP Step Count', compute='_compute_x_wip_summary')
    x_wip_current_total = fields.Float(string='Current WIP Total', compute='_compute_x_wip_summary')

    def _compute_x_wip_summary(self):
        report_model = self.env['sn.wsd.wip.batch.report']
        for batch in self:
            lines = report_model.search([('manufacturing_batch_id', '=', batch.id)])
            batch.x_wip_report_line_count = len(lines)
            batch.x_wip_current_total = sum(lines.mapped('wip_qty'))

    def action_refresh_wip_snapshot(self):
        self.mapped('production_ids').action_refresh_wip_snapshot()
        return True

    def action_open_wip_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Batch WIP Report',
            'res_model': 'sn.wsd.wip.batch.report',
            'view_mode': 'graph,list,pivot',
            'domain': [('manufacturing_batch_id', '=', self.id)],
            'context': {'search_default_group_by_step': 1},
        }

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    x_wip_qty_start_snapshot = fields.Float(string='WIP Start Qty Snapshot', copy=False)
    x_wip_qty_pass_snapshot = fields.Float(string='WIP Pass Qty Snapshot', copy=False)
    x_wip_qty_fail_snapshot = fields.Float(string='WIP Fail Qty Snapshot', copy=False)
    x_wip_qty_scrap_snapshot = fields.Float(string='WIP Scrap Qty Snapshot', copy=False)
    x_wip_qty_pending_snapshot = fields.Float(string='WIP Pending Qty Snapshot', copy=False)
    x_wip_data_source = fields.Selection(
        [('sn', 'SN Travel'), ('qty', 'Quantity Reporting')],
        string='WIP Data Source',
        copy=False,
    )
    x_wip_snapshot_time = fields.Datetime(string='WIP Snapshot Time', copy=False)

    def _get_wip_qty_snapshot_values(self):
        self.ensure_one()
        travel_model = self.env['sn.wsd.mes.sn.travel']
        issue_model = self.env['sn.wsd.quality.issue']
        travel_domain = [('workorder_id', '=', self.id)]
        travel_count = travel_model.search_count(travel_domain)
        if travel_count:
            data_source = 'sn'
            start_qty = travel_model.search_count(travel_domain + [('event_type', '=', 'start')])
            pass_qty = travel_model.search_count(travel_domain + [('event_type', 'in', ['complete', 'pass']), ('result', '!=', 'fail')])
            fail_qty = travel_model.search_count(travel_domain + ['|', ('event_type', '=', 'fail'), ('result', '=', 'fail')])
            scrap_qty = issue_model.search_count([
                ('workorder_id', '=', self.id),
                '|',
                ('disposition', '=', 'scrap'),
                ('state', '=', 'scrapped'),
            ])
            input_qty = max(self.x_meter_qty_input, start_qty, pass_qty + fail_qty + scrap_qty)
        else:
            data_source = 'qty'
            pass_qty = self.x_meter_qty_pass
            fail_qty = self.x_meter_qty_fail
            scrap_qty = self.x_meter_qty_scrap
            start_qty = max(
                self.x_meter_qty_input,
                self.qty_producing,
                pass_qty + fail_qty + scrap_qty,
            )
            input_qty = start_qty
        return {
            'x_wip_qty_start_snapshot': start_qty,
            'x_wip_qty_pass_snapshot': pass_qty,
            'x_wip_qty_fail_snapshot': fail_qty,
            'x_wip_qty_scrap_snapshot': scrap_qty,
            'x_wip_qty_pending_snapshot': max(input_qty - start_qty, 0.0),
            'x_wip_data_source': data_source,
            'x_wip_snapshot_time': fields.Datetime.now(),
        }

    def action_refresh_wip_qty_snapshot(self):
        productions = self.env['mrp.production']
        for workorder in self:
            workorder.write(workorder._get_wip_qty_snapshot_values())
            productions |= workorder.production_id
        if productions:
            productions.action_refresh_wip_snapshot()
        return True

    def button_finish(self):
        result = super().button_finish()
        self.action_refresh_wip_qty_snapshot()
        return result

    def action_sync_meter_qty(self):
        result = super().action_sync_meter_qty()
        self.action_refresh_wip_qty_snapshot()
        return result

    def action_meter_scan_complete(self, *args, **kwargs):
        result = super().action_meter_scan_complete(*args, **kwargs)
        self.action_refresh_wip_qty_snapshot()
        return result


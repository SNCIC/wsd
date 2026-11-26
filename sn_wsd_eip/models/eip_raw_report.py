"""Raw-material inspection reports (the GET file-collection interface).

One record = one report file attached to one raw-material inspection
batch. The gateway polls /api/eip/collect/M-REPORT (or C-REPORT) and
receives the fileArray of pending reports: procedure code, batches,
testFileType and a downloadable file URL. Claimed reports flip to
delivered -- fire-and-forget, same as every other interface.

The file serial number is a UUID generated per report. The work order
is picked from the work-order register (dropdown); its order and work
order numbers are copied onto the report -- the served payload keeps
that copy, whatever the register says afterwards.
"""
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EipRawReport(models.Model):
    _name = 'sn.wsd.eip.raw.report'
    _description = 'EIP Raw Material Report'
    _order = 'id'
    _rec_name = 'test_code'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    production_order_no = fields.Char(
        string='Production Order No.', required=True)
    production_work_no = fields.Char(string='Production Work No.')
    work_order_id = fields.Many2one(
        'sn.wsd.eip.work.order', string='Production Work Order',
        ondelete='set null', index=True, check_company=True,
        help='Picks the work order from the register; its production '
             'order and work order numbers are copied onto the report.')
    procedure_code = fields.Selection(
        selection=[('1012', '压敏电阻'), ('1013', '光电耦合器'),
                   ('1014', '晶体谐振器'), ('1015', '瞬变二极管'),
                   ('1016', '时钟电池'), ('1017', '液晶'),
                   ('1018', '电流互感器'),
                   ('2011', '压敏电阻'), ('2012', '光电耦合器'),
                   ('2013', '晶体谐振器'), ('2014', '瞬变二极管')],
        string='Procedure Code', required=True, index=True,
        help='The raw-material inspection procedure the report belongs '
             'to (platform-issued names).')
    test_code = fields.Char(
        string='Report Code', required=True, index=True, copy=False,
        default=lambda self: str(uuid.uuid4()),
        help='File serial number: a UUID generated for each report.')
    test_file_type = fields.Selection(
        selection=[('1', 'Incoming Check Report'),
                   ('2', 'Manufacturer Report')],
        string='Report Type', required=True, default='1')
    material_check_batch = fields.Char(
        string='Material Check Batch', required=True)
    material_batch = fields.Char(string='Material Batch')
    attachment_ids = fields.Many2many(
        'ir.attachment', string='Report Files',
        help='The report files themselves (PDF etc); served to the '
             'gateway as downloadable URLs.')
    family = fields.Selection(
        selection=[('meter', 'Electricity Meter'),
                   ('collector', 'Collection Device')],
        string='Spec Family', compute='_compute_family', store=True,
        index=True)
    state = fields.Selection(
        selection=[('pending', 'Pending'), ('delivered', 'Delivered')],
        string='State', required=True, default='pending', index=True)
    delivered_time = fields.Datetime(string='Delivered Time', readonly=True)

    @api.depends('procedure_code')
    def _compute_family(self):
        for report in self:
            report.family = ('meter'
                             if (report.procedure_code or '1').startswith('1')
                             else 'collector')

    # the only columns the delivery stamp itself may write on an
    # already-delivered report -- everything else is frozen forever
    DELIVERY_WRITE_KEYS = frozenset({'state', 'delivered_time'})

    def write(self, vals):
        if (any(record.state == 'delivered' for record in self)
                and any(key not in self.DELIVERY_WRITE_KEYS
                        for key in vals)):
            raise UserError(_(
                'Delivered rows are frozen: the gateway already took '
                'them, nothing can be edited afterwards.'))
        return super().write(vals)

    @api.onchange('work_order_id', 'procedure_code')
    def _onchange_work_order_id(self):
        """Picking the work order copies its numbers and its material
        batch; the inspection batch is the latest raw-material inspection
        of that work order under the chosen procedure."""
        work_order = self.work_order_id
        if not work_order:
            return
        self.production_order_no = work_order.ipo_no
        self.production_work_no = work_order.wo_no
        if work_order.materials_batch:
            self.material_batch = work_order.materials_batch
        if self.procedure_code:
            inspection = self.env['sn.wsd.eip.raw.record'].search(
                [('work_order_no', '=', work_order.wo_no),
                 ('info_type_code', '=', self.procedure_code)],
                order='check_time desc, id desc', limit=1)
            if inspection:
                self.material_check_batch = inspection.material_check_batch

    @api.model
    def _eip_claim(self, family, amount):
        """Atomically take up to ``amount`` pending reports of one spec
        family, FIFO, delivering them inside the same statement."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE sn_wsd_eip_raw_report r "
            "SET state = 'delivered', "
            "    delivered_time = (now() AT TIME ZONE 'UTC') "
            "WHERE r.id IN ("
            "  SELECT id FROM sn_wsd_eip_raw_report"
            "  WHERE state = 'pending' AND family = %s"
            "  ORDER BY id LIMIT %s"
            "  FOR UPDATE SKIP LOCKED) "
            "RETURNING id",
            (family, amount))
        ids = sorted(row[0] for row in self.env.cr.fetchall())
        self.invalidate_model()
        return self.browse(ids)

    def _eip_report_payloads(self, base_url):
        """data[] records of the report interface: one per report, the
        fileArray carries every attached file as a public download URL
        (files are flipped public at claim time -- LAN delivery)."""
        payloads = []
        base = base_url.rstrip('/')
        for report in self:
            files = []
            for att in report.attachment_ids:
                if not att.public:
                    att.sudo().write({'public': True})
                files.append({
                    'type': '1',
                    'fileUrl': '%s/web/content/%s?download=True'
                               % (base, att.id),
                    'fileName': att.name or '',
                    'testFileType': int(report.test_file_type or 1),
                    'MATERIAL_CHECK_BATCH': report.material_check_batch or '',
                    'MATERIAL_BATCH': report.material_batch or '',
                })
            payloads.append({
                'productionOrderNo': report.production_order_no or '',
                'productionWorkNo': report.production_work_no or '',
                'procedureCode': report.procedure_code or '',
                'fileArray': files,
                'Test_Code': report.test_code or '',
            })
        return payloads

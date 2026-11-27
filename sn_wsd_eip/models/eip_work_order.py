from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError

from .eip_push import C, F, K, T


class EipWorkOrder(models.Model):
    """Work order pushed to the EIP platform (single-table interface):
    the shop-floor decomposition of a production order. Created from a
    production order or by hand."""
    _name = 'sn.wsd.eip.work.order'
    _description = 'EIP Work Order'
    _rec_name = 'wo_no'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'wo_no desc, id desc'
    _check_company_auto = True

    EIP_INTERFACE = 'work_order'
    EIP_NUMBER_FIELD = 'wo_no'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        F('ipoNo', 'ipo_no', add=True, update=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        C('supplierName', 'supplier_name', add=True, update=True),
        F('woNo', 'wo_no', add=True, update=True),
        F('categoryCode', 'category_id.code', add=True),
        F('subclassCode', 'subclass_id.code', add=True),
        F('materialsCode', 'materials_code', add=True),
        F('materialsDescription', 'materials_description'),
        F('materialsBatch', 'materials_batch'),
        F('amount', 'amount', add=True),
        F('unit', 'unit', add=True),
        F('planStartDate', 'plan_start_date', add=True),
        F('planFinishDate', 'plan_finish_date', add=True),
        F('actualStartDate', 'actual_start_date'),
        F('actualFinishDate', 'actual_finish_date'),
        F('woStatus', 'wo_status', add=True),
        F('entityCode', 'entity_code'),
        F('processRouteNo', 'process_route_no'),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
        F('modelSpec', 'model_spec'),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    production_order_id = fields.Many2one(
        'sn.wsd.eip.production.order', string='Production Order',
        ondelete='set null', check_company=True, index=True,
        help='Picks the production order; its number is copied into '
             'the payload key.')
    # the work order number is the MES order number: the collected
    # production data is keyed by it, and the platform joins the two
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='Main MES Order', ondelete='set null',
        check_company=True, index=True, copy=False,
        help='Picks the main MES order; its number becomes the work order '
             'number and its manufacturing order the production order '
             'number. The numbers are copies, the ledger stays usable '
             'without the MES order.')
    mes_order_ids = fields.Many2many(
        'sn.wsd.mes.order', string='Linked MES Orders',
        check_company=True, copy=False,
        help='Every MES order whose collected production data is reported '
             'under this work order, the main one included. One MES order '
             'can only be linked to one work order.')
    ipo_no = fields.Char(
        string='Production Order No.', index=True,
        help='Number of the production order this work order belongs '
             'to. Bring it out with the MES order picker, or type it; '
             'the pre-push required check refuses an empty number.')
    wo_no = fields.Char(
        string='Work Order No.', index=True, copy=False,
        help='Key the platform joins the collected production data by. '
             'Bring it out with the MES order picker (the MES order '
             'number), or type it; the pre-push required check refuses '
             'an empty number.')
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_category_id'))
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code', index=True,
        default=lambda self: self.env['sn.wsd.eip.config']._eip_default(
            'default_subclass_id'))
    materials_code = fields.Char(string='Material Code')
    materials_description = fields.Char(string='Material Description')
    materials_batch = fields.Char(string='Material Batch')
    amount = fields.Char(string='Quantity')
    unit = fields.Char(string='Unit of Measure')
    plan_start_date = fields.Date(string='Planned Start')
    plan_finish_date = fields.Date(string='Planned Finish')
    actual_start_date = fields.Date(string='Actual Start')
    actual_finish_date = fields.Date(string='Actual Finish')
    wo_status = fields.Selection(
        [('1', 'Created'), ('2', 'Incoming Inspection'),
         ('3', 'In Production'), ('4', 'Factory Test'),
         ('5', 'Packed and Stocked')],
        string='Status', default='1')
    entity_code = fields.Char(
        string='Entity ID',
        help='One entity ID, or a range like 0001-0100 kept continuous.')
    process_route_no = fields.Char(string='Process Route No.')
    model_spec = fields.Char(string='Model Specification')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')

    _wo_uniq = models.Constraint(
        'unique(company_id, wo_no)',
        'The work order number must be unique per company.',
    )

    # how many collection rows one rewrite statement may carry
    REWRITE_BATCH = 1000

    @api.onchange('mes_order_id')
    def _onchange_mes_order_id(self):
        """MES order picked: its number is the work order number, its
        manufacturing order the production order number. The main order
        joins the linked list by itself (the save-time check demands
        it)."""
        order = self.mes_order_id
        if order:
            self.wo_no = order.name
            self.ipo_no = order.production_id.name or self.ipo_no
            if order not in self.mes_order_ids:
                self.mes_order_ids = [Command.link(order.id)]

    @api.onchange('production_order_id')
    def _onchange_production_order_id(self):
        order = self.production_order_id
        if order:
            self.ipo_no = order.ipo_no
            self.category_id = order.category_id
            self.subclass_id = order.subclass_id
            self.materials_code = order.materials_code
            self.materials_description = (order.materials_desc
                or order.purchase_line_id.material_desc or '')
            self.amount = order.amount
            self.unit = order.unit

    # ------------------------------------------------------------------
    # linked MES orders (one work order covers the SMT / DIP / assembly
    # lines of one product: a single ledger, several MES orders)
    # ------------------------------------------------------------------
    @api.constrains('mes_order_id', 'mes_order_ids')
    def _check_mes_orders(self):
        for work in self:
            main = work.mes_order_id
            if main and main not in work.mes_order_ids:
                raise ValidationError(_(
                    'The main MES order %(order)s must also be one of the '
                    'linked MES orders.', order=main.name))
            linked = main | work.mes_order_ids
            if not linked:
                continue
            other = self.search([
                ('id', '!=', work.id),
                ('company_id', '=', work.company_id.id),
                '|', ('mes_order_id', 'in', linked.ids),
                ('mes_order_ids', 'in', linked.ids),
            ], limit=1)
            if other:
                clash = linked & (other.mes_order_id | other.mes_order_ids)
                raise ValidationError(_(
                    'MES order %(order)s is already linked to work order '
                    '%(work)s: one MES order can only belong to one work '
                    'order.', order=clash[:1].name, work=other.wo_no))

    @api.model
    def _eip_resolve_normalized(self, order):
        """Collected-data numbers of an MES order: ``(wo_no, ipo_no)`` of
        the work order it is linked to, ``False`` when no work order
        carries it (or the ledger has no number yet) -- the capture then
        keeps the MES order numbers."""
        if not order:
            return False
        work = self.search([
            ('company_id', '=', order.company_id.id),
            '|', ('mes_order_id', '=', order.id),
            ('mes_order_ids', 'in', order.id),
        ], limit=1)
        if not work or not work.wo_no:
            return False
        return work.wo_no, work.ipo_no

    # ------------------------------------------------------------------
    # write-back of the undelivered collection rows
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        works = super().create(vals_list)
        works._eip_rewrite_collected_numbers()
        return works

    def write(self, vals):
        relinks = bool({'mes_order_id', 'mes_order_ids'} & set(vals))
        previous = ({work.id: work.wo_no for work in self}
                    if relinks else {})
        result = super().write(vals)
        if relinks:
            self._eip_rewrite_collected_numbers(previous)
        return result

    def _eip_rewrite_collected_numbers(self, previous_wo_no=None):
        """Converge the undelivered collection rows of every linked MES
        order on the ledger numbers; delivered rows are frozen by their
        own write guard and stay untouched."""
        previous_wo_no = previous_wo_no or {}
        Pass = self.env['sn.wsd.eip.pass.record'].sudo()
        Pack = self.env['sn.wsd.eip.pack.record'].sudo()
        for work in self:
            if not work.wo_no:
                continue
            numbers = {'work_order_no': work.wo_no}
            if work.ipo_no:
                numbers['production_order_no'] = work.ipo_no
            orders = work.mes_order_id | work.mes_order_ids
            if orders:
                # station-pass rows carry the MES order they were born
                # from: an exact anchor
                rows = Pass.search([
                    ('company_id', '=', work.company_id.id),
                    ('mes_order_id', 'in', orders.ids),
                    ('state', '!=', 'delivered'),
                ])
                self._eip_rewrite_batches(rows, numbers)
            # packing-storage rows carry no MES order: converge the ones
            # still reporting one of this work order's MES order numbers
            # (and the number the ledger had before this write)
            reported = {order.name for order in orders}
            if previous_wo_no.get(work.id):
                reported.add(previous_wo_no[work.id])
            reported.discard(work.wo_no)
            if not reported:
                continue
            rows = Pack.search([
                ('company_id', '=', work.company_id.id),
                ('work_order_no', 'in', list(reported)),
                ('state', '!=', 'delivered'),
            ])
            self._eip_rewrite_batches(rows, numbers)

    def _eip_rewrite_batches(self, records, vals):
        """Batch the rewrite: one UPDATE per chunk instead of one huge
        IN list on the high-volume collection tables."""
        for start in range(0, len(records), self.REWRITE_BATCH):
            records[start:start + self.REWRITE_BATCH].write(vals)

    def _eip_document_ref(self):
        self.ensure_one()
        return self.wo_no

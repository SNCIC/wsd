from odoo import fields, models

from .eip_push import C, F, K, N, T

SUPPLY_LINE_SPEC = (
    F('poItemNo', 'po_item_no', add=True, update=True),
    F('receivedName', 'received_name', add=True),
    F('materialCode', 'material_code', add=True),
    F('materialDesc', 'material_desc', add=True),
    F('eipMaterialCode', 'eip_material_code'),
    F('eipMaterialDesc', 'eip_material_desc'),
    F('amount', 'amount', add=True),
    F('categoryCode', 'category_id.code', add=True),
    F('subclassCode', 'subclass_id.code', add=True),
    F('measUnit', 'meas_unit', add=True),
)


class EipSupplyNote(models.Model):
    """Supply note pushed to the EIP platform: the contract / supply
    note the supplier received when it was not circulating in ECP yet.
    On success the platform returns the line IDs it generated; they are
    written back on the lines (usable later as purchase line IDs)."""
    _name = 'sn.wsd.eip.supply.note'
    _description = 'EIP Supply Note'
    _inherit = 'sn.wsd.eip.push.mixin'
    _order = 'supply_no desc, id desc'
    _check_company_auto = True

    EIP_INTERFACE = 'supply_note'
    EIP_SEQUENCE = 'sn.wsd.eip.supply.note'
    EIP_NUMBER_FIELD = 'supply_no'
    EIP_FIELDS = (
        C('purchaserHqCode', 'purchaser_hq_code', add=True),
        C('supplierCode', 'supplier_code', add=True, update=True),
        F('conType', 'con_type', add=True),
        F('supplyNo', 'supply_no', add=True),
        F('conCode', 'con_code', add=True),
        F('sellerSignTime', 'seller_sign_time'),
        F('prjName', 'prj_name'),
        F('conName', 'con_name'),
        F('sellerConCode', 'seller_con_code'),
        F('matMaxCode', 'mat_max_code'),
        F('matMedCode', 'mat_med_code'),
        F('matMinCode', 'mat_min_code'),
        F('matMaxName', 'mat_max_name'),
        F('matMedName', 'mat_med_name'),
        F('matMinName', 'mat_min_name'),
        F('cargoName', 'cargo_name', add=True),
        F('purchaseName', 'purchase_name', add=True),
        F('purchaseCode', 'purchase_code'),
        K('dataSource', '0', add=True),
        T('dataSourceCreateTime', add=True, update=True),
        F('remark', 'remark'),
        F('ownerId', 'owner_code'),
        F('openId', 'open_code'),
        N('itemList', 'line_ids', SUPPLY_LINE_SPEC),
    )

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    con_type = fields.Selection(
        [('1', 'Standard Contract'), ('2', 'Framework Stock'),
         ('3', 'Purchase Supply Note')],
        string='Contract Type')
    supply_no = fields.Char(
        string='Supply Note No.', required=True, index=True,
        copy=False, default=lambda self: self._eip_new_number())
    con_code = fields.Char(string='Contract No.')
    seller_sign_time = fields.Date(string='Contract Signing Date')
    prj_name = fields.Char(string='Project Name')
    con_name = fields.Char(string='Contract Name')
    seller_con_code = fields.Char(string='Contract No. (Legal System)')
    mat_max_code = fields.Char(string='Material Class Code')
    mat_med_code = fields.Char(string='Material Family Code')
    mat_min_code = fields.Char(string='Material Type Code')
    mat_max_name = fields.Char(string='Material Class')
    mat_med_name = fields.Char(string='Material Family')
    mat_min_name = fields.Char(string='Material Type')
    cargo_name = fields.Char(
        string='Cargo Name',
        help='Name of the delivered goods used on the supply note.')
    purchase_name = fields.Char(string='Purchaser Name')
    purchase_code = fields.Char(string='Purchaser Code (Company)')
    remark = fields.Char(string='Remark')
    owner_code = fields.Char(string='Data Owner')
    open_code = fields.Char(string='Data Viewer')
    line_ids = fields.One2many(
        'sn.wsd.eip.supply.note.line', 'supply_note_id', string='Lines')
    # non-payload local field: the raw returned data, kept for review
    eip_result_data = fields.Text(
        string='Returned Line IDs', readonly=True, copy=False,
        help='Raw data returned by the platform on a successful push.')

    _supply_uniq = models.Constraint(
        'unique(company_id, supply_no)',
        'The supply note number must be unique per company.',
    )

    def _eip_document_ref(self):
        self.ensure_one()
        return self.supply_no

    def _eip_on_push_success(self, result):
        """Write back the line IDs the platform returned:
        ``0010:<id>&0011:<id>`` matched by line number."""
        data = result.get('data')
        if not isinstance(data, str) or ':' not in data:
            return
        lines = {line.po_item_no: line for line in self.line_ids}
        for segment in data.split('&'):
            number, _, item_id = segment.partition(':')
            line = lines.get(number.strip())
            if line and item_id.strip():
                line.write({'eip_item_id': item_id.strip()})
        # keep the raw string on the record (a local field: never queues)
        self.write({'eip_result_data': data})


class EipSupplyNoteLine(models.Model):
    """One line of a supply note; the platform answers with the line
    ID it generated, written back here."""
    _name = 'sn.wsd.eip.supply.note.line'
    _description = 'EIP Supply Note Line'
    _inherit = 'sn.wsd.eip.push.line.mixin'
    _order = 'po_item_no, id'
    _check_company_auto = True

    EIP_LINES = SUPPLY_LINE_SPEC
    EIP_PARENT_FIELD = 'supply_note_id'
    EIP_LINE_NO_FIELD = 'po_item_no'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    supply_note_id = fields.Many2one(
        'sn.wsd.eip.supply.note', string='Supply Note', required=True,
        index=True, ondelete='cascade', check_company=True)
    po_item_no = fields.Char(
        string='Line No.',
        help='0010, 0020, 0030... for the first, second, third line.')
    received_name = fields.Char(
        string='Receiver Name',
        help='Requiring unit / project unit / receiver.')
    material_code = fields.Char(string='Material Code')
    material_desc = fields.Char(string='Material Description')
    eip_material_code = fields.Char(string='Grid Material Code')
    eip_material_desc = fields.Char(string='Grid Material Description')
    amount = fields.Char(string='Quantity')
    category_id = fields.Many2one(
        'sn.wsd.eip.category', string='Category Code', index=True)
    subclass_id = fields.Many2one(
        'sn.wsd.eip.subclass', string='Subclass Code', index=True)
    meas_unit = fields.Char(string='Unit of Measure')
    # local field written back by the platform answer
    eip_item_id = fields.Char(
        string='Returned Line ID', readonly=True, copy=False, index=True,
        help='ID EIP generated for this line; usable as the line ID of '
             'later interfaces.')

import base64
import csv
import io
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


TRACK_TYPE_SELECTION = [
    ('single', 'Single Track'),
    ('dual', 'Dual Track'),
]

PRODUCT_SIDE_SELECTION = [
    ('top', 'T Side'),
    ('bottom', 'B Side'),
    ('single', 'Single Side'),
]

TABLE_TYPE_SELECTION = [
    ('smt', 'SMT Material Table'),
    ('feeder', 'Feeder Table'),
    ('other', 'Other'),
]

YN_SELECTION = [
    ('Y', 'Yes'),
    ('N', 'No'),
]


class SnSmtMaterialTable(models.Model):
    _name = 'sn.smt.material.table'
    _description = 'SMT Material Table'
    _order = 'model_code, product_side, model_ver, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    table_name = fields.Char(string='TABLE_NAME', required=True, tracking=True)
    table_type = fields.Selection(TABLE_TYPE_SELECTION, string='TABLE_TYPE', default='smt', required=True)
    model_code = fields.Char(string='MODEL_CODE', required=True, index=True, tracking=True)
    model_ver = fields.Char(string='MODEL_VER', index=True)
    product_side = fields.Selection(PRODUCT_SIDE_SELECTION, string='PRODUCT_SIDE', required=True, index=True, tracking=True)
    item_count = fields.Integer(string='ITEM_COUNT')
    track_type = fields.Selection(TRACK_TYPE_SELECTION, string='TRACK_TYPE', default='single', required=True)
    is_valid = fields.Selection(YN_SELECTION, string='IS_VALID', default='Y', required=True, tracking=True)
    note = fields.Text(string='Note')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    line_link_ids = fields.One2many(
        'sn.smt.material.table.line',
        'table_id',
        string='Production Lines',
    )
    detail_ids = fields.One2many(
        'sn.smt.material.table.detail',
        'mt_id',
        string='Details',
    )
    detail_count = fields.Integer(compute='_compute_detail_count', string='Detail Count')

    _sn_smt_table_name_unique = models.Constraint(
        'unique(company_id, table_name)',
        'The material table name must be unique per company.',
    )

    @api.depends('table_name', 'model_code', 'product_side', 'model_ver')
    def _compute_name(self):
        for record in self:
            record.name = record.table_name or ' / '.join(
                item for item in [record.model_code, record.product_side, record.model_ver] if item
            )

    @api.depends('detail_ids')
    def _compute_detail_count(self):
        for record in self:
            record.detail_count = len(record.detail_ids)

    @api.constrains('line_link_ids')
    def _check_has_line_link(self):
        for record in self:
            if not record.line_link_ids:
                continue
            if any(link.company_id != record.company_id for link in record.line_link_ids):
                raise ValidationError(_('The linked production line company must match the material table company.'))

    @api.model
    def _match_for_production(self, production):
        candidates = self.search([
            ('company_id', '=', production.company_id.id),
            ('model_code', '=', production.product_id.default_code),
            ('product_side', '=', production.x_smt_product_side),
            ('is_valid', '=', 'Y'),
            ('line_link_ids.production_line_id', '=', production.x_smt_production_line_id.id),
        ])
        if not candidates:
            return self.env['sn.smt.material.table']
        if production.x_smt_model_ver:
            exact = candidates.filtered(lambda table: table.model_ver == production.x_smt_model_ver)
            if exact:
                return exact[:1]
        blank_ver = candidates.filtered(lambda table: not table.model_ver)
        return (blank_ver or candidates)[:1]

    def _prepare_online_material_vals(self, production):
        self.ensure_one()
        values = []
        for detail in self.detail_ids.sorted(lambda line: (line.device_seq, line.table_no, line.loadpoint, line.id)):
            values.append({
                'mt_id': self.id,
                'production_id': production.id,
                'mo_number': production.name,
                'project_id': production.origin,
                'model_code': production.product_id.default_code,
                'area_sn': production.x_smt_production_line_id.code,
                'production_line_id': production.x_smt_production_line_id.id,
                'process_face': production.x_smt_product_side,
                'item_code': detail.item_code,
                'program_name': self.table_name,
                'device_seq': detail.device_seq,
                'table_no': detail.table_no,
                'loadpoint': detail.loadpoint,
                'chanel_sn': detail.chanel_sn,
                'point_qty': detail.point_qty,
                'point_location': detail.point_location,
                'feeder_spec': detail.feeder_spec,
                'track_type': detail.track_type,
                'is_tray': detail.is_tray,
                'is_skip': detail.is_skip,
                'is_load': 'N',
                'is_qc_test': 'N',
                'company_id': production.company_id.id,
            })
        return values


class SnSmtMaterialTableLine(models.Model):
    _name = 'sn.smt.material.table.line'
    _description = 'SMT Material Table Production Line Link'
    _order = 'production_line_id, id'
    _check_company_auto = True

    table_id = fields.Many2one(
        'sn.smt.material.table',
        string='Material Table',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    production_line_id = fields.Many2one(
        'sn.mrp.production.line',
        string='Production Line',
        required=True,
        ondelete='restrict',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='table_id.company_id',
        store=True,
        readonly=True,
    )
    line_code = fields.Char(related='production_line_id.code', store=True, readonly=True)

    _sn_smt_table_line_unique = models.Constraint(
        'unique(table_id, production_line_id)',
        'A production line can only be linked once to the same material table.',
    )


class SnSmtMaterialTableDetail(models.Model):
    _name = 'sn.smt.material.table.detail'
    _description = 'SMT Material Table Detail'
    _order = 'device_seq, table_no, loadpoint, id'
    _check_company_auto = True

    mt_id = fields.Many2one(
        'sn.smt.material.table',
        string='MT_ID',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    company_id = fields.Many2one(related='mt_id.company_id', store=True, readonly=True)
    item_code = fields.Char(string='ITEM_CODE', required=True, index=True)
    device_seq = fields.Integer(string='DEVICE_SEQ', required=True)
    table_no = fields.Char(string='TABLE_NO', required=True)
    loadpoint = fields.Char(string='LOADPOINT', required=True)
    chanel_sn = fields.Char(string='CHANEL_SN')
    point_qty = fields.Integer(string='POINT_QTY')
    feeder_spec = fields.Char(string='FEEDER_SPEC')
    is_tray = fields.Selection(YN_SELECTION, string='IS_TRAY', default='N', required=True)
    is_skip = fields.Selection(YN_SELECTION, string='IS_SKIP', default='N', required=True)
    track_type = fields.Selection(TRACK_TYPE_SELECTION, string='TRACK_TYPE', default='single', required=True)
    direction = fields.Char(string='DIRECTION')
    point_location = fields.Text(string='POINT_LOCATION')

    _sn_smt_table_detail_unique = models.Constraint(
        'unique(mt_id, device_seq, table_no, loadpoint, chanel_sn)',
        'The device sequence, table number, loadpoint, and channel must be unique per material table.',
    )


class SnSmtOnlineMaterial(models.Model):
    _name = 'sn.smt.online.material'
    _description = 'SMT Online Material'
    _order = 'production_id, device_seq, table_no, loadpoint, id'
    _check_company_auto = True

    mt_id = fields.Many2one('sn.smt.material.table', string='MT_ID', check_company=True)
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        required=True,
        ondelete='cascade',
        check_company=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='production_id.x_mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    mo_number = fields.Char(string='MO_NUMBER', required=True, index=True)
    project_id = fields.Char(string='PROJECT_ID')
    model_code = fields.Char(string='MODEL_CODE', required=True, index=True)
    area_sn = fields.Char(string='AREA_SN', required=True, index=True)
    production_line_id = fields.Many2one('sn.mrp.production.line', string='Production Line', check_company=True)
    process_face = fields.Selection(PRODUCT_SIDE_SELECTION, string='PROCESS_FACE', required=True)
    item_code = fields.Char(string='ITEM_CODE', required=True)
    program_name = fields.Char(string='PROGRAM_NAME')
    device_seq = fields.Integer(string='DEVICE_SEQ', required=True)
    table_no = fields.Char(string='TABLE_NO', required=True)
    loadpoint = fields.Char(string='LOADPOINT', required=True)
    chanel_sn = fields.Char(string='CHANEL_SN')
    point_qty = fields.Integer(string='POINT_QTY')
    point_location = fields.Text(string='POINT_LOCATION')
    feeder_spec = fields.Char(string='FEEDER_SPEC')
    track_type = fields.Selection(TRACK_TYPE_SELECTION, string='TRACK_TYPE', default='single', required=True)
    is_tray = fields.Selection(YN_SELECTION, string='IS_TRAY', default='N', required=True)
    is_skip = fields.Selection(YN_SELECTION, string='IS_SKIP', default='N', required=True)
    is_load = fields.Selection(YN_SELECTION, string='IS_LOAD', default='N', required=True)
    is_qc_test = fields.Selection(YN_SELECTION, string='IS_QC_TEST', default='N', required=True)
    offline_material_ids = fields.One2many(
        'sn.smt.offline.material',
        'online_material_id',
        string='Offline Preparation Records',
    )
    loaded_material_lot_id = fields.Many2one(
        'stock.lot',
        string='Loaded Material SN',
        copy=False,
        check_company=True,
    )
    loaded_product_id = fields.Many2one(
        'product.product',
        string='Loaded Material',
        compute='_compute_loaded_product_id',
        store=True,
        readonly=True,
        check_company=True,
    )
    loaded_feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='Loaded Feeder',
        copy=False,
        check_company=True,
    )
    feeder_line_ids = fields.One2many(
        'mrp.feeder.line',
        'online_material_id',
        string='Feeder Lines',
    )
    replace_count = fields.Integer(string='Replace Count', default=0)
    unloaded_at = fields.Datetime(string='Unloaded At', copy=False)
    unload_scope = fields.Char(string='Unload Scope', copy=False)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_smt_online_material_unique = models.Constraint(
        'unique(production_id, device_seq, table_no, loadpoint, chanel_sn)',
        'The online material position must be unique per manufacturing order.',
    )

    @api.depends('loaded_material_lot_id.product_id')
    def _compute_loaded_product_id(self):
        for record in self:
            record.loaded_product_id = record.loaded_material_lot_id.product_id


class SnSmtFeeder(models.Model):
    _name = 'sn.smt.feeder'
    _description = 'SMT Feeder'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Feeder SN', required=True, index=True)
    channel_sn = fields.Char(string='Channel')
    feeder_spec = fields.Char(string='Feeder Spec')
    status = fields.Selection(
        [
            ('1', 'Normal'),
            ('2', 'In Use'),
            ('9', 'Disabled'),
        ],
        string='Status',
        default='1',
        required=True,
    )
    maintenance_ok = fields.Boolean(string='Maintenance OK', default=True)
    usage_count = fields.Integer(string='Usage Count', default=0)
    bound_production_id = fields.Many2one(
        'mrp.production',
        string='Bound Manufacturing Order',
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_smt_feeder_name_unique = models.Constraint(
        'unique(company_id, name)',
        'The feeder SN must be unique per company.',
    )


class SnSmtOfflineMaterial(models.Model):
    _name = 'sn.smt.offline.material'
    _description = 'SMT Offline Preparation Record'
    _order = 'production_id, device_seq, table_no, loadpoint, id'
    _check_company_auto = True

    online_material_id = fields.Many2one(
        'sn.smt.online.material',
        string='Online Material',
        required=True,
        ondelete='restrict',
        check_company=True,
    )
    production_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        related='online_material_id.production_id',
        store=True,
        readonly=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='online_material_id.mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    material_table_id = fields.Many2one(
        'sn.smt.material.table',
        string='Material Table',
        related='online_material_id.mt_id',
        store=True,
        readonly=True,
    )
    material_lot_id = fields.Many2one(
        'stock.lot',
        string='Material SN',
        required=True,
        check_company=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Material',
        related='material_lot_id.product_id',
        store=True,
        readonly=True,
    )
    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='Feeder',
        check_company=True,
    )
    cart_id = fields.Many2one(
        'sn.smt.cart',
        string='Material Cart',
        check_company=True,
    )
    old_material_lot_id = fields.Many2one(
        'stock.lot',
        string='Old Material SN',
        check_company=True,
    )
    change_type = fields.Selection(
        [('change', 'Change'), ('continue', 'Continue')],
        string='Change Type',
    )
    device_seq = fields.Integer(related='online_material_id.device_seq', store=True, readonly=True)
    table_no = fields.Char(related='online_material_id.table_no', store=True, readonly=True)
    loadpoint = fields.Char(related='online_material_id.loadpoint', store=True, readonly=True)
    chanel_sn = fields.Char(related='online_material_id.chanel_sn', store=True, readonly=True)
    is_online = fields.Selection(YN_SELECTION, string='IS_ONLINE', default='N', required=True)
    is_repeat = fields.Selection(YN_SELECTION, string='IS_REPEAT', default='N', required=True)
    item_type = fields.Selection(
        [('0', 'Material')],
        string='ITEM_TYPE',
        default='0',
        required=True,
    )
    action_type = fields.Selection(
        [('5', 'Offline Preparation')],
        string='ACTION_TYPE',
        default='5',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='online_material_id.company_id',
        store=True,
        readonly=True,
    )

    _sn_smt_offline_material_unique = models.Constraint(
        'unique(online_material_id)',
        'The same SMT position can only have one active offline preparation record.',
    )


class SnSmtCart(models.Model):
    _name = 'sn.smt.cart'
    _description = 'SMT Material Cart'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Cart SN', required=True, index=True)
    status = fields.Selection(
        [
            ('0', 'Idle'),
            ('1', 'In Use'),
        ],
        string='Status',
        default='0',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    offline_material_ids = fields.One2many(
        'sn.smt.offline.material',
        'cart_id',
        string='Offline Materials',
    )

    _sn_smt_cart_name_unique = models.Constraint(
        'unique(company_id, name)',
        'The cart SN must be unique per company.',
    )


class SnSmtConfig(models.Model):
    _name = 'sn.smt.config'
    _description = 'SMT Configuration'
    _order = 'key, id'
    _check_company_auto = True

    key = fields.Char(string='Key', required=True, index=True)
    value = fields.Char(string='Value', required=True)
    description = fields.Char(string='Description')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sn_smt_config_unique = models.Constraint(
        'unique(company_id, key)',
        'The SMT configuration key must be unique per company.',
    )

    @api.model
    def get_value(self, key, default=False, company=False):
        company = company or self.env.company
        record = self.search([
            ('company_id', '=', company.id),
            ('key', '=', key),
        ], limit=1)
        return record.value if record else default


class SnSmtOperationRecord(models.Model):
    _name = 'sn.smt.operation.record'
    _description = 'SMT Operation Record'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='production_id.x_mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    online_material_id = fields.Many2one(
        'sn.smt.online.material',
        string='Online Material',
        ondelete='restrict',
        check_company=True,
    )
    material_lot_id = fields.Many2one('stock.lot', string='Material SN', check_company=True)
    old_material_lot_id = fields.Many2one('stock.lot', string='Old Material SN', check_company=True)
    feeder_id = fields.Many2one('sn.smt.feeder', string='Feeder', check_company=True)
    cart_id = fields.Many2one('sn.smt.cart', string='Cart', check_company=True)
    operation_type = fields.Selection(
        [
            ('offline_prepare', 'Offline Prepare'),
            ('online_load', 'Online Load'),
            ('cart_load', 'Cart Load'),
            ('unload', 'Unload'),
            ('change', 'Change'),
            ('continue', 'Continue'),
            ('changeover_inherit', 'Changeover Inherit'),
        ],
        string='Operation Type',
        required=True,
    )
    is_online = fields.Selection(YN_SELECTION, string='Is Online', default='N', required=True)
    device_seq = fields.Integer(string='Device Sequence')
    table_no = fields.Char(string='TABLE No')
    loadpoint = fields.Char(string='Loadpoint')
    chanel_sn = fields.Char(string='Channel')
    item_code = fields.Char(string='Item Code')
    required_item_code = fields.Char(string='Main Item Code')
    actual_item_code = fields.Char(string='Actual Item Code')
    qty_before = fields.Float(string='Points Before')
    operation_qty = fields.Float(string='Operation Points')
    qty_after = fields.Float(string='Points After')
    operator_id = fields.Many2one('res.users', string='Operator', default=lambda self: self.env.user, check_company=True)
    operation_datetime = fields.Datetime(string='Operation Time', default=fields.Datetime.now, index=True)
    note = fields.Char(string='Note')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )


class SnSmtOperationLog(models.Model):
    _name = 'sn.smt.operation.log'
    _description = 'SMT Operation Log'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    operation_record_id = fields.Many2one(
        'sn.smt.operation.record',
        string='Operation Record',
        ondelete='cascade',
        check_company=True,
    )
    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='production_id.x_mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    event_type = fields.Char(string='Event Type', required=True)
    message = fields.Char(string='Message')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )


class SnSmtTraceability(models.Model):
    _name = 'sn.smt.traceability'
    _description = 'SMT Material Traceability'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    production_id = fields.Many2one('mrp.production', string='Manufacturing Order', required=True, check_company=True)
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        related='production_id.x_mes_order_id',
        store=True,
        readonly=True,
        index=True,
    )
    online_material_id = fields.Many2one(
        'sn.smt.online.material',
        string='Online Material',
        ondelete='restrict',
        check_company=True,
    )
    material_lot_id = fields.Many2one('stock.lot', string='Material SN', required=True, check_company=True)
    old_material_lot_id = fields.Many2one('stock.lot', string='Old Material SN', check_company=True)
    feeder_id = fields.Many2one('sn.smt.feeder', string='Feeder', check_company=True)
    cart_id = fields.Many2one('sn.smt.cart', string='Cart', check_company=True)
    action_type = fields.Char(string='Action Type', required=True)
    item_code = fields.Char(string='Item Code')
    device_seq = fields.Integer(string='Device Sequence')
    table_no = fields.Char(string='TABLE No')
    loadpoint = fields.Char(string='Loadpoint')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )


class SnSmtOperationMixin(models.AbstractModel):
    _name = 'sn.smt.operation.mixin'
    _description = 'SMT Operation Mixin'

    @api.model
    def _is_config_enabled(self, key, company):
        value = self.env['sn.smt.config'].get_value(key, default='0', company=company)
        return str(value).strip().upper() in {'1', 'Y', 'YES', 'TRUE', 'ON'}

    @api.model
    def _get_qc_flag(self, production):
        return 'Y' if self._is_config_enabled('QM011', production.company_id) else 'N'

    @api.model
    def _get_unload_release_enabled(self, production):
        return self._is_config_enabled('SMT020', production.company_id)

    @api.model
    def _get_mes_order_productions(self, production):
        mes_order = production.x_mes_order_id if production else self.env['sn.wsd.mes.order']
        return mes_order.production_id if mes_order else production


    @api.model
    def _normalize_product_code(self, product):
        return product.default_code if product else False

    @api.model
    def _is_allowed_material_product(self, required_product, candidate_product):
        if not required_product or not candidate_product:
            return False
        if candidate_product == required_product:
            return True
        return candidate_product in required_product.substitute_ids or required_product in candidate_product.substitute_for_ids

    @api.model
    def _check_same_mes_order(self, source_production, target_production):
        source_order = source_production.x_mes_order_id if source_production else False
        target_order = target_production.x_mes_order_id if target_production else False
        if source_order and target_order and source_order != target_order:
            raise UserError(_('The target manufacturing order must belong to the same MES order.'))
        return True

    @api.model
    def _check_feeder_mes_order_scope(self, feeder, production):
        if not feeder or not feeder.bound_production_id or feeder.bound_production_id == production:
            return True
        if feeder.bound_production_id not in self._get_mes_order_productions(production):
            raise UserError(_('The feeder is already bound to another MES order.'))
        return True

    @api.model
    def _check_material_expiration(self, lot):
        expiration_value = False
        for field_name in ('expiration_date', 'use_date', 'removal_date', 'alert_date'):
            if field_name in lot._fields and lot[field_name]:
                expiration_value = lot[field_name]
                break
        if not expiration_value:
            return
        expiration_dt = fields.Datetime.to_datetime(expiration_value) if not isinstance(expiration_value, datetime) else expiration_value
        if expiration_dt and expiration_dt < fields.Datetime.now():
            raise ValidationError(_('The material or product has expired.'))

    @api.model
    def _check_material_move_scope(self, production, material_lot, require_issue=False):
        moves = production.move_raw_ids.filtered(lambda move: move.state != 'cancel')
        if not moves:
            return
        target_moves = production._find_matching_raw_moves(material_lot.product_id)
        if not target_moves:
            raise ValidationError(_('The material is not reserved for the current manufacturing order.'))
        move_lines = target_moves.mapped('move_line_ids').filtered(
            lambda line: line.lot_id == material_lot and line.state != 'cancel'
        )
        if require_issue and not move_lines:
            raise ValidationError(_('The material has not been issued and cannot be loaded online.'))
        if target_moves.mapped('move_line_ids') and not move_lines:
            raise ValidationError(_('The material is not reserved for the current manufacturing order.'))

    @api.model
    def _check_material_common_rules(self, production, online_material, material_lot, require_issue=False, require_positive_qty=False):
        required_product = self.env['product.product'].search([
            ('default_code', '=', online_material.item_code),
        ], limit=1)
        if required_product and not production._is_allowed_substitute_product(required_product, material_lot.product_id):
            raise ValidationError(_('The material does not match the current SMT loadpoint requirement.'))
        if not required_product and self._normalize_product_code(material_lot.product_id) != online_material.item_code:
            raise ValidationError(_('The material does not match the current SMT loadpoint requirement.'))
        if require_positive_qty and material_lot.product_qty <= 0:
            raise ValidationError(_('The current material quantity is zero.'))
        if self.env['sn.smt.offline.material'].search_count([
            ('material_lot_id', '=', material_lot.id),
            ('is_online', '=', 'Y'),
        ], limit=1):
            raise ValidationError(_('The material is already loaded online or continued.'))
        self._check_material_expiration(material_lot)
        self._check_material_move_scope(production, material_lot, require_issue=require_issue)

    @api.model
    def _get_active_online_materials(self, production, include_skipped=False):
        lines = production.x_smt_online_material_ids
        if not include_skipped:
            lines = lines.filtered(lambda line: line.is_skip != 'Y')
        return lines

    @api.model
    def _is_scope_complete(self, lines):
        active_lines = lines.filtered(lambda line: line.is_skip != 'Y')
        return not active_lines.filtered(lambda line: line.is_load != 'Y')

    @api.model
    def _get_completion_snapshot(self, production):
        active_lines = self._get_active_online_materials(production)
        loaded_lines = active_lines.filtered(lambda line: line.is_load == 'Y')
        feeder_lines = production.feeder_line_ids.filtered(
            lambda line: line.state in ('pending', 'verified', 'consuming')
        )
        return {
            'required_qty': len(active_lines),
            'loaded_qty': len(loaded_lines),
            'unloaded_qty': len(active_lines - loaded_lines),
            'table_complete_keys': {
                (line.device_seq, line.table_no)
                for line in active_lines
                if self._is_scope_complete(
                    active_lines.filtered(
                        lambda current: current.device_seq == line.device_seq and current.table_no == line.table_no
                    )
                )
            },
            'machine_complete_keys': {
                line.device_seq
                for line in active_lines
                if self._is_scope_complete(
                    active_lines.filtered(lambda current: current.device_seq == line.device_seq)
                )
            },
            'line_complete': self._is_scope_complete(active_lines),
            'feeder_pending': bool(feeder_lines.filtered(lambda line: line.state == 'pending')),
        }

    @api.model
    def _sync_feeder_lines_after_unload(self, production, online_materials):
        if not online_materials:
            return
        feeder_lines = production.feeder_line_ids.filtered(
            lambda line: line.state in ('verified', 'consuming')
        )
        for feeder_line in feeder_lines:
            lot = feeder_line.lot_id
            if not lot:
                continue
            still_online = production.x_smt_online_material_ids.filtered(
                lambda line: line.is_load == 'Y' and line.loaded_material_lot_id == lot
            )
            if still_online:
                continue
            feeder_line.write({
                'actual_product_id': False,
                'lot_id': False,
                'lot_name': False,
                'loaded_qty': 0.0,
                'state': 'pending',
                'verify_datetime': False,
                'verify_user_id': False,
            })

    @api.model
    def _sync_feeder_binding_after_unload(self, production, feeder, release_enabled):
        if not feeder:
            return
        still_in_use = self.env['sn.smt.online.material'].search([
            ('production_id', 'in', self._get_mes_order_productions(production).ids),
            ('loaded_feeder_id', '=', feeder.id),
            ('is_load', '=', 'Y'),
        ], limit=1)
        if still_in_use:
            feeder.write({
                'status': '2',
                'bound_production_id': still_in_use.production_id.id,
            })
        elif release_enabled:
            feeder.write({'status': '1', 'bound_production_id': False})

    @api.model
    def _sync_production_after_smt_change(self, production):
        snapshot = self._get_completion_snapshot(production)
        if snapshot['line_complete']:
            production.x_smt_online_state = 'online'
            # Online is carried by the MES orders (制令单)
            production._action_online_mes_orders()
            if production._fields.get('x_meter_flow_state'):
                production.x_meter_flow_state = 'material_ready'
        else:
            if production._fields.get('x_meter_flow_state'):
                production.x_meter_flow_state = 'draft'
        return snapshot

    @api.model
    def _finalize_unload_lines(self, production, lines, unload_scope, clear_online_table=False):
        if not lines:
            return self.env['sn.smt.online.material']
        self._archive_online_operation_records(production, lines, note=unload_scope)
        now = fields.Datetime.now()
        release_enabled = self._get_unload_release_enabled(production)
        for line in lines:
            loaded_lot = line.loaded_material_lot_id
            loaded_feeder = line.loaded_feeder_id
            offline_records = self.env['sn.smt.offline.material'].search([
                ('online_material_id', '=', line.id),
            ])
            carts = offline_records.mapped('cart_id')
            line.write({
                'is_load': 'N',
                'is_qc_test': 'N',
                'loaded_material_lot_id': False,
                'loaded_feeder_id': False,
                'unloaded_at': now,
                'unload_scope': unload_scope,
            })
            offline_records.write({'is_online': 'N'})
            if loaded_feeder:
                self._sync_feeder_binding_after_unload(production, loaded_feeder, release_enabled)
            if loaded_lot:
                still_loaded_lot = self.env['sn.smt.online.material'].search_count([
                    ('loaded_material_lot_id', '=', loaded_lot.id),
                    ('is_load', '=', 'Y'),
                ], limit=1)
                if not still_loaded_lot:
                    loaded_lot.write({
                        'x_smt_reel_state': 'depleted'
                        if loaded_lot.x_smt_available_qty <= 0
                        else 'unloaded',
                    })
            for cart in carts:
                cart_lines = cart.offline_material_ids.filtered(lambda rec: rec.is_online == 'Y')
                if release_enabled and not cart_lines:
                    cart.status = '0'
            self._create_operation_bundle(
                production,
                online_material=line,
                operation_type='unload',
                material_lot=loaded_lot if loaded_lot else False,
                feeder=loaded_feeder if loaded_feeder else False,
                cart=carts[:1] if carts else False,
                is_online='N',
                note=unload_scope,
            )
        self._sync_feeder_lines_after_unload(production, lines)
        if clear_online_table:
            lines.unlink()
        self._sync_production_after_smt_change(production)
        return lines

    @api.model
    def _create_operation_bundle(self, production, online_material=False, operation_type=False, material_lot=False, old_material_lot=False, feeder=False, cart=False, is_online='N', note=False):
        loaded_qty = online_material.loaded_qty if online_material else 0.0
        consumed_qty = online_material.consumed_qty if online_material else 0.0
        record = self.env['sn.smt.operation.record'].create({
            'production_id': production.id,
            'online_material_id': online_material.id if online_material else False,
            'material_lot_id': material_lot.id if material_lot else False,
            'old_material_lot_id': old_material_lot.id if old_material_lot else False,
            'feeder_id': feeder.id if feeder else False,
            'cart_id': cart.id if cart else False,
            'operation_type': operation_type,
            'is_online': is_online,
            'device_seq': online_material.device_seq if online_material else False,
            'table_no': online_material.table_no if online_material else False,
            'loadpoint': online_material.loadpoint if online_material else False,
            'chanel_sn': online_material.chanel_sn if online_material else False,
            'item_code': online_material.item_code if online_material else False,
            'required_item_code': online_material.required_item_code if online_material else False,
            'actual_item_code': material_lot.product_id.default_code if material_lot else False,
            'qty_before': online_material.remaining_qty if online_material else 0.0,
            'operation_qty': loaded_qty if operation_type in ('online_load', 'continue', 'change') else 0.0,
            'qty_after': online_material.remaining_qty if online_material else 0.0,
            'operator_id': self.env.user.id,
            'operation_datetime': fields.Datetime.now(),
            'note': note,
            'company_id': production.company_id.id,
        })
        self.env['sn.smt.operation.log'].create({
            'operation_record_id': record.id,
            'production_id': production.id,
            'event_type': operation_type,
            'message': note or operation_type,
            'company_id': production.company_id.id,
        })
        if online_material and operation_type in dict(online_material._fields['last_operation_type'].selection):
            online_material.last_operation_type = operation_type
        if material_lot:
            self.env['sn.smt.traceability'].create({
                'production_id': production.id,
                'online_material_id': online_material.id if online_material else False,
                'material_lot_id': material_lot.id,
                'old_material_lot_id': old_material_lot.id if old_material_lot else False,
                'feeder_id': feeder.id if feeder else False,
                'cart_id': cart.id if cart else False,
                'action_type': operation_type,
                'item_code': online_material.item_code if online_material else False,
                'device_seq': online_material.device_seq if online_material else False,
                'table_no': online_material.table_no if online_material else False,
                'loadpoint': online_material.loadpoint if online_material else False,
                'company_id': production.company_id.id,
            })
        return record

    @api.model
    def _archive_online_operation_records(self, production, online_materials, note='XL'):
        if not online_materials:
            return self.env['sn.smt.operation.record']
        records = self.env['sn.smt.operation.record'].search([
            ('production_id', '=', production.id),
            ('online_material_id', 'in', online_materials.ids),
            ('is_online', '=', 'Y'),
        ])
        if not records:
            return records
        records.write({'is_online': 'N'})
        self.env['sn.smt.operation.log'].create([
            {
                'operation_record_id': record.id,
                'production_id': production.id,
                'event_type': 'archive',
                'message': note,
                'company_id': production.company_id.id,
            }
            for record in records
        ])
        return records


class SnSmtTableImportMixin(models.AbstractModel):
    _name = 'sn.smt.table.import.mixin'
    _description = 'SMT Table Import Mixin'

    @api.model
    def _parse_import_file(self, file_content):
        raw = base64.b64decode(file_content)
        text = raw.decode('utf-8-sig')
        rows = csv.DictReader(io.StringIO(text))
        return list(rows)

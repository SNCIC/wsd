import base64
import csv
import io
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from odoo.addons.sn_wsd_mrp.models.constants import SIDE_SELECTION


TRACK_TYPE_SELECTION = [
    ('single', 'Single Track'),
    ('dual', 'Dual Track'),
]

# 产品面别与工艺路线 sn.wsd.process_route.x_production_side 共用同一套 key。
PRODUCT_SIDE_SELECTION = SIDE_SELECTION

TABLE_TYPE_SELECTION = [
    ('smt', 'SMT Material Table'),
]

YN_SELECTION = [
    ('Y', 'Yes'),
    ('N', 'No'),
]

# 物料日志操作类型（英文稳定 key，界面中文经 zh_CN.po）。
MATERIAL_LOG_OPERATION_SELECTION = [
    ('offline_prepare', 'Offline Preparation'),
    ('online_load', 'Online Load'),
    ('cart_load', 'Cart Load'),
    ('change', 'Change'),
    ('continue', 'Continue'),
    ('unload', 'Unload'),
    ('changeover_inherit', 'Changeover Inherit'),
]


class SnSmtMaterialTable(models.Model):
    _name = 'sn.smt.material.table'
    _description = 'SMT Material Table'
    _order = 'model_code, product_side, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    table_name = fields.Char(string='TABLE_NAME', required=True, tracking=True)
    table_type = fields.Selection(TABLE_TYPE_SELECTION, string='TABLE_TYPE', default='smt', required=True)
    # 产品料号：取产品上的图号（product.default_code）
    model_code = fields.Char(string='MODEL_CODE', required=True, index=True, tracking=True)
    product_side = fields.Selection(PRODUCT_SIDE_SELECTION, string='PRODUCT_SIDE', required=True, index=True, tracking=True)
    item_count = fields.Integer(string='ITEM_COUNT')
    total_point_qty = fields.Integer(compute='_compute_total_point_qty', string='Total Points')
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

    @api.depends('table_name', 'model_code', 'product_side')
    def _compute_name(self):
        for record in self:
            record.name = record.table_name or ' / '.join(
                item for item in [record.model_code, record.product_side] if item
            )

    @api.depends('detail_ids')
    def _compute_detail_count(self):
        for record in self:
            record.detail_count = len(record.detail_ids)

    @api.depends('detail_ids.point_qty')
    def _compute_total_point_qty(self):
        for record in self:
            record.total_point_qty = sum(record.detail_ids.mapped('point_qty'))

    @api.constrains('line_link_ids')
    def _check_has_line_link(self):
        for record in self:
            if not record.line_link_ids:
                continue
            if any(link.company_id != record.company_id for link in record.line_link_ids):
                raise ValidationError(_('The linked production line company must match the material table company.'))

    @api.model
    def _match_for_mes_order(self, mes_order):
        """按 图号+面别 匹配制令单的料站表；优先取产线绑定的表，
        否则回退到未绑定任何产线的表。"""
        base_domain = [
            ('company_id', '=', mes_order.company_id.id),
            ('model_code', '=', mes_order.product_id.default_code),
            ('product_side', '=', mes_order.x_side),
            ('is_valid', '=', 'Y'),
        ]
        line = mes_order.production_line_id
        if line:
            candidates = self.search(base_domain + [
                ('line_link_ids.production_line_id', '=', line.id),
            ], limit=1)
            if candidates:
                return candidates
        unbound = self.search(base_domain + [
            ('line_link_ids', '=', False),
        ], limit=1)
        if unbound:
            return unbound
        return self.search(base_domain, limit=1)

    def _prepare_online_material_vals(self, mes_order):
        self.ensure_one()
        values = []
        for detail in self.detail_ids.sorted(lambda line: (line.device_seq, line.table_no, line.loadpoint, line.id)):
            values.append({
                'mt_id': self.id,
                'mes_order_id': mes_order.id,
                'model_code': mes_order.product_id.default_code,
                'area_sn': mes_order.production_line_id.code,
                'production_line_id': mes_order.production_line_id.id,
                'process_face': mes_order.x_side,
                'item_code': detail.item_code,
                'required_item_code': detail.item_code,
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
                'company_id': mes_order.company_id.id,
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

    @api.constrains('table_no')
    def _check_table_no_format(self):
        # The TABLE barcode scanned on the floor is DEVICE.TABLE (e.g. 2.B1):
        # DEVICE_SEQ carries the "2" and TABLE_NO must hold only "B1".
        # Storing the whole barcode in TABLE_NO can never match the parsed
        # station lookup, so every scan on that table would be rejected.
        # (Pattern kept in sync with DEVICE_TABLE_PATTERN in
        # sn_smt_loading_service.py.)
        for detail in self:
            if re.match(r'^\s*\d+\.', detail.table_no or ''):
                raise ValidationError(_(
                    'TABLE_NO must store the table name only (e.g. T1), not '
                    'the whole DEVICE.TABLE barcode (e.g. 1.T1); the device '
                    'sequence belongs in DEVICE_SEQ.'))


class SnSmtOnlineMaterial(models.Model):
    _name = 'sn.smt.online.material'
    _description = 'SMT Online Material'
    _order = 'mes_order_id, device_seq, table_no, loadpoint, id'
    _check_company_auto = True

    mt_id = fields.Many2one('sn.smt.material.table', string='MT_ID', check_company=True)
    # Row origin: SMT rows are split from the material table at order-online
    # time; drawing_list rows are split from the critical-material list by
    # sn_wsd_barcode for workshops without a material table (DIP / assembly).
    source = fields.Selection(
        [
            ('smt_table', 'SMT Material Table'),
            ('drawing_list', 'Drawing Material List'),
        ],
        string='Source',
        default='smt_table',
        required=True,
        index=True,
    )
    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        required=True,
        index=True,
        ondelete='cascade',
        check_company=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        index=True,
        check_company=True,
    )
    project_id = fields.Char(string='PROJECT_ID')
    model_code = fields.Char(string='MODEL_CODE', required=True, index=True)
    area_sn = fields.Char(string='AREA_SN', index=True)
    production_line_id = fields.Many2one('sn.mrp.production.line', string='Production Line', check_company=True)
    process_face = fields.Selection(PRODUCT_SIDE_SELECTION, string='PROCESS_FACE')
    item_code = fields.Char(string='ITEM_CODE', index=True)
    program_name = fields.Char(string='PROGRAM_NAME')
    device_seq = fields.Integer(string='DEVICE_SEQ')
    table_no = fields.Char(string='TABLE_NO')
    loadpoint = fields.Char(string='LOADPOINT')
    chanel_sn = fields.Char(string='CHANEL_SN')
    point_qty = fields.Integer(string='POINT_QTY')
    point_location = fields.Text(string='POINT_LOCATION')
    feeder_spec = fields.Char(string='FEEDER_SPEC')
    track_type = fields.Selection(TRACK_TYPE_SELECTION, string='TRACK_TYPE', default='single', required=True)
    is_tray = fields.Selection(YN_SELECTION, string='IS_TRAY', default='N', required=True)
    is_skip = fields.Selection(YN_SELECTION, string='IS_SKIP', default='N', required=True)
    is_load = fields.Selection(YN_SELECTION, string='IS_LOAD', default='N', required=True)
    is_qc_test = fields.Selection(YN_SELECTION, string='IS_QC_TEST', default='N', required=True)
    loaded_material_lot_id = fields.Many2one(
        'stock.lot',
        string='Loaded Material SN',
        copy=False,
        index=True,
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
    cart_id = fields.Many2one(
        'sn.smt.cart',
        string='Cart',
        copy=False,
        ondelete='set null',
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

    # 一个料站同一时刻只能有一盘料在线（同一制令单下唯一位置行）。
    _sn_smt_online_material_unique = models.Constraint(
        'unique(company_id, mes_order_id, device_seq, table_no, loadpoint, chanel_sn)',
        'The online material position must be unique per MES order.',
    )

    @api.depends('loaded_material_lot_id.product_id')
    def _compute_loaded_product_id(self):
        for record in self:
            record.loaded_product_id = record.loaded_material_lot_id.product_id

    @api.model
    def _get_active_lines(self, mes_order, include_skipped=False):
        lines = mes_order.x_smt_online_material_ids
        if not include_skipped:
            lines = lines.filtered(lambda line: line.is_skip != 'Y')
        return lines

    @api.model
    def _get_completion_snapshot(self, mes_order):
        active_lines = self._get_active_lines(mes_order)
        loaded_lines = active_lines.filtered(lambda line: line.is_load == 'Y')
        return {
            'required_qty': len(active_lines),
            'loaded_qty': len(loaded_lines),
            'unloaded_qty': len(active_lines - loaded_lines),
            'line_complete': not active_lines.filtered(lambda line: line.is_load != 'Y'),
        }


class SnSmtConfig(models.Model):
    """公司级 key-value 配置存储。SMT 域自身的配置项已随旧流程移除，
    该模型保留给跨域通用开关（如 sn_wsd_api 的 G0010 / MESSC010）。"""
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


class SnSmtMaterialLog(models.Model):
    _name = 'sn.smt.material.log'
    _description = 'SMT Material Log'
    _order = 'operated_at desc, id desc'
    _check_company_auto = True

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order',
        string='MES Order',
        required=True,
        index=True,
        ondelete='cascade',
        check_company=True,
    )
    online_material_id = fields.Many2one(
        'sn.smt.online.material',
        string='Online Material',
        ondelete='set null',
        index=True,
        check_company=True,
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter',
        string='Work Center',
        ondelete='set null',
        check_company=True,
    )
    operation_type = fields.Selection(
        MATERIAL_LOG_OPERATION_SELECTION,
        string='Operation Type',
        required=True,
        index=True,
    )
    material_lot_id = fields.Many2one(
        'stock.lot',
        string='Material SN',
        ondelete='restrict',
        index=True,
        check_company=True,
    )
    old_material_lot_id = fields.Many2one(
        'stock.lot',
        string='Old Material SN',
        ondelete='restrict',
        index=True,
        check_company=True,
    )
    old_lot_qty = fields.Float(string='Old Lot Remaining Points', copy=False)
    feeder_id = fields.Many2one(
        'sn.smt.feeder',
        string='Feeder',
        ondelete='restrict',
        check_company=True,
    )
    cart_id = fields.Many2one(
        'sn.smt.cart',
        string='Cart',
        ondelete='restrict',
        check_company=True,
    )
    device_seq = fields.Integer(string='Device Sequence')
    table_no = fields.Char(string='Table No')
    loadpoint = fields.Char(string='Loadpoint')
    chanel_sn = fields.Char(string='Channel')
    required_item_code = fields.Char(string='Required Item Code', index=True)
    actual_item_code = fields.Char(string='Actual Item Code', index=True)
    qty_before = fields.Float(string='Points Before', copy=False)
    qty_after = fields.Float(string='Points After', copy=False)
    operator_id = fields.Many2one(
        'res.users',
        string='Operator',
        default=lambda self: self.env.user,
        index=True,
        check_company=True,
    )
    operated_at = fields.Datetime(string='Operated At', default=fields.Datetime.now, index=True)
    note = fields.Char(string='Note')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )


class SnSmtOperationMixin(models.AbstractModel):
    """上料校验共用的物料/飞达规则（服务层调用）。"""
    _name = 'sn.smt.operation.mixin'
    _description = 'SMT Operation Mixin'

    @api.model
    def _normalize_product_code(self, product):
        return product.default_code if product else False

    @api.model
    def _is_allowed_material_product(self, mes_order, required_product, candidate_product):
        if not required_product or not candidate_product:
            return False
        if candidate_product == required_product:
            return True
        production = mes_order.production_id
        if production:
            return production._is_allowed_substitute_product(required_product, candidate_product)
        return candidate_product in required_product.substitute_ids or required_product in candidate_product.substitute_for_ids

    @api.model
    def _check_material_expiration(self, lot):
        expiration_value = False
        for field_name in ('expiration_date', 'use_date', 'removal_date', 'alert_date'):
            if field_name in lot._fields and lot[field_name]:
                expiration_value = lot[field_name]
                break
        if not expiration_value:
            return
        expiration_dt = fields.Datetime.to_datetime(expiration_value)
        if expiration_dt and expiration_dt < fields.Datetime.now():
            raise ValidationError(_('The material or product has expired.'))

    @api.model
    def _check_material_common_rules(self, mes_order, online_material, material_lot):
        """物料SN 只查不建；料号一致或替代料；未在其他位置在线；未过期；数量为正。"""
        if not material_lot:
            raise ValidationError(_('The material SN could not be resolved to a stock lot.'))
        product_model = self.env['product.product']
        required_product = product_model.search([
            ('default_code', '=', online_material.item_code),
        ], limit=1)
        if required_product and not self._is_allowed_material_product(mes_order, required_product, material_lot.product_id):
            raise ValidationError(_(
                'The material does not match the current SMT loadpoint requirement (%(required)s).',
                required=online_material.item_code,
            ))
        if not required_product and self._normalize_product_code(material_lot.product_id) != online_material.item_code:
            raise ValidationError(_(
                'The material does not match the current SMT loadpoint requirement (%(required)s).',
                required=online_material.item_code,
            ))
        if self.env['sn.smt.online.material'].search_count([
            ('loaded_material_lot_id', '=', material_lot.id),
            ('is_load', '=', 'Y'),
        ], limit=1):
            raise ValidationError(_('The material is already loaded online.'))
        self._check_material_expiration(material_lot)
        if material_lot._smt_on_hand_qty() <= 0:
            raise ValidationError(_('The current material quantity is zero.'))


class SnSmtTableImportMixin(models.AbstractModel):
    _name = 'sn.smt.table.import.mixin'
    _description = 'SMT Table Import Mixin'

    @api.model
    def _parse_import_file(self, file_content):
        raw = base64.b64decode(file_content)
        text = raw.decode('utf-8-sig')
        rows = csv.DictReader(io.StringIO(text))
        return list(rows)

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SerialIdentity(models.Model):
    _name = 'sn.wsd.serial.identity'
    _description = 'Physical Serial Identity'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(string='Physical SN', required=True, index=True, copy=False)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True,
    )
    origin_type = fields.Selection(
        [
            ('laser', 'Laser'),
            ('external', 'External'),
            ('manual', 'Manual'),
            ('migration', 'Migration'),
        ],
        default='external',
        required=True,
        index=True,
    )
    origin_production_id = fields.Many2one(
        'mrp.production', string='Origin Manufacturing Order', check_company=True, index=True,
    )
    origin_lot_id = fields.Many2one(
        'stock.lot', string='Origin Lot/Serial', check_company=True, index=True,
    )
    binding_ids = fields.One2many(
        'sn.wsd.serial.binding', 'serial_identity_id', string='Bindings',
    )
    bound_machine_binding_ids = fields.One2many(
        'sn.wsd.serial.binding', 'bound_serial_identity_id',
        string='Bound SNs',
    )
    # 回流凭证（oqc-ng-disposition）：OQC 拨回重走时存源检验单 id
    # （Integer 而非 m2o：本模块不依赖质量模块）。凭证在位时过站豁免
    # "已过站/次数上限"拦截，重走的过站行打 x_is_rework 标记；板重新
    # 通过质检工序时由 sn_wsd_quality 清零
    x_rework_inspection_id = fields.Integer(
        string='Rework Voucher Inspection', index=True, copy=False)
    x_rework_count = fields.Integer(
        string='Rework Count', default=0, copy=False)
    # 返工凭证范围收紧（oqc-disposition-closure 决策 1，任务 1.2）：
    # 凭证只对本制令单/目标工序有效，授权路线以发起时间为截断点，
    # 审计事件身份供质量侧回链。底层不依赖 quality 模块，故均为
    # 平凡字段/Integer 而非跨模块 m2o
    x_rework_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='Rework MES Order',
        check_company=True, index=True, copy=False,
        help='MES order the rework voucher was issued on: the voucher only '
             'exempts station gates for this order.')
    x_rework_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Rework Operation',
        check_company=True, index=True, copy=False,
        help='Route operation the rework voucher targets: the board must '
             'restart its re-walk from this operation.')
    x_rework_history_watermark = fields.Integer(
        string='Rework History Watermark', copy=False,
        help='Highest station-history row id of this SN when its OQC '
             'rework voucher was armed: only history rows with a greater '
             'id count as progress of that rework attempt (oqc-disposition-'
             'closure task 5.3). Robust where second-truncated timestamps '
             'cannot separate an old OK from the re-walk.')
    x_rework_started_at = fields.Datetime(
        string='Rework Started At', copy=False,
        help='When this rework attempt was issued. Only station passes '
             'after this timestamp count as re-walk progress for the '
             'voucher (route cutoff point).')
    x_rework_event_id_value = fields.Integer(
        string='Rework Audit Event ID', index=True, copy=False,
        help='Id of the OQC disposition event that issued the voucher '
             '(integer snapshot: this module must not depend on the '
             'quality module).')
    note = fields.Text()

    _name_company_uniq = models.Constraint(
        'unique(company_id, name)',
        'The physical serial number must be unique per company.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values['name'] = (values.get('name') or '').strip()
            if not values['name']:
                raise ValidationError(_('Physical SN is required.'))
        return super().create(vals_list)

    @api.model
    def get_or_create(self, serial_no, company, **values):
        serial_no = (serial_no or '').strip()
        if not serial_no:
            raise ValidationError(_('Physical SN is required.'))
        identity = self.with_context(active_test=False).search([
            ('name', '=', serial_no),
            ('company_id', '=', company.id),
        ], limit=1)
        if identity:
            updates = {}
            if not identity.active:
                updates['active'] = True
            for field_name in ('origin_type', 'origin_production_id', 'origin_lot_id'):
                value = values.get(field_name)
                if value and not identity[field_name]:
                    updates[field_name] = value.id if hasattr(value, 'id') else value
            if updates:
                identity.write(updates)
            return identity
        create_values = {
            'name': serial_no,
            'company_id': company.id,
            **{
                key: value.id if hasattr(value, 'id') else value
                for key, value in values.items()
                if key in ('origin_type', 'origin_production_id', 'origin_lot_id', 'note') and value
            },
        }
        return self.create(create_values)

    @api.model
    def generate_for_production(self, production, origin_type='manual'):
        """Reserve the next SN for a production's product. The coding-rule
        engine renders it when a rule targets this model (field segments
        reach the drawing number through origin_production_id), otherwise
        the legacy per-product sequence keeps the pre-migration behavior.
        Device-supplied SNs (get_or_create) never pass here."""
        self = self.with_company(production.company_id)
        proxy = self.new({
            'company_id': production.company_id.id,
            'origin_production_id': production.id,
        })
        rule = self.env['sn.code.rule']._find_rule(proxy)
        if rule:
            serial_no = rule.render(proxy)
        else:
            sequence = production._sn_product_sequence()
            serial_no = sequence.sudo().next_by_code(sequence.code)
        if not serial_no:
            raise ValidationError(_('No SN sequence is configured.'))
        return self.create({
            'name': serial_no,
            'company_id': production.company_id.id,
            'origin_type': origin_type,
            'origin_production_id': production.id,
        })

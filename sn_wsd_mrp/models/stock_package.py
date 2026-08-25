from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class StockPackage(models.Model):
    _inherit = 'stock.package'

    x_wsd_company_id = fields.Many2one(
        'res.company', string='WSD Company', default=lambda self: self.env.company, index=True,
    )
    x_wsd_package_role = fields.Selection(
        [('carton', 'Meter Carton'), ('pallet', 'Meter Pallet')],
        string='WSD Package Role',
        index=True,
        copy=False,
    )
    x_wsd_pack_state = fields.Selection(
        [('open', 'Open'), ('closed', 'Closed'), ('received', 'Received'),
         ('shipped', 'Shipped'), ('cancelled', 'Cancelled')],
        string='WSD Pack State',
        default='open',
        index=True,
        copy=False,
    )
    x_wsd_production_id = fields.Many2one(
        'mrp.production', string='Manufacturing Order', index=True, check_company=True, copy=False,
    )
    x_wsd_pack_time = fields.Datetime(copy=False, index=True)
    x_wsd_close_time = fields.Datetime(copy=False, index=True)
    x_wsd_operator_code = fields.Char(copy=False, index=True)
    x_meter_pack_record_ids = fields.One2many(
        'sn.wsd.meter.pack.record', 'carton_package_id', string='Meter Pack Records', readonly=True,
    )

    @api.constrains('name', 'x_wsd_company_id', 'x_wsd_package_role', 'x_wsd_pack_state')
    def _check_wsd_package_reference(self):
        for package in self.filtered(lambda item: item.x_wsd_package_role and item.x_wsd_pack_state != 'cancelled'):
            duplicate = self.search([
                ('id', '!=', package.id),
                ('name', '=', package.name),
                ('x_wsd_company_id', '=', package.x_wsd_company_id.id),
                ('x_wsd_package_role', '!=', False),
                ('x_wsd_pack_state', '!=', 'cancelled'),
            ], limit=1)
            if duplicate:
                raise ValidationError(_('Package reference %s is already in use.') % package.name)

    @api.constrains('parent_package_id', 'x_wsd_package_role')
    def _check_wsd_package_hierarchy(self):
        for package in self.filtered('parent_package_id'):
            if package.x_wsd_package_role == 'pallet':
                raise ValidationError(_('A meter pallet cannot be placed inside another package.'))
            if package.x_wsd_package_role == 'carton' and package.parent_package_id.x_wsd_package_role != 'pallet':
                raise ValidationError(_('A meter carton can only be bound to a meter pallet.'))

    @api.model
    def get_or_create_wsd_package(self, reference, role, company, **values):
        reference = (reference or '').strip()
        if not reference:
            raise ValidationError(_('Package reference is required.'))
        package = self.search([
            ('name', '=', reference),
            ('x_wsd_company_id', '=', company.id),
            ('x_wsd_pack_state', '!=', 'cancelled'),
        ], limit=1)
        if package:
            if package.x_wsd_package_role and package.x_wsd_package_role != role:
                raise ValidationError(_(
                    'Package reference %(reference)s is already used as %(role)s.'
                ) % {'reference': reference, 'role': package.x_wsd_package_role})
            updates = {}
            if not package.x_wsd_package_role:
                updates['x_wsd_package_role'] = role
            for field_name, value in values.items():
                if field_name in self._fields and value and not package[field_name]:
                    updates[field_name] = value.id if hasattr(value, 'id') else value
            if updates:
                package.write(updates)
            return package
        package_type = self.env.ref(
            'sn_wsd_mrp.package_type_meter_carton' if role == 'carton' else 'sn_wsd_mrp.package_type_meter_pallet',
            raise_if_not_found=False,
        )
        create_values = {
            'name': reference,
            'package_type_id': package_type.id if package_type else False,
            'x_wsd_company_id': company.id,
            'x_wsd_package_role': role,
            'x_wsd_pack_state': 'open',
            'x_wsd_pack_time': fields.Datetime.now(),
        }
        create_values.update({
            key: value.id if hasattr(value, 'id') else value
            for key, value in values.items()
            if key in self._fields and value
        })
        return self.create(create_values)


class CartonPalletBindingLog(models.Model):
    _name = 'sn.wsd.carton.pallet.binding.log'
    _description = 'Carton Pallet Binding Log'
    _order = 'event_time desc, id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    carton_package_id = fields.Many2one('stock.package', required=True, ondelete='restrict', index=True)
    pallet_package_id = fields.Many2one('stock.package', required=True, ondelete='restrict', index=True)
    previous_pallet_package_id = fields.Many2one('stock.package', ondelete='restrict', index=True)
    event_type = fields.Selection(
        [('bind', 'Bind'), ('unbind', 'Unbind'), ('move', 'Move'), ('close', 'Close'), ('receive', 'Receive')],
        required=True,
        default='bind',
        index=True,
    )
    operator_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, index=True)
    operator_code = fields.Char(index=True)
    event_time = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    reason = fields.Char()
    device_code = fields.Char(index=True)

    @api.model
    def bind_carton_to_pallet(self, pallet_no, carton_no, operator_code=None, device_code=None):
        company = self.env.company
        package_model = self.env['stock.package']
        pallet = package_model.get_or_create_wsd_package(
            pallet_no, 'pallet', company, x_wsd_operator_code=operator_code,
        )
        carton = package_model.search([
            ('name', '=', (carton_no or '').strip()),
            ('x_wsd_company_id', '=', company.id),
            ('x_wsd_package_role', '=', 'carton'),
            ('x_wsd_pack_state', '!=', 'cancelled'),
        ], limit=1)
        if not carton:
            raise ValidationError(_('Meter carton %s was not found.') % (carton_no or ''))
        if carton.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('Meter carton %s has already been shipped.') % carton.name)
        if pallet.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('Meter pallet %s has already been shipped.') % pallet.name)
        if pallet.x_wsd_pack_state == 'closed':
            raise ValidationError(_('Meter pallet %s is closed.') % pallet.name)
        if not carton.x_meter_pack_record_ids:
            raise ValidationError(_('Meter carton %s does not contain any meter pack record.') % carton.name)
        if carton.parent_package_id == pallet:
            return {
                'ok': True,
                'duplicated': True,
                'confirm_unbind': True,
                'carton_id': carton.id,
                'carton_no': carton.name,
                'pallet_id': pallet.id,
                'pallet_no': pallet.name,
                'carton_count': len(pallet.child_package_ids),
                'meter_count': sum(len(item.x_meter_pack_record_ids) for item in pallet.child_package_ids),
                'message': _('Meter carton %s is bound to the current pallet. Scan it again to unbind.',
                             carton.name),
            }
        if carton.parent_package_id and carton.parent_package_id.id != pallet.id:
            return {
                'ok': True,
                'confirm_move': True,
                'carton_no': carton.name,
                'current_pallet_no': carton.parent_package_id.name,
                'message': _('Meter carton %(carton)s is bound to pallet %(pallet)s. Scan it again to move it to the current pallet.',
                             carton=carton.name, pallet=carton.parent_package_id.name),
            }
        carton.parent_package_id = pallet
        carton.x_meter_pack_record_ids.write({'pallet_package_id': pallet.id, 'pallet_no': pallet.name})
        self.create({
            'company_id': company.id,
            'carton_package_id': carton.id,
            'pallet_package_id': pallet.id,
            'event_type': 'bind',
            'operator_code': operator_code,
            'device_code': device_code,
        })
        return {
            'ok': True,
            'duplicated': False,
            'carton_id': carton.id,
            'carton_no': carton.name,
            'pallet_id': pallet.id,
            'pallet_no': pallet.name,
            'carton_count': len(pallet.child_package_ids),
            'meter_count': sum(len(item.x_meter_pack_record_ids) for item in pallet.child_package_ids),
        }

    @api.model
    def close_pallet(self, pallet_no, operator_code=None, device_code=None):
        pallet = self.env['stock.package'].search([
            ('name', '=', (pallet_no or '').strip()),
            ('x_wsd_company_id', '=', self.env.company.id),
            ('x_wsd_package_role', '=', 'pallet'),
        ], limit=1)
        if not pallet:
            raise ValidationError(_('Meter pallet %s was not found.') % (pallet_no or ''))
        if not pallet.child_package_ids:
            raise ValidationError(_('An empty meter pallet cannot be closed.'))
        if pallet.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('Meter pallet %s has already been shipped.') % pallet.name)
        if pallet.x_wsd_pack_state != 'closed':
            pallet.write({'x_wsd_pack_state': 'closed', 'x_wsd_close_time': fields.Datetime.now()})
            self.create({
                'company_id': self.env.company.id,
                'carton_package_id': pallet.child_package_ids[:1].id,
                'pallet_package_id': pallet.id,
                'event_type': 'close',
                'operator_code': operator_code,
                'device_code': device_code,
            })
        return {
            'ok': True,
            'pallet_id': pallet.id,
            'pallet_no': pallet.name,
            'carton_count': len(pallet.child_package_ids),
            'meter_count': sum(len(item.x_meter_pack_record_ids) for item in pallet.child_package_ids),
        }

    # ------------------------------------------------------------------
    # 解绑 / 换绑 / 攒托入库（pallet-unbind-receipt）
    # ------------------------------------------------------------------

    def _pallet_result(self, pallet):
        return {
            'ok': True,
            'pallet_id': pallet.id,
            'pallet_no': pallet.name,
            'carton_count': len(pallet.child_package_ids),
            'meter_count': sum(len(item.x_meter_pack_record_ids) for item in pallet.child_package_ids),
        }

    @api.model
    def unbind_carton_from_pallet(self, pallet_no, carton_no, operator_code=None, device_code=None):
        """解绑：箱离开当前托盘（只动 箱↔托盘，不动 产品↔箱）。"""
        pallet = self.env['stock.package'].search([
            ('name', '=', (pallet_no or '').strip()),
            ('x_wsd_company_id', '=', self.env.company.id),
            ('x_wsd_package_role', '=', 'pallet'),
        ], limit=1)
        if not pallet:
            raise ValidationError(_('Meter pallet %s was not found.') % (pallet_no or ''))
        carton = self.env['stock.package'].search([
            ('name', '=', (carton_no or '').strip()),
            ('x_wsd_company_id', '=', self.env.company.id),
            ('x_wsd_package_role', '=', 'carton'),
        ], limit=1)
        if not carton or carton.parent_package_id.id != pallet.id:
            raise ValidationError(_('Meter carton %s is not bound to pallet %s.',
                                    (carton_no or ''), pallet.name))
        if carton.x_wsd_pack_state == 'shipped' or pallet.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('A shipped pallet or carton cannot be unbound.'))
        if pallet.x_wsd_pack_state in ('closed', 'received'):
            raise ValidationError(_('Meter pallet %s is %s; unbind is not allowed.',
                                    pallet.name, pallet.x_wsd_pack_state))
        carton.parent_package_id = False
        carton.x_meter_pack_record_ids.write({'pallet_package_id': False, 'pallet_no': False})
        self.create({
            'company_id': self.env.company.id,
            'carton_package_id': carton.id,
            'pallet_package_id': pallet.id,
            'event_type': 'unbind',
            'operator_code': operator_code,
            'device_code': device_code,
        })
        result = self._pallet_result(pallet)
        result.update({'carton_no': carton.name, 'unbound': True})
        return result

    @api.model
    def move_carton_to_pallet(self, pallet_no, carton_no, operator_code=None, device_code=None):
        """换绑：箱从原托盘移到当前托盘，记 move 日志（previous 记来源）。"""
        pallet = self.env['stock.package'].search([
            ('name', '=', (pallet_no or '').strip()),
            ('x_wsd_company_id', '=', self.env.company.id),
            ('x_wsd_package_role', '=', 'pallet'),
        ], limit=1)
        if not pallet:
            raise ValidationError(_('Meter pallet %s was not found.') % (pallet_no or ''))
        if pallet.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('Meter pallet %s has already been shipped.',)) % (pallet.name,)
        if pallet.x_wsd_pack_state in ('closed', 'received'):
            raise ValidationError(_('Meter pallet %s is %s; binding is not allowed.',
                                    pallet.name, pallet.x_wsd_pack_state))
        carton = self.env['stock.package'].search([
            ('name', '=', (carton_no or '').strip()),
            ('x_wsd_company_id', '=', self.env.company.id),
            ('x_wsd_package_role', '=', 'carton'),
        ], limit=1)
        if not carton or not carton.parent_package_id:
            raise ValidationError(_('Meter carton %s is not bound to any pallet.',
                                    (carton_no or '')))
        previous_pallet = carton.parent_package_id
        if previous_pallet.x_wsd_pack_state == 'shipped':
            raise ValidationError(_('The source pallet has already been shipped.'))
        if previous_pallet.x_wsd_pack_state in ('closed', 'received'):
            raise ValidationError(_('The source pallet is %s; move is not allowed.',
                                    previous_pallet.x_wsd_pack_state))
        carton.parent_package_id = pallet
        carton.x_meter_pack_record_ids.write({'pallet_package_id': pallet.id, 'pallet_no': pallet.name})
        self.create({
            'company_id': self.env.company.id,
            'carton_package_id': carton.id,
            'pallet_package_id': pallet.id,
            'previous_pallet_package_id': previous_pallet.id,
            'event_type': 'move',
            'operator_code': operator_code,
            'device_code': device_code,
        })
        result = self._pallet_result(pallet)
        result.update({'carton_no': carton.name,
                       'moved_from': previous_pallet.name, 'moved': True})
        return result

    @api.model
    def receive_pallets(self, pallet_nos, operator_code=None, device_code=None, dry_run=False):
        """攒托入库：前端攒好的托盘列表一次开单（单事务）。

        按制令单聚合箱内包装记录；每单调既有完工入库机制
        （backflush + receipt + x_done_qty 累计 + 齐量关单），
        receipt 的 move line 按箱挂 package 结构。全部成功后托盘 → received。
        """
        package_model = self.env['stock.package']
        company = self.env.company
        pallets = package_model
        for pallet_no in pallet_nos or []:
            pallet = package_model.search([
                ('name', '=', (pallet_no or '').strip()),
                ('x_wsd_company_id', '=', company.id),
                ('x_wsd_package_role', '=', 'pallet'),
            ], limit=1)
            if not pallet:
                raise ValidationError(_('Meter pallet %s was not found.',)) % (pallet_no,)
            if pallet.x_wsd_pack_state == 'received':
                raise ValidationError(_('Meter pallet %s was already received.',)) % (pallet.name,)
            if pallet.x_wsd_pack_state == 'shipped':
                raise ValidationError(_('Meter pallet %s has already been shipped.',)) % (pallet.name,)
            if pallet.x_wsd_pack_state != 'closed':
                raise ValidationError(_('Meter pallet %s is not closed yet.',)) % (pallet.name,)
            if not pallet.child_package_ids:
                raise ValidationError(_('Meter pallet %s is empty.',)) % (pallet.name,)
            pallets |= pallet

        if dry_run:
            return {
                'ok': True,
                'pallets': [{
                    'pallet_no': p.name,
                    'carton_count': len(p.child_package_ids),
                    'meter_count': sum(len(item.x_meter_pack_record_ids) for item in p.child_package_ids),
                } for p in pallets],
            }

        # 按制令单聚合：order -> (qty, cartons)
        order_map = {}
        for pallet in pallets:
            for carton in pallet.child_package_ids:
                for record in carton.x_meter_pack_record_ids:
                    order = record.production_id.x_mes_order_id
                    if not order:
                        raise ValidationError(_(
                            'Pack record %s has no MES order; cannot receive.',
                            record.name))
                    entry = order_map.setdefault(order, {'qty': 0, 'cartons': carton.browse()})
                    entry['qty'] += 1
                    entry['cartons'] |= carton

        receipts = []
        for order, entry in order_map.items():
            if order.state not in ('in_progress',) or not order.x_online_date:
                raise ValidationError(_(
                    'MES order %s must be online and in progress to receive products.',
                    order.name))
            if order.x_done_qty + entry['qty'] > order.x_output_qty + 0.0001:
                raise ValidationError(_(
                    'MES order %(order)s: receiving %(new)d would exceed the output '
                    'target (%(done)d / %(target)d).',
                    order=order.name, new=entry['qty'],
                    done=order.x_done_qty, target=order.x_output_qty))
            order._mes_backflush(entry['qty'])
            picking = order._mes_create_pallet_receipt(
                entry['qty'], entry['cartons'],
                origin_pallets=', '.join(pallets.mapped('name')))
            order.write({
                'x_done_qty': order.x_done_qty + entry['qty'],
                'x_done_date': fields.Datetime.now(),
            })
            if order.x_done_qty + 0.0001 >= order.x_output_qty:
                order.state = 'done'
                order._on_done()
            receipts.append({'order': order.name, 'picking': picking.name,
                             'qty': entry['qty']})

        pallets.write({'x_wsd_pack_state': 'received'})
        for pallet in pallets:
            self.create({
                'company_id': company.id,
                'carton_package_id': pallet.child_package_ids[:1].id,
                'pallet_package_id': pallet.id,
                'event_type': 'receive',
                'operator_code': operator_code,
                'device_code': device_code,
                'reason': _('receipt: %s', ', '.join(r['picking'] for r in receipts)),
            })
        return {'ok': True, 'receipts': receipts,
                'pallet_nos': pallets.mapped('name')}

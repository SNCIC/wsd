from odoo import _, api, models
from odoo.exceptions import UserError


class SnWsdRepairService(models.AbstractModel):
    """PDA service layer for product repair: scan SN in, translated message out.

    Shares the model actions used by the UI buttons so guards stay identical.
    """

    _name = 'sn.wsd.repair.service'
    _description = 'SN WSD Repair PDA Service'

    @api.model
    def _resolve_sn(self, sn):
        identity = self.env['sn.wsd.serial.identity'].search(
            [('name', '=', sn), ('company_id', '=', self.env.company.id)], limit=1)
        if not identity:
            raise UserError(_('SN %s does not exist.', sn))
        return identity

    @api.model
    def _resolve_dict(self, model, value, field_names, label):
        """Resolve a dictionary record by id or by code/name."""
        if not value:
            return self.env[model]
        if isinstance(value, int):
            record = self.env[model].browse(value)
            if record.exists():
                return record
            raise UserError(_('%s %s does not exist.', label, value))
        domain = [(name, '=', str(value)) for name in field_names]
        record = self.env[model].search(
            ['|'] * (len(domain) - 1) + domain
            + [('company_id', 'in', [self.env.company.id, False])], limit=1)
        if not record:
            raise UserError(_('%s %s does not exist.', label, value))
        return record

    @api.model
    def _get_open_order(self, sn):
        identity = self._resolve_sn(sn)
        order = self.env['sn.wsd.repair.order'].search(
            [('serial_identity_id', '=', identity.id),
             ('state', 'in', ('draft', 'reported', 'repairing'))],
            order='id desc', limit=1)
        return identity, order

    @api.model
    def resolve(self, sn):
        identity, order = self._get_open_order(sn)
        route_operation = identity._current_route_operation()
        production = route_operation.mes_order_id.production_id if route_operation else False
        return {
            'sn': identity.name,
            'product': production.product_id.display_name if production else '',
            'current_route_operation': route_operation.display_name if route_operation else '',
            'open_repair_order': order.name or '',
            'open_repair_state': order.state or '',
            'repair_count': len(identity.repair_order_ids),
        }

    @api.model
    def report(self, sn, defect_code, location=None, cause=None, note=None, lines=None):
        """Report a repair for a defective SN. defect_code/cause accept ids or codes.

        lines: optional list of {'defect_code': code/id, 'qty': int, 'location': str}
        describing multiple defects; defect_code stays the main defect."""
        identity, order = self._get_open_order(sn)
        if order:
            raise UserError(_(
                'SN %s already has an open repair order %s.', sn, order.name))
        defect = self._resolve_dict(
            'sn.wsd.quality.defect.code', defect_code, ['code', 'name'], _('Defect code'))
        if not defect:
            raise UserError(_('A defect code is required.'))
        cause_rec = self._resolve_dict(
            'sn.wsd.repair.cause', cause, ['code', 'name'], _('Failure cause'))
        route_operation = identity._current_route_operation()
        if not route_operation:
            raise UserError(_('SN %s has no current route operation.', sn))
        line_commands = []
        if not lines:
            lines = [{'defect_code': defect_code, 'qty': 1, 'location': location}]
        for line in lines:
            line_defect = self._resolve_dict(
                'sn.wsd.quality.defect.code', line.get('defect_code'),
                ['code', 'name'], _('Defect code'))
            if not line_defect:
                raise UserError(_('A defect code is required.'))
            line_commands.append((0, 0, {
                'defect_code_id': line_defect.id,
                'qty': int(line.get('qty', 1)),
                'defect_location': line.get('location'),
            }))
        order = self.env['sn.wsd.repair.order'].create({
            'serial_identity_id': identity.id,
            'serial_no': identity.name,
            'defect_code_id': defect.id,
            'failure_cause_id': cause_rec.id,
            'defect_location': location,
            'note': note,
            'defect_line_ids': line_commands,
        })
        order.action_report_repair()
        return _('Repair order %s reported for %s.', order.name, sn)

    @api.model
    def start(self, sn, entry_route_operation=None):
        serial, order = self._get_open_order(sn)
        if not order:
            raise UserError(_('SN %s has no open repair order.', sn))
        if order.state != 'reported':
            raise UserError(_('Repair order %s cannot start (state %s).', order.name, order.state))
        if entry_route_operation:
            # Route operations carry no business code: accept the record id.
            entry = self.env['sn.wsd.mes.order.route.operation'].browse(
                int(entry_route_operation))
            if not entry.exists():
                raise UserError(_('Route operation %s does not exist.', entry_route_operation))
            if entry.mes_order_id != order.mes_order_id:
                raise UserError(_(
                    'The entry operation does not belong to the MES order of repair %s.', order.name))
            order.repair_entry_route_operation_id = entry.id
        order.action_start_repair()
        entry = order._get_repair_entry_route_operation()
        return _('Repair %s started, SN %s flows back to %s.',
                 order.name, sn, entry.display_name)

    @api.model
    def ok(self, sn, method=None, location=None, cause=None, replacement_product=None):
        serial, order = self._get_open_order(sn)
        if not order:
            raise UserError(_('SN %s has no open repair order.', sn))
        if order.state != 'repairing':
            raise UserError(_('Repair order %s is not under repair.', order.name))
        values = {}
        if method:
            values['repair_method'] = method
        if location:
            values['defect_location'] = location
        cause_rec = self._resolve_dict(
            'sn.wsd.repair.cause', cause, ['code', 'name'], _('Failure cause'))
        if cause_rec:
            values['failure_cause_id'] = cause_rec.id
        if replacement_product:
            product = self._resolve_dict(
                'product.product', replacement_product,
                ['default_code', 'barcode'], _('Product'))
            if product:
                values['replacement_product_id'] = product.id
        if values:
            order.with_context(allow_repair_order_write=True).write(values)
        entry = order._get_repair_entry_route_operation()
        order.action_repair_ok()
        return _('Repair %s done, SN %s returns to %s.', order.name, sn, entry.display_name)

    @api.model
    def scrap(self, sn, reason):
        serial, order = self._get_open_order(sn)
        if not order:
            raise UserError(_('SN %s has no open repair order.', sn))
        reason_rec = self._resolve_dict(
            'sn.wsd.scrap.reason', reason, ['code', 'name'], _('Scrap reason'))
        if not reason_rec:
            raise UserError(_('A scrap reason is required.'))
        order.scrap_reason_id = reason_rec.id
        order.action_repair_scrap()
        return _('Repair %s scrapped SN %s.', order.name, sn)

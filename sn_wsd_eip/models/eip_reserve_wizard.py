"""Re-serve wizard (user decision 2026-11-27): the gateway may not
display data it was served; the manager re-queues the delivered
snapshots of ONE work order and ONE interface -- the next gateway pull
delivers the very same payload again. Opened from the collect-outbox
list action menu with the selection prefilling the wizard."""
from odoo import _, api, fields, models


class EipReserveWizard(models.TransientModel):
    _name = 'sn.wsd.eip.reserve.wizard'
    _description = 'EIP Collection Re-serve by Work Order and Interface'

    work_order_no = fields.Char(
        string='Work Order No', required=True,
        help='Every delivered snapshot carrying this work order number '
             'is re-queued.')
    info_type_code = fields.Selection(
        selection='_selection_interface_codes',
        string='Info Type Code', required=True,
        help='The interface whose delivered snapshots of the work order '
             'are re-queued.')

    @api.model
    def _selection_interface_codes(self):
        interfaces = self.env['sn.wsd.eip.collect.interface'].with_context(
            active_test=True).search([], order='code')
        return [(item.code, '%s %s' % (item.code, item.name))
                for item in interfaces]

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        # opened from the collect-outbox list action menu: prefill from
        # the selected snapshot(s)
        records = self.env['sn.wsd.eip.collect.outbox'].browse(
            self.env.context.get('active_ids') or [])
        first = records.filtered(
            lambda row: row.work_order_no)[:1]
        if first:
            defaults['work_order_no'] = first.work_order_no
            defaults['info_type_code'] = first.info_type_code
        return defaults

    def action_re_serve(self):
        self.ensure_one()
        targets = self.env['sn.wsd.eip.collect.outbox']._eip_re_serve(
            self.work_order_no.strip(), self.info_type_code)
        self.env['bus.bus']._sendone(
            self.env.user.partner_id, 'simple_notification', {
                'type': 'success',
                'title': _('Re-served'),
                'message': _(
                    '%(total)s snapshots re-queued for work order '
                    '%(order)s / interface %(code)s: the gateway fetches '
                    'the same payloads again.',
                    total=len(targets),
                    order=self.work_order_no,
                    code=self.info_type_code),
            })
        return {'type': 'ir.actions.act_window_close'}

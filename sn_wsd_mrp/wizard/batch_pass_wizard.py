from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.sn_wsd_mrp.models.batch_pass_log import BATCH_PASS_REASONS


class SnWsdBatchPassWizard(models.TransientModel):
    """One confirmation dialog shared by both entries (MES order form
    and shop-floor terminal): the order's in-progress SNs, the ones that
    cannot move auto-excluded with a reason, a mandatory reason category
    and a confirm button. Confirm calls the order service -- one
    transaction for the whole batch."""
    _name = 'sn.wsd.batch.pass.wizard'
    _description = 'Batch Station Pass Wizard'

    mes_order_id = fields.Many2one(
        'sn.wsd.mes.order', string='MES Order', required=True,
        ondelete='cascade',
    )
    route_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Operation', required=True,
        domain="[('mes_order_id', '=', mes_order_id)]",
        ondelete='cascade',
    )
    workcenter_id = fields.Many2one(
        'mrp.workcenter', string='Work Center',
        help='Terminal entry context only (which screen opened the dialog).',
    )
    reason = fields.Selection(
        BATCH_PASS_REASONS, string='Reason', required=True,
    )
    note = fields.Char(string='Note')
    line_ids = fields.One2many(
        'sn.wsd.batch.pass.wizard.line', 'wizard_id', string='Serials',
    )
    eligible_count = fields.Integer(
        string='Eligible', compute='_compute_line_counts',
    )
    excluded_count = fields.Integer(
        string='Excluded', compute='_compute_line_counts',
    )
    excluded_summary = fields.Char(
        string='Excluded Summary', compute='_compute_line_counts',
    )

    @api.depends('line_ids.selected', 'line_ids.block_reason')
    def _compute_line_counts(self):
        for wizard in self:
            lines = wizard.line_ids
            wizard.eligible_count = len(
                lines.filtered(lambda l: l.selected and not l.block_reason))
            excluded = lines.filtered(lambda l: l.block_reason)
            wizard.excluded_count = len(excluded)
            wizard.excluded_summary = ' ; '.join(
                f'{line.serial_name}: {line.block_reason}'
                for line in excluded[:10])

    @api.onchange('mes_order_id', 'route_operation_id')
    def _onchange_load_lines(self):
        self.line_ids = [(5, 0, 0)]
        if not (self.mes_order_id and self.route_operation_id):
            return
        order = self.mes_order_id
        Wip = self.env['sn.wsd.serial.wip']
        wips = Wip.search([('mes_order_id', '=', order.id)])
        now = fields.Datetime.now()
        vals_list = []
        for wip in wips:
            if wip.route_operation_id != self.route_operation_id and \
                    self.route_operation_id not in \
                    order._batch_pass_downstream_ops(wip.route_operation_id):
                continue  # already past the target: not our business
            block = order._batch_pass_block_reason(
                wip.serial_identity_id, self.route_operation_id)
            park_hours = (
                (now - wip.in_date).total_seconds() / 3600.0
                if wip.in_date else 0.0)
            vals_list.append({
                'serial_identity_id': wip.serial_identity_id.id,
                'serial_name': wip.serial_identity_id.name,
                'current_operation_id': wip.route_operation_id.id,
                'park_hours': round(park_hours, 1),
                'block_reason': block or False,
                'selected': not block,
            })
        self.line_ids = [(0, 0, vals) for vals in vals_list]

    def action_confirm(self):
        self.ensure_one()
        if not self.reason:
            raise ValidationError(_('Pick a batch pass reason.'))
        lines = self.line_ids.filtered(
            lambda l: l.selected and not l.block_reason)
        if not lines:
            raise ValidationError(_('Select at least one SN.'))
        receipt = self.mes_order_id.action_batch_pass_station(
            lines.mapped('serial_identity_id').ids,
            self.route_operation_id, self.reason, note=self.note or False)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Batch Station Pass'),
                'message': _(
                    '%(count)s SNs passed %(op)s on %(order)s; the boards '
                    'are parked at the next station.',
                    count=receipt['passed'], op=receipt['operation'],
                    order=receipt['order_name']),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SnWsdBatchPassWizardLine(models.TransientModel):
    _name = 'sn.wsd.batch.pass.wizard.line'
    _description = 'Batch Station Pass Wizard Line'

    wizard_id = fields.Many2one(
        'sn.wsd.batch.pass.wizard', required=True, ondelete='cascade',
    )
    serial_identity_id = fields.Many2one(
        'sn.wsd.serial.identity', string='SN', required=True,
        ondelete='cascade',
    )
    serial_name = fields.Char(string='SN')
    current_operation_id = fields.Many2one(
        'sn.wsd.mes.order.route.operation', string='Parked At',
        ondelete='cascade',
    )
    park_hours = fields.Float(string='Parked (h)')
    selected = fields.Boolean(string='Pass Through', default=True)
    block_reason = fields.Char(string='Excluded Because')

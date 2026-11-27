"""Backfill of packing-storage rows for nameplate bindings that predate
the capture hook (or SNs unmapped at binding time): typed work order,
one click, the same capture as the hook."""
from odoo import _, fields, models
from odoo.exceptions import UserError


class EipPackCaptureWizard(models.TransientModel):
    _name = 'sn.wsd.eip.pack.capture.wizard'
    _description = 'EIP Packing Storage Capture by Work Order'

    work_order_no = fields.Char(
        string='Work Order No', required=True,
        help='Every nameplate binding of the machines passed under this '
             'work order gets its packing-storage row.')

    def action_capture(self):
        self.ensure_one()
        number = self.work_order_no.strip()
        # the typed number is the EIP work order number: when a ledger
        # carries it, every MES order linked to the ledger is captured
        # (SMT / DIP / assembly lines of one product); otherwise the
        # number is taken as a bare MES order name
        work = self.env['sn.wsd.eip.work.order'].sudo().search([
            ('company_id', '=', self.env.company.id),
            ('wo_no', '=', number),
        ], limit=1)
        orders = work.mes_order_id | work.mes_order_ids
        History = self.env['sn.wsd.serial.operation.history'].sudo()
        histories = History.search(
            [('mes_order_id', 'in', orders.ids)] if orders
            else [('mes_order_id.name', '=', number)])
        bindings = self.env['sn.wsd.serial.binding'].sudo().search([
            ('bound_serial_identity_id', 'in',
             histories.serial_identity_id.ids),
            ('binding_type', '=', 'nameplate'),
        ])
        if not bindings:
            raise UserError(_(
                'No nameplate binding was found for work order "%s".',
                number))
        Pack = self.env['sn.wsd.eip.pack.record'].sudo()
        collected = Pack.search_count(
            [('binding_id', 'in', bindings.ids)])
        records = Pack._eip_capture_from_bindings(bindings)
        # neither collected before nor created now: no production order
        # or no mapped spec family
        skipped = len(bindings) - collected - len(records)
        if not records:
            raise UserError(_(
                'None of the %(count)s nameplate bindings of work order '
                '"%(number)s" can be captured: they are already collected '
                'or their machines have no production order or no mapped '
                'spec family.',
                count=len(bindings), number=number))
        if skipped:
            message = _(
                '%(created)s packing-storage rows created; %(skipped)s '
                'binding(s) skipped (no production order or no mapped spec '
                'family).', created=len(records), skipped=skipped)
        else:
            message = _(
                '%(created)s packing-storage rows created.',
                created=len(records))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Packing Storage Records'),
            'res_model': 'sn.wsd.eip.pack.record',
            'view_mode': 'list,form',
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
            'effect': {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': message,
                    'sticky': False,
                },
            },
        }

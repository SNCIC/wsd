from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class QualityInspectionDisposition(models.Model):
    """NG-board disposition actions on OQC inspections (oqc-ng-disposition):
    re-test = retype the cells, rework = pull the board back to an
    operation, scrap = native scrap + cells to N/A. No new documents."""

    _inherit = 'sn.wsd.quality.inspection'

    x_full_inspection = fields.Boolean(
        string='Full Lot Inspection', copy=False,
        help='Rejected-lot switch: the inspection reopens and the feeding '
             'gate lets every remaining board through the inspection '
             'operation one by one.')

    # ------------------------------------------------------------------
    # Rework: pull an NG sample board back to a production operation
    # ------------------------------------------------------------------
    def action_rework_sn(self, serial_identity, route_operation, reason):
        """Move the board's in-progress position back to ``route_operation``
        and arm its rework voucher. The board then re-walks the route on
        its original MES order (no material picking) and, back at the
        inspection operation, its result cells re-spread for re-judgment."""
        self.ensure_one()
        if self.inspection_type != 'oqc' or not self.mes_order_id \
                or self.mes_order_id.x_manage_mode == 'report':
            raise UserError(_(
                'Rework applies to outgoing inspections of station-mode '
                'MES orders only.'))
        if self.state == 'done':
            raise UserError(_('This inspection is already closed.'))
        if serial_identity not in self.x_fai_serial_ids:
            raise ValidationError(_(
                '"%s" is not one of this round\'s picked products.',
                serial_identity.name))
        has_ng = serial_identity in self.x_oqc_ng_serial_ids or any(
            cell.result == 'fail'
            for cell in self.cell_ids
            if cell.serial_identity_id == serial_identity)
        if not has_ng:
            raise ValidationError(_(
                'SN %s carries no failed result: only NG boards can be '
                'sent back through rework.', serial_identity.name))
        if not (reason or '').strip():
            raise ValidationError(_('Describe the rework reason.'))
        order = self.mes_order_id
        if route_operation.mes_order_id != order:
            raise ValidationError(_(
                'The rework operation must belong to MES order %s.',
                order.name))

        Wip = self.env['sn.wsd.serial.wip']
        wip = Wip.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', order.id),
        ], limit=1)
        if wip:
            wip.sudo().unlink()
        now = fields.Datetime.now()
        enter_vals = {
            'serial_identity_id': serial_identity.id,
            'mes_order_id': order.id,
            'route_operation_id': route_operation.id,
        }
        Wip.create(dict(enter_vals, in_date=now, company_id=order.company_id.id))
        # 立行口径同进站（pass-history-on-enter）：拨回即视为重新进站，
        # 后续出站回填该行（x_is_rework 由 _prepare_leave_history_vals 打标）
        self.env['sn.wsd.serial.operation.history'].sudo().create(
            dict(enter_vals, result='in_progress', in_date=now))
        serial_identity.x_rework_inspection_id = self.id
        serial_identity.x_rework_count += 1
        self.message_post(body=_(
            'Rework: SN %(sn)s pulled back to operation %(op)s '
            '(attempt %(attempt)s). Reason: %(reason)s',
            sn=serial_identity.name, op=route_operation.display_label,
            attempt=serial_identity.x_rework_count,
            reason=(reason or '').strip()))
        return True

    def _oqc_rework_pending_count(self):
        self.ensure_one()
        return self.env['sn.wsd.serial.identity'].search_count([
            ('x_rework_inspection_id', '=', self.id)])

    # ------------------------------------------------------------------
    # Rejected-lot switch: reopen and let every board through the gate
    # ------------------------------------------------------------------
    def action_start_full_inspection(self):
        self.ensure_one()
        if self.inspection_type != 'oqc' or self.state != 'done' \
                or self.result in ('pass', 'concession'):
            raise UserError(_(
                'Full-lot inspection starts from a rejected outgoing '
                'inspection.'))
        self.x_full_inspection = True
        return self.action_reset_open()


class MesOrderReworkMark(models.Model):
    """Rework boards leave a mark on their re-walked pass rows so the
    ledger and reports can tell them from first-pass production."""

    _inherit = 'sn.wsd.mes.order'

    def _prepare_leave_history_vals(self, serial_identity, route_operation,
                                    wip, result, scrap_reason=False,
                                    ng_defect=False, operator_code=False,
                                    workcenter=False):
        vals = super()._prepare_leave_history_vals(
            serial_identity, route_operation, wip, result,
            scrap_reason=scrap_reason, ng_defect=ng_defect,
            operator_code=operator_code, workcenter=workcenter)
        if serial_identity.x_rework_inspection_id:
            vals['x_is_rework'] = True
        return vals

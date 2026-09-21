"""Batch station pass (批量过站 / 行政过站) service layer.

A deliberate, logged bypass of ONE mid-route operation for a batch of
SNs already in progress on a station-mode MES order: boards keep flowing
when an operation temporarily cannot (or need not) process them. The
pass reuses the one-scan kernel semantics -- a board parked at the
target operation completes it, a board parked upstream is pulled through
(arrival pull) -- so every existing gate (freeze, pass-count, FAI/OQC)
still fires. The whole batch is one transaction: any failure rolls the
entire batch back and names the offending SN."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .batch_pass_log import BATCH_PASS_REASONS


class MesOrderBatchPass(models.Model):
    _inherit = 'sn.wsd.mes.order'

    x_batch_pass_count = fields.Integer(
        string='Batch Pass Count', compute='_compute_x_batch_pass_count',
        help='Number of batch station passes recorded on this order.',
    )

    def _compute_x_batch_pass_count(self):
        Log = self.env['sn.wsd.batch.pass.log']
        for order in self:
            order.x_batch_pass_count = Log.search_count(
                [('mes_order_id', '=', order.id)])

    # ------------------------------------------------------------------
    # restrictions (the four no-entry slots) and precheck
    # ------------------------------------------------------------------
    def _batch_pass_gate_checks(self, route_operation):
        """Hard restrictions raised before anything is written. Extended
        by sn_wsd_quality to refuse operations hit by an FAI scheme (the
        FAI gate only guards the feeding station, a mid-route first
        article has no gate of its own)."""
        self.ensure_one()
        if self.x_manage_mode != 'station':
            raise ValidationError(_(
                'Batch station pass is only available for station-mode MES '
                'orders.'))
        if route_operation.mes_order_id != self:
            raise ValidationError(_(
                'Operation %(op)s does not belong to MES order %(order)s.',
                op=route_operation.display_label, order=self.name))
        if route_operation.x_allow_entry:
            raise ValidationError(_(
                'Operation %(op)s is a feeding (start) operation: batch '
                'pass would forge input counts. It is not allowed.',
                op=route_operation.display_label))
        if route_operation.x_allow_exit:
            raise ValidationError(_(
                'Operation %(op)s is the end operation: batch pass would '
                'forge output quantity and trigger the auto-close. It is '
                'not allowed.',
                op=route_operation.display_label))
        if self.x_mes_route_id.x_material_operation_id == route_operation:
            raise ValidationError(_(
                'Operation %(op)s is the material operation: batch pass '
                'would forge SMT consumption records and skew the '
                'backflush. It is not allowed.',
                op=route_operation.display_label))

    def _batch_pass_block_reason(self, serial_identity, route_operation):
        """Why this SN cannot be batch-passed right now, or False when it
        can. Mirrors the same conditions the execution gates enforce (the
        execution stays the final authority); sn_wsd_repair extends it
        with the quality-freeze check."""
        self.ensure_one()
        Wip = self.env['sn.wsd.serial.wip']
        wip = Wip.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ], limit=1)
        if not wip:
            return _('not in progress on this order')
        if wip.route_operation_id != route_operation and \
                route_operation not in self._batch_pass_downstream_ops(
                    wip.route_operation_id):
            return _('parked at or past the target operation')
        History = self.env['sn.wsd.serial.operation.history']
        passes = History.search_count([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
            ('route_operation_id', '=', route_operation.id),
            ('result', 'in', ('ok', 'ng')),
        ])
        cap = 1 if route_operation.x_allow_exit \
            else route_operation.operation_id.x_max_test_count
        if passes >= cap:
            return _(
                'pass limit reached (%(limit)s) at %(op)s',
                limit=cap, op=route_operation.display_label)
        return False

    def _batch_pass_downstream_ops(self, route_operation):
        """Transitive successors of an operation on this order's route
        (used to tell 'parked upstream of the target' from 'already past
        it')."""
        self.ensure_one()
        seen = set()
        frontier = route_operation.successor_ids
        while frontier:
            nxt = frontier - self.x_mes_route_id.operation_ids.browse(seen)
            seen.update(nxt.ids)
            frontier = nxt.mapped('successor_ids')
        return self.x_mes_route_id.operation_ids.browse(seen)

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    def action_batch_pass_station(self, serial_ids, route_operation,
                                  reason, note=False):
        """Batch-pass ``serial_ids`` through ``route_operation`` with an
        administrative OK. One transaction for the whole batch: any gate
        failure rolls everything back and names the SN. Returns a receipt
        dict for the caller to display."""
        self.ensure_one()
        if not self.env.user.has_group('mrp.group_mrp_manager'):
            raise ValidationError(_(
                'Only manufacturing managers can batch-pass stations.'))
        if reason not in dict(BATCH_PASS_REASONS):
            raise ValidationError(_('Pick a batch pass reason.'))
        self._batch_pass_gate_checks(route_operation)
        serials = self.env['sn.wsd.serial.identity'].browse(
            [sid for sid in serial_ids if sid])
        if not serials:
            raise ValidationError(_('Select at least one SN.'))
        log = self.env['sn.wsd.batch.pass.log'].sudo().create({
            'mes_order_id': self.id,
            'route_operation_id': route_operation.id,
            'reason': reason,
            'note': note or False,
            'serial_identity_ids': [(6, 0, serials.ids)],
            'company_id': self.company_id.id,
        })
        marked = self.with_context(
            sn_wsd_batch_pass_log_id=log.id,
            sn_wsd_batch_pass_target_id=route_operation.id,
        )
        for serial in serials:
            marked._batch_pass_one(serial, route_operation)
        return {
            'passed': len(serials),
            'log_id': log.id,
            'order_name': self.name,
            'operation': route_operation.display_label,
        }

    def _batch_pass_one(self, serial_identity, route_operation):
        """Route one SN through the batch pass, one-scan-kernel style:
        a board parked at the target completes it; a board parked
        upstream is pulled forward (its parked operation completes OK,
        then it enters the target). The OK verdict on the target row is
        stamped with the batch log marker via context; the pulled
        upstream row stays unmarked (its work was real). Afterwards the
        board parks at the successor, exactly like a physical scan."""
        self.ensure_one()
        Wip = self.env['sn.wsd.serial.wip']
        wip = Wip.search([
            ('serial_identity_id', '=', serial_identity.id),
            ('mes_order_id', '=', self.id),
        ], limit=1)
        if not wip:
            raise ValidationError(_(
                'SN %(sn)s is not in progress on MES order %(order)s.',
                sn=serial_identity.name, order=self.name))
        if wip.route_operation_id != route_operation:
            if route_operation not in self._batch_pass_downstream_ops(
                    wip.route_operation_id):
                raise ValidationError(_(
                    'SN %(sn)s is parked at %(parked)s, which is not '
                    'upstream of %(op)s.',
                    sn=serial_identity.name,
                    parked=wip.route_operation_id.display_label,
                    op=route_operation.display_label))
            # arrival pull: the parked operation hands the board over
            self.leave_station(serial_identity, 'ok')
            self.enter_station(serial_identity, route_operation)
        # target verdict -- marked by _prepare_leave_history_vals via
        # the context keys set in action_batch_pass_station
        self.leave_station(serial_identity, 'ok')
        successor = self._station_successors(route_operation)[:1]
        if successor:
            self.enter_station(
                serial_identity, successor,
                workcenter=successor.workcenter_id)

    # ------------------------------------------------------------------
    # history row marker (consumes the context keys above)
    # ------------------------------------------------------------------
    def _prepare_leave_history_vals(self, serial_identity, route_operation,
                                    wip, result, scrap_reason=False,
                                    ng_defect=False, operator_code=False):
        vals = super()._prepare_leave_history_vals(
            serial_identity, route_operation, wip, result,
            scrap_reason=scrap_reason, ng_defect=ng_defect,
            operator_code=operator_code)
        log_id = self.env.context.get('sn_wsd_batch_pass_log_id')
        if log_id and route_operation.id == \
                self.env.context.get('sn_wsd_batch_pass_target_id'):
            vals['x_batch_pass_log_id'] = log_id
        return vals

    def action_open_batch_pass_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Batch Station Passes'),
            'res_model': 'sn.wsd.batch.pass.log',
            'view_mode': 'list,form',
            'domain': [('mes_order_id', '=', self.id)],
            'context': {'default_mes_order_id': self.id},
        }


class MesOrderRouteOperationBatchPass(models.Model):
    _inherit = 'sn.wsd.mes.order.route.operation'

    def action_open_batch_pass_wizard(self):
        """Row-level entry on the MES order form (工序数量 page): open the
        shared confirmation dialog pre-filled with this operation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Batch Station Pass'),
            'res_model': 'sn.wsd.batch.pass.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_mes_order_id': self.mes_order_id.id,
                'default_route_operation_id': self.id,
                'default_workcenter_id': self.workcenter_id.id or False,
            },
        }

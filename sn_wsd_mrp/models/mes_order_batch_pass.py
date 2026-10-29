"""Batch station pass (批量过站 / 行政过站) service layer.

A deliberate, logged bypass of ONE mid-route operation for a batch of
SNs whose previous operation is already OK: boards keep flowing when an
operation temporarily cannot (or need not) process them. The pass
records the target operation's own row (strict one-scan-per-station:
the administrative OK replaces that single scan, it never bridges
several operations), so every existing gate (freeze, pass-count,
FAI/OQC) still fires. The whole batch is one transaction: any failure
rolls the entire batch back and names the offending SN."""
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
        with the quality-freeze check.

        Strict one-scan-per-station: a board can only be batch-passed
        through the operation right after the one it currently sits at --
        the administrative OK replaces that single scan, it never bridges
        several operations."""
        self.ensure_one()
        current = self.serial_current_route_operations(
            [serial_identity.id]).get(serial_identity.id)
        if not current:
            return _('not fed into this order')
        current_op = current.route_operation_id
        if current_op == route_operation:
            return _(
                'already at %(op)s', op=route_operation.display_label)
        if route_operation not in self._station_successors(current_op):
            return _(
                'not the next operation after %(op)s',
                op=current_op.display_label)
        if current.result == 'in_progress':
            return _(
                'decision pending at %(op)s', op=current_op.display_label)
        if current.result != 'ok':
            return _(
                'last pass at %(op)s was %(result)s',
                op=current_op.display_label, result=current.result)
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
        """Route one SN through the batch pass: the administrative OK
        replaces the ONE scan of the target operation (strict
        one-scan-per-station). The board must sit at the operation right
        before the target; the OK verdict is stamped with the batch log
        marker via context. Nothing is parked at the successor and no
        upstream operation is pulled -- the board simply becomes the
        target's latest pass."""
        self.ensure_one()
        block = self._batch_pass_block_reason(serial_identity, route_operation)
        if block:
            raise ValidationError(_(
                'SN %(sn)s cannot be batch-passed through %(op)s: %(reason)s',
                sn=serial_identity.name,
                op=route_operation.display_label, reason=block))
        self.enter_station(serial_identity, route_operation)
        self.leave_station(serial_identity, 'ok')

    # ------------------------------------------------------------------
    # history row marker (consumes the context keys above)
    # ------------------------------------------------------------------
    def _prepare_leave_history_vals(self, serial_identity, route_operation,
                                    wip, result, scrap_reason=False,
                                    ng_defect=False, operator_code=False,
                                    workcenter=False):
        vals = super()._prepare_leave_history_vals(
            serial_identity, route_operation, wip, result,
            scrap_reason=scrap_reason, ng_defect=ng_defect,
            operator_code=operator_code, workcenter=workcenter)
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

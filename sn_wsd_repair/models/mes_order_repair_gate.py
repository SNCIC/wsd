from odoo import _, models
from odoo.exceptions import ValidationError

# Terminal states: a repair order in any other state freezes the SN.
REPAIR_ACTIVE_STATES = ('draft', 'reported', 'repairing')
ISSUE_OPEN_STATES = ('open', 'analysis', 'repairing', 'verified')


class MesOrderRepairGate(models.Model):
    _inherit = 'sn.wsd.mes.order'

    def enter_station(self, serial_identity, route_operation, workcenter=False):
        """Quality freeze gate on station entry: an SN with an open repair
        order or an open quality issue stays out of the flow until the
        document reaches a terminal state. A closed repair order supplies
        the pass-count cutoff (its repair_time) and, when set on this
        order, the authorized re-entry seed (its re-entry operation):
        counters restart and the SN must re-walk from that point."""
        freeze_source = self._sn_quality_freeze_source(serial_identity)
        if freeze_source:
            raise ValidationError(_(
                'SN %(sn)s is frozen by %(kind)s %(ref)s in state %(state)s; '
                'close it before feeding the SN back into the flow.',
                sn=serial_identity.name,
                kind=freeze_source['kind'], ref=freeze_source['ref'],
                state=freeze_source['state']))
        context = dict(self.env.context)
        repair = self._sn_last_closed_repair(serial_identity)
        if repair and repair.repair_time:
            context['sn_wsd_pass_cutoff'] = repair.repair_time
            seed = repair.repair_entry_route_operation_id
            if seed and seed.mes_order_id == self:
                context['sn_wsd_repair_seed_ids'] = [seed.id]
        return super(
            MesOrderRepairGate, self.with_context(context),
        ).enter_station(serial_identity, route_operation, workcenter=workcenter)

    def leave_station(self, serial_identity, result, scrap_reason=False,
                      ng_defect=False, operator_code=False):
        """Frozen SNs may not continue downstream: an OK leave is refused
        until the repair order / quality issue is closed. NG and scrap
        leaves stay open -- they are the offline paths to repair/scrap."""
        if result == 'ok':
            freeze_source = self._sn_quality_freeze_source(serial_identity)
            if freeze_source:
                raise ValidationError(_(
                    'SN %(sn)s is frozen by %(kind)s %(ref)s in state '
                    '%(state)s; it cannot leave with OK before the issue is '
                    'resolved.',
                    sn=serial_identity.name,
                    kind=freeze_source['kind'], ref=freeze_source['ref'],
                    state=freeze_source['state']))
        return super().leave_station(
            serial_identity, result, scrap_reason=scrap_reason,
            ng_defect=ng_defect, operator_code=operator_code)

    def _sn_quality_freeze_source(self, serial_identity):
        """First freeze source of the SN: an active repair order or an open
        quality issue. Returns {'kind', 'ref', 'state'} or False."""
        repair = self.env['sn.wsd.repair.order'].search([
            ('serial_identity_id', '=', serial_identity.id),
            ('company_id', '=', serial_identity.company_id.id),
            ('state', 'in', REPAIR_ACTIVE_STATES),
        ], order='id desc', limit=1)
        if repair:
            state_label = dict(
                repair._fields['state'].selection
            ).get(repair.state, repair.state)
            return {'kind': _('repair order'), 'ref': repair.name,
                    'state': state_label}
        issue = self.env['sn.wsd.quality.issue'].search([
            ('serial_identity_id', '=', serial_identity.id),
            ('company_id', '=', serial_identity.company_id.id),
            ('state', 'in', ISSUE_OPEN_STATES),
        ], order='id desc', limit=1)
        if issue:
            state_label = dict(
                issue._fields['state'].selection
            ).get(issue.state, issue.state)
            return {'kind': _('quality issue'), 'ref': issue.name,
                    'state': state_label}
        return False

    def _sn_last_closed_repair(self, serial_identity):
        """Latest successfully closed repair order of the SN: its repair_time
        is the pass-count / reachability cutoff, its re-entry operation the
        authorized station seed."""
        return self.env['sn.wsd.repair.order'].search([
            ('serial_identity_id', '=', serial_identity.id),
            ('company_id', '=', serial_identity.company_id.id),
            ('state', '=', 'done'),
            ('result', '=', 'ok'),
        ], order='repair_time desc, id desc', limit=1)

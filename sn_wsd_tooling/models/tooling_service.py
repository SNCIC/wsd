from odoo import _, api, models
from odoo.exceptions import UserError


class SnToolingService(models.AbstractModel):
    """PDA service layer for tooling: scan SN in, translated message out.

    Every method shares the model methods used by the UI buttons, so guards
    and state transitions stay identical on both sides.
    """

    _name = 'sn.tooling.service'
    _description = 'Tooling PDA Service'

    @api.model
    def _resolve(self, sn):
        tooling = self.env['sn.tooling'].search(
            [('sn', '=', sn), ('company_id', '=', self.env.company.id)], limit=1)
        if not tooling:
            raise UserError(_('Tooling SN %s does not exist.', sn))
        return tooling

    @api.model
    def resolve(self, sn):
        tooling = self._resolve(sn)
        return {
            'sn': tooling.sn,
            'template': tooling.template_id.display_name,
            'type': tooling.type_id.name or '',
            'state': tooling.state,
            'maintenance_status': tooling.maintenance_status or 'normal',
            'total_usage_count': tooling.total_usage_count,
            'cycle_usage_count': tooling.cycle_usage_count,
        }

    @api.model
    def issue(self, sn):
        tooling = self._resolve(sn)
        tooling.action_issue()
        return _('Tooling %s issued.', tooling.sn)

    @api.model
    def return_(self, sn):
        tooling = self._resolve(sn)
        tooling.action_return()
        return _('Tooling %s returned.', tooling.sn)

    @api.model
    def online(self, sn):
        tooling = self._resolve(sn)
        tooling.action_online()
        return _('Tooling %s put online.', tooling.sn)

    @api.model
    def offline(self, sn):
        tooling = self._resolve(sn)
        tooling.action_offline()
        return _('Tooling %s taken offline.', tooling.sn)

    @api.model
    def maintain_start(self, sn):
        tooling = self._resolve(sn)
        tooling.action_maintain_start()
        return _('Tooling %s maintenance started.', tooling.sn)

    @api.model
    def maintain_done(self, sn, results=None, params=None):
        """results: list of dicts {name, result, note} for the maintenance items."""
        tooling = self._resolve(sn)
        line_vals = [(0, 0, line) for line in (results or [])]
        tooling.action_maintain_done(line_vals=line_vals, params=params or {})
        return _('Tooling %s maintenance done.', tooling.sn)

    @api.model
    def repair_start(self, sn, fault):
        tooling = self._resolve(sn)
        tooling.action_repair_start(fault)
        return _('Tooling %s repair started.', tooling.sn)

    @api.model
    def repair_done(self, sn, outcome, reason=None):
        """outcome: 'fixed' back to idle, 'scrap' goes to scrapped (reason required)."""
        tooling = self._resolve(sn)
        tooling.action_repair_done(outcome, reason=reason)
        if outcome == 'scrap':
            return _('Tooling %s scrapped after repair.', tooling.sn)
        return _('Tooling %s repaired.', tooling.sn)

    @api.model
    def disable(self, sn, reason):
        tooling = self._resolve(sn)
        tooling.action_disable(reason)
        return _('Tooling %s disabled.', tooling.sn)

    @api.model
    def enable(self, sn):
        tooling = self._resolve(sn)
        tooling.action_enable()
        return _('Tooling %s enabled.', tooling.sn)

    @api.model
    def scrap(self, sn, reason):
        tooling = self._resolve(sn)
        tooling.action_scrap(reason)
        return _('Tooling %s scrapped.', tooling.sn)

    @api.model
    def register_usage(self, sn, qty):
        tooling = self._resolve(sn)
        tooling.register_usage(qty)
        return _('Tooling %s: registered %s usages.', tooling.sn, qty)

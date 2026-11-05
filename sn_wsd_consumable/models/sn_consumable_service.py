from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SnConsumableService(models.AbstractModel):
    """Scan-driven entry points for PDA integration.

    All methods take the scanned consumable SN (and scan/plain values only),
    run the same guards as the UI actions and return a human readable result
    message. The PDA frontend only needs to call these methods.
    """
    _name = 'sn.consumable.service'
    _description = 'Consumable PDA Service'

    @api.model
    def _resolve_info(self, sn):
        info = self.env['sn.consumable.info'].search([
            ('sn', '=', sn),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not info:
            raise UserError(_('The consumable SN %s does not exist.', sn))
        return info

    @api.model
    def _resolve_mes_order(self, mes_order):
        if not mes_order:
            raise UserError(_('The MES order is required.'))
        MesOrder = self.env['sn.wsd.mes.order']
        if isinstance(mes_order, int):
            order = MesOrder.browse(mes_order)
            if not order.exists():
                raise UserError(_('The MES order %s does not exist.', mes_order))
            return order
        order = MesOrder.search([('name', '=', str(mes_order))], limit=1)
        if not order:
            raise UserError(_('The MES order %s does not exist.', mes_order))
        return order

    @api.model
    def resolve(self, sn):
        info = self._resolve_info(sn)
        return {
            'id': info.id,
            'sn': info.sn,
            'template_code': info.template_code,
            'type': info.type_id.name or '',
            'aux_state': info.aux_state,
            'expiry_date': fields.Date.to_string(info.expiry_date) if info.expiry_date else False,
        }

    @api.model
    def issue(self, sn):
        self._resolve_info(sn).action_issue()
        return _('Consumable %s issued.', sn)

    @api.model
    def return_(self, sn):
        self._resolve_info(sn).action_return()
        return _('Consumable %s returned.', sn)

    @api.model
    def thaw_start(self, sn):
        self._resolve_info(sn).action_thaw_start()
        return _('Thawing started for %s.', sn)

    @api.model
    def thaw_end(self, sn):
        self._resolve_info(sn).action_thaw_end()
        return _('Thawing finished for %s.', sn)

    @api.model
    def stir_start(self, sn):
        self._resolve_info(sn).action_stir_start()
        return _('Stirring started for %s.', sn)

    @api.model
    def stir_end(self, sn):
        self._resolve_info(sn).action_stir_end()
        return _('Stirring finished for %s.', sn)

    @api.model
    def load(self, sn, mes_order):
        order = self._resolve_mes_order(mes_order)
        self._resolve_info(sn).action_load(order)
        return _('%s loaded for %s.', sn, order.display_name)

    @api.model
    def unload(self, sn):
        self._resolve_info(sn).action_unload()
        return _('%s unloaded.', sn)

    @api.model
    def exhaust(self, sn):
        self._resolve_info(sn).action_exhaust()
        return _('%s exhausted.', sn)

    @api.model
    def scrap(self, sn, reason=False):
        self._resolve_info(sn).action_scrap(reason=reason)
        return _('%s scrapped.', sn)

    @api.model
    def disable(self, sn):
        self._resolve_info(sn).action_disable()
        return _('%s disabled.', sn)

    @api.model
    def enable(self, sn):
        self._resolve_info(sn).action_enable()
        return _('%s enabled.', sn)

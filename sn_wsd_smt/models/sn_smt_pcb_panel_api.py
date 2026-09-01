from odoo import _, api, models
from odoo.exceptions import ValidationError


class SnSmtPcbPanelApi(models.AbstractModel):
    """Business service behind the SMT PCB panel HTTP API.

    The controller (sn_ssd_smt/controllers/sn_smt_pcb_panel_controller.py)
    is a thin layer over these methods; validation failures are returned as
    ``{'code': 400, 'message': ...}`` instead of raising so external callers
    always receive a structured answer.
    """
    _name = 'sn.smt.pcb.panel.api'
    _description = 'SMT PCB Panel API Service'

    # ------------------------------------------------------------------
    # F-001 panel creation
    # ------------------------------------------------------------------
    @api.model
    def api_panel_add(self, params):
        params = params or {}
        product_no = (params.get('productNo') or '').strip()
        if not product_no:
            return {'code': 400, 'message': _('Product No is required.')}
        quantity = params.get('quantity') or 1
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return {'code': 400, 'message': _('Panel quantity must be an integer.')}
        if quantity < 1:
            return {'code': 400, 'message': _('Panel quantity must be positive.')}
        bindings = params.get('bindings') or []
        if not bindings:
            return {'code': 400, 'message': _('Bindings are required.')}

        Serial = self.env['sn.wsd.serial.identity']
        for index, binding in enumerate(bindings, start=1):
            pro_sn = (binding.get('proSn') or '').strip()
            if not pro_sn:
                return {'code': 400, 'message': _(
                    'Record #%(index)s: product SN is empty.',
                    index=index)}
            serial = Serial.search([
                ('name', '=', pro_sn),
                '|',
                ('company_id', '=', False),
                ('company_id', 'in', self.env.companies.ids),
            ], limit=1)
            if not serial:
                return {'code': 400, 'message': _(
                    'Record #%(index)s: product SN [%(sn)s] does not exist.',
                    index=index, sn=pro_sn)}

        production = self.env['mrp.production'].search(
            [('name', '=', product_no)], limit=1)
        try:
            self.env['sn.smt.pcb.panel']._create_from_api(
                {
                    'productNo': product_no,
                    'quantity': quantity,
                    'pcb_item_sn': (params.get('pcbItemSn') or '').strip(),
                    'bindings': bindings,
                },
                production_id=production.id if production else None,
            )
        except ValidationError as exc:
            return {'code': 400, 'message': str(exc)}
        return {'code': 200, 'message': _('Saved successfully.')}

    # ------------------------------------------------------------------
    # F-002 panel query
    # ------------------------------------------------------------------
    @api.model
    def api_panel_query(self, params):
        params = params or {}
        Panel = self.env['sn.smt.pcb.panel']
        pro_sn = (params.get('proSn') or '').strip()
        product_no = (params.get('productNo') or '').strip()
        if pro_sn:
            panels = Panel.search([('board_ids.pro_sn', '=', pro_sn)])
        elif product_no:
            panels = Panel.search([('product_no', '=', product_no)])
        else:
            return {'code': 400, 'message': _(
                'Provide productNo or proSn to query.')}
        return {
            'code': 200,
            'message': _('Query successful.'),
            'data': {
                'panels': [panel.to_api_response() for panel in panels],
                'total': len(panels),
            },
        }

    @api.model
    def api_panel_detail(self, panel_id):
        panel = self.env['sn.smt.pcb.panel'].browse(panel_id).exists()
        if not panel:
            return {'code': 400, 'message': _(
                'Panel %s does not exist.', panel_id)}
        return {
            'code': 200,
            'message': _('Query successful.'),
            'data': panel.to_api_response(),
        }

    @api.model
    def api_panel_delete(self, panel_id):
        panel = self.env['sn.smt.pcb.panel'].browse(panel_id).exists()
        if not panel:
            return {'code': 400, 'message': _(
                'Panel %s does not exist.', panel_id)}
        panel.unlink()
        return {'code': 200, 'message': _('Deleted successfully.')}

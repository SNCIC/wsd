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
    # organization resolution (same contract as sn.wsd.api.service)
    # ------------------------------------------------------------------
    @api.model
    def _company_or_error(self, params):
        """M_DATA_AUTH -> (company, None) or (None, graded error dict)."""
        code = (params.get('M_DATA_AUTH') or '').strip()
        if not code:
            return None, {'code': 400, 'message': _('Organization is empty.')}
        company = self.env['res.company'].search(
            [('company_registry', '=', code)], limit=1)
        if not company:
            return None, {
                'code': 404,
                'message': _('Organization %s does not exist.', code)}
        return company, None

    # ------------------------------------------------------------------
    # F-001 panel creation
    # ------------------------------------------------------------------
    @api.model
    def api_panel_add(self, params):
        params = params or {}
        company, error = self._company_or_error(params)
        if error:
            return error
        self = self.with_company(company)
        product_no = (params.get('productNo') or '').strip()
        if not product_no:
            return {'code': 400, 'message': _('Product No is required.')}
        quantity = params.get('quantity') or 1
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return {'code': 400, 'message': _('Panel quantity must be an integer.')}
        if quantity < 1:
            return {'code': 422, 'message': _('Panel quantity must be positive.')}
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
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            if not serial:
                return {'code': 404, 'message': _(
                    'Record #%(index)s: product SN [%(sn)s] does not exist.',
                    index=index, sn=pro_sn)}

        production = self.env['mrp.production'].search([
            ('name', '=', product_no),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
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
        company, error = self._company_or_error(params)
        if error:
            return error
        self = self.with_company(company)
        Panel = self.env['sn.smt.pcb.panel']
        pro_sn = (params.get('proSn') or '').strip()
        product_no = (params.get('productNo') or '').strip()
        company_domain = [('company_id', '=', self.env.company.id)]
        if pro_sn:
            panels = Panel.search(
                company_domain + [('board_ids.pro_sn', '=', pro_sn)])
        elif product_no:
            panels = Panel.search(
                company_domain + [('product_no', '=', product_no)])
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

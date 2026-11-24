"""EIP production-data collect interface registry.

One row per gateway-facing endpoint: each production-data spec
(electricity meters 1xxx, collection devices 2xxx) ships one interface
per data kind and the gateway fetches each by its own URL
(/api/eip/collect/<code>). The material-inspection, packing/shipping
and report interfaces are seeded inactive: their capture sources are
not implemented this round, the registry rows just reserve the URLs.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class EipCollectError(Exception):
    """Protocol-level failure of a gateway fetch; the controller turns
    it into a status-1 envelope."""


class EipCollectInterface(models.Model):
    _name = 'sn.wsd.eip.collect.interface'
    _description = 'EIP Collect Interface'
    _order = 'code, id'
    _rec_name = 'code'

    code = fields.Char(
        string='Info Type Code', required=True, index=True,
        help='Interface key of the URL /api/eip/collect/<code>: the spec '
             'INFO_TYPE_CODE (1xxx electricity meters, 2xxx collection '
             'devices); the report interfaces use synthetic keys.')
    family = fields.Selection(
        selection=[
            ('meter', 'Electricity Meter'),
            ('collector', 'Collection Device'),
        ],
        string='Spec Family', required=True, index=True,
        help='Which production-data spec the interface belongs to.')
    name = fields.Char(string='Name', required=True)
    method = fields.Selection(
        selection=[('post', 'POST'), ('get', 'GET')],
        string='Method', required=True, default='post')
    active = fields.Boolean(default=True, index=True)
    note = fields.Char(string='Notes')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The collect interface code must be unique.',
    )

    @api.model
    def _eip_collect_interface(self, code):
        """Registry row of ``code`` (disabled rows included), or an
        empty recordset."""
        return self.with_context(active_test=False).search(
            [('code', '=', code)], limit=1)

    @api.model
    def _eip_main_company(self):
        """auth='none' carries no user/company: single-factory
        deployment stamps the first company (device-endpoint
        precedent)."""
        return self.env['res.company'].sudo().search(
            [], order='id asc', limit=1)

    @api.model
    def _eip_serve(self, code, amount):
        """Answer one gateway fetch of ``code``: resolve the registry
        row and the supplier identity, claim up to ``amount`` qualified
        snapshots FIFO and deliver them. Returns a dict with the
        supplier code and the payload list; raises EipCollectError on
        protocol failures (before anything is claimed)."""
        interface = self._eip_collect_interface(code)
        if not interface or not interface.active:
            raise EipCollectError(
                'unknown or disabled collect interface: %s' % code)
        company = self._eip_main_company()
        config = self.env['sn.wsd.eip.config'].sudo().search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], limit=1)
        if not config:
            raise EipCollectError('no active EIP integration config')
        claimed = self.env['sn.wsd.eip.collect.outbox']._eip_claim(
            code, amount)
        return {
            'supplier_code': config.supplier_code,
            'data': [row.payload or {} for row in claimed],
        }

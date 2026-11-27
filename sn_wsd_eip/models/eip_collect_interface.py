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


# raw-material inspection codes: served from sn.wsd.eip.raw.record
RAW_INTERFACE_CODES = frozenset(
    {'1012', '1013', '1014', '1015', '1016', '1017', '1018',
     '2011', '2012', '2013', '2014'})


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
        string='Device Category', required=True, index=True,
        help='Which production-data spec the interface belongs to.')
    # platform-issued interface title: translated so the ledgers
    # and the work-order overview show it in the user language
    name = fields.Char(string='Name', required=True, translate=True)
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
        if code in RAW_INTERFACE_CODES:
            claimed = self.env['sn.wsd.eip.raw.record']._eip_claim(
                code, amount)
            return {'supplier_code': config.supplier_code,
                    'data': claimed._eip_raw_payloads()}
        if code in ('1090', '2090', '1091', '2091'):
            # logistics documents serve directly from their own tables
            model = 'sn.wsd.eip.pack.record' if code in ('1090', '2090')                 else 'sn.wsd.eip.ship.record'
            claimed = self.env[model]._eip_claim(code, amount)
            payloads = (claimed._eip_pack_payloads()
                        if code in ('1090', '2090')
                        else claimed._eip_ship_payloads())
            return {'supplier_code': config.supplier_code,
                    'data': payloads}
        if interface.method == 'get':
            if not config.collect_base_url:
                raise EipCollectError(
                    'collect base URL not configured: fill it under EIP '
                    'Configuration so the gateway can download the '
                    'report files')
            claimed = self.env['sn.wsd.eip.raw.report']._eip_claim(
                interface.family, amount)
            return {
                'supplier_code': config.supplier_code,
                'data': claimed._eip_report_payloads(config.collect_base_url),
            }
        claimed = self.env['sn.wsd.eip.collect.outbox']._eip_claim(
            code, amount)
        return {
            'supplier_code': config.supplier_code,
            'data': [row.payload or {} for row in claimed],
        }

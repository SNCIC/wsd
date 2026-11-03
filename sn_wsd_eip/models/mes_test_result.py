import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class MesTestResultEip(models.Model):
    """Phase-2 hook (1/2): the report channel lands its test result
    AFTER the pass transaction (scan-pass / AOI call the kernel first,
    ingest second). Creating the test result links it onto the pending
    collection row born at the pass and refreshes the device chain
    (report device first). Value extraction also runs here, but the
    detail items land later -- the detail create hook re-runs it."""
    _inherit = 'sn.wsd.mes.test.result'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            self.env['sn.wsd.eip.pass.record'].sudo(
            )._enrich_from_test_result(records)
        except Exception as exc:  # noqa: BLE001 -- deliberate tolerance
            _logger.warning('EIP enrichment failed: %s', exc)
        return records


class MesTestResultDetailEip(models.Model):
    """Phase-2 hook (2/2): ingest writes the detail items after the
    test result row, so bucket-1 extraction has to re-run here -- this
    is the actual last write of the report channel."""
    _inherit = 'sn.wsd.mes.test.result.detail'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            self.env['sn.wsd.eip.pass.record'].sudo(
            )._enrich_from_test_result(records.test_result_id)
        except Exception as exc:  # noqa: BLE001 -- deliberate tolerance
            _logger.warning('EIP enrichment failed: %s', exc)
        return records

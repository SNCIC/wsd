import logging

_logger = logging.getLogger(__name__)

# Orphan ir.model rows left behind by the 19.0.8.0.0 serial-registry
# unification (sn.wsd.internal.serial -> sn.wsd.serial.identity) and by the
# removed sn_wsd_print label-report models. No module code declares them any
# more, so Odoo warns "declared but cannot be loaded" at every start.
ORPHAN_MODELS = [
    'report.sn_wsd_print.report_incoming_material_label_zpl',
    'report.sn_wsd_print.report_internal_serial_label_zpl',
    'sn.wsd.internal.serial.generate.print.wizard',
    'sn.wsd.internal.serial',
]


def migrate(cr, version):
    if not version:
        return
    for model in ORPHAN_MODELS:
        # FK chains (ir_model_fields, ir_model_access, ir_model_relation,
        # ir_model_constraint, ir_rule, ...) are ON DELETE CASCADE, so a
        # single DELETE removes the model and all its metadata.
        cr.execute('DELETE FROM ir_model WHERE model = %s', [model])
        if cr.rowcount:
            _logger.info(
                'sn_wsd_mrp 19.0.9.0.3: removed orphan ir.model %s', model)

"""Generation layer: tolerant birth hooks on MES write paths.

Every hook is wrapped in try/except so an NQI failure NEVER breaks the
station-pass / binding transaction; missed rows are recovered by the
watermark cron worker (nqi_worker). Idempotency uses event anchors
(one mirror row per source event, unique constraint on the anchor), so
replayed events and cron/hook races collapse to a single row.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def _fmt(dt):
    return dt.strftime(DATETIME_FORMAT) if dt else ''


class NqiGenerationIdempotency(models.AbstractModel):
    """Shared helpers for the birth hooks."""
    _name = 'sn.wsd.nqi.generation.mixin'
    _description = 'NQI Generation Helpers'

    @api.model
    def _nqi_create_if_new(self, model_name, vals, key_field):
        """Create a row unless its event anchor already has one.

        Pre-filter by the (indexed, unique) anchor; the rare race is
        caught by the constraint itself via a savepoint, so concurrent
        creators collapse to exactly one row without raising outward.
        """
        target = self.env[model_name].sudo()
        existing = target.search([(key_field, '=', vals[key_field])], limit=1)
        if existing:
            return existing
        try:
            with self.env.cr.savepoint():
                return target.create(vals)
        except Exception as exc:  # noqa: BLE001 -- deliberate tolerance
            _logger.warning(
                'NQI birth skipped for %s %s: %s',
                model_name, vals.get(key_field), exc)
            return target.browse()

    @api.model
    def _nqi_birth_mounting_rows(self, model_name, records):
        """One process row per judged station pass, axis by product kind."""
        board = model_name == 'sn.wsd.nqi.fit.pcb.mounting'
        for record in records.sudo():
            order = record.mes_order_id
            sn = record.serial_identity_id
            if not order or not sn or not record.result:
                continue
            kind = order.product_id._nqi_product_kind()
            if board != (kind == 'board'):
                continue
            sequence = ''
            if record.route_operation_id:
                sequence = str(record.route_operation_id.sequence or '')
            values = {
                'company_id': record.company_id.id,
                'operation_history_id': record.id,
                'para_index': sequence,
                'operator_code': record.operator_code or '',
                'detect_date': _fmt(record.out_date or record.in_date),
            }
            values['pcb_code' if board else 'serial_no'] = sn.name
            self._nqi_create_if_new(model_name, values,
                                    'operation_history_id')


class NqiFitMeterInfoBirth(models.Model):
    _inherit = 'sn.wsd.nqi.fit.meter.info'

    operation_history_id = fields.Many2one(
        'sn.wsd.serial.operation.history', string='Output Pass History',
        index=True, ondelete='set null')

    _output_history_uniq = models.Constraint(
        'unique(company_id, operation_history_id)',
        'One mirror row per output pass event.')

    @api.model
    def _nqi_birth_from_history(self, records):
        """Asset rows born when a machine-kind SN passes its output op."""
        helpers = self.env['sn.wsd.nqi.generation.mixin']
        for record in records.sudo():
            order = record.mes_order_id
            if not order or record.result != 'ok':
                continue
            if (order.x_daily_output_operation_id
                    and record.route_operation_id
                    != order.x_daily_output_operation_id):
                continue
            if order.product_id._nqi_product_kind() != 'machine':
                continue
            sn = record.serial_identity_id
            if not sn:
                continue
            helpers._nqi_create_if_new(
                'sn.wsd.nqi.fit.meter.info',
                {
                    'company_id': record.company_id.id,
                    'operation_history_id': record.id,
                    'serial_no': sn.name,
                    'status': '1',
                },
                'operation_history_id')


class NqiFitMountingBirthBoard(models.Model):
    _inherit = 'sn.wsd.nqi.fit.pcb.mounting'

    operation_history_id = fields.Many2one(
        'sn.wsd.serial.operation.history', string='Pass History',
        index=True, ondelete='set null')

    _history_uniq = models.Constraint(
        'unique(company_id, operation_history_id)',
        'One mirror row per station pass event.')

    @api.model
    def _nqi_birth_mounting(self, records):
        self.env['sn.wsd.nqi.generation.mixin']._nqi_birth_mounting_rows(
            'sn.wsd.nqi.fit.pcb.mounting', records)


class NqiFitMountingBirthMachine(models.Model):
    _inherit = 'sn.wsd.nqi.fit.meter.mounting'

    operation_history_id = fields.Many2one(
        'sn.wsd.serial.operation.history', string='Pass History',
        index=True, ondelete='set null')

    _history_uniq = models.Constraint(
        'unique(company_id, operation_history_id)',
        'One mirror row per station pass event.')

    @api.model
    def _nqi_birth_mounting(self, records):
        self.env['sn.wsd.nqi.generation.mixin']._nqi_birth_mounting_rows(
            'sn.wsd.nqi.fit.meter.mounting', records)


class SerialOperationHistoryNqi(models.Model):
    _inherit = 'sn.wsd.serial.operation.history'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get('nqi_skip_birth'):
            return records
        try:
            self.env['sn.wsd.nqi.fit.meter.info'].sudo(
            )._nqi_birth_from_history(records)
            self.env['sn.wsd.nqi.fit.pcb.mounting'].sudo(
            )._nqi_birth_mounting(records)
            self.env['sn.wsd.nqi.fit.meter.mounting'].sudo(
            )._nqi_birth_mounting(records)
        except Exception as exc:  # noqa: BLE001 -- never break a pass
            _logger.warning('NQI station-pass birth failed: %s', exc)
        return records


class NqiFitBridgeBirth(models.Model):
    _inherit = 'sn.wsd.nqi.fit.pcb.serial.bind'

    binding_id = fields.Many2one(
        'sn.wsd.serial.binding', string='Serial Binding',
        index=True, ondelete='set null')

    _binding_uniq = models.Constraint(
        'unique(company_id, binding_id)',
        'One mirror row per serial binding event.')


class SerialBindingNqi(models.Model):
    _inherit = 'sn.wsd.serial.binding'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            helpers = self.env['sn.wsd.nqi.generation.mixin'].sudo()
            for record in records.sudo():
                if record.binding_type != 'machine':
                    continue
                board_sn = record.serial_identity_id
                machine_sn = record.bound_serial_identity_id
                if not board_sn or not machine_sn:
                    continue
                helpers._nqi_create_if_new(
                    'sn.wsd.nqi.fit.pcb.serial.bind',
                    {
                        'company_id': record.company_id.id,
                        'binding_id': record.id,
                        'serial_no': machine_sn.name,
                        'pcb_code': board_sn.name,
                    },
                    'binding_id')
        except Exception as exc:  # noqa: BLE001
            _logger.warning('NQI binding birth failed: %s', exc)
        return records


class NqiFitComponentBindBirth(models.Model):
    _inherit = 'sn.wsd.nqi.fit.component.bind'

    component_binding_id = fields.Many2one(
        'sn.wsd.meter.component.binding', string='Component Binding Event',
        index=True, ondelete='set null')

    _component_binding_uniq = models.Constraint(
        'unique(company_id, component_binding_id)',
        'One mirror row per component binding event.')


class MeterComponentBindingNqi(models.Model):
    _inherit = 'sn.wsd.meter.component.binding'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            helpers = self.env['sn.wsd.nqi.generation.mixin'].sudo()
            for record in records.sudo():
                parent = record.serial_identity_id
                if not parent:
                    continue
                helpers._nqi_create_if_new(
                    'sn.wsd.nqi.fit.component.bind',
                    {
                        'company_id': record.company_id.id,
                        'component_binding_id': record.id,
                        'pcb_code': parent.name,
                    },
                    'component_binding_id')
        except Exception as exc:  # noqa: BLE001
            _logger.warning('NQI component-binding birth failed: %s', exc)
        return records

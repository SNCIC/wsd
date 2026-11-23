"""Generation layer: tolerant birth hooks on MES write paths.

Every hook is wrapped in try/except so an NQI failure NEVER breaks the
station-pass / binding transaction; missed rows are recovered by the
watermark cron worker (nqi_worker). Idempotency uses event anchors
(one mirror row per source event, unique constraint on the anchor), so
replayed events and cron/hook races collapse to a single row.
"""
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'

# bare-INSERT enqueue for the hot path (see hook docstring): no ORM
# machinery, no flush pull-forward of the pending pass rows
_ENQUEUE_SQL = (
    "INSERT INTO sn_wsd_nqi_birth_queue "
    "(company_id, source_model, source_ids, create_uid, create_date, "
    " write_uid, write_date) VALUES (%s, %s, %s, %s, "
    "now() AT TIME ZONE 'UTC', %s, now() AT TIME ZONE 'UTC')")


def _enqueue_birth(cr, uid, company_id, source_model, source_ids):
    cr.execute(_ENQUEUE_SQL, (
        company_id, source_model, json.dumps(source_ids), uid, uid))


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
    def _nqi_create_batch_if_new(self, model_name, vals_list, key_field):
        """Batched idempotent create: one pre-filter search, one multi
        insert, one savepoint; a rare race falls back to row-by-row
        skipping (constraint collapses duplicates)."""
        if not vals_list:
            return self.env[model_name]
        target = self.env[model_name].sudo()
        keys = [vals[key_field] for vals in vals_list]
        existing = set(target.search(
            [(key_field, 'in', keys)]).mapped(key_field))
        todo = [vals for vals in vals_list
                if vals[key_field] not in existing]
        if not todo:
            return target.browse()
        try:
            with self.env.cr.savepoint():
                return target.create(todo)
        except Exception:  # noqa: BLE001 -- race: retry row by row
            created = target.browse()
            for vals in todo:
                created |= self._nqi_create_if_new(
                    model_name, vals, key_field)
            return created

    @api.model
    def _nqi_birth_mounting_rows(self, model_name, records):
        """One process row per judged station pass, axis by product kind."""
        board = model_name == 'sn.wsd.nqi.fit.pcb.mounting'
        batch = []
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
            batch.append(values)
        self._nqi_create_batch_if_new(
            model_name, batch, 'operation_history_id')


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
        batch = []
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
            batch.append({
                'company_id': record.company_id.id,
                'operation_history_id': record.id,
                'serial_no': sn.name,
                'status': '1',
            })
        helpers._nqi_create_batch_if_new(
            'sn.wsd.nqi.fit.meter.info', batch, 'operation_history_id')


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


class NqiFitBridgeBirthFromQueue(models.Model):
    _inherit = 'sn.wsd.nqi.fit.pcb.serial.bind'

    @api.model
    def _nqi_birth_from_bindings(self, records):
        helpers = self.env['sn.wsd.nqi.generation.mixin']
        batch = []
        for record in records.sudo():
            if record.binding_type != 'machine':
                continue
            board_sn = record.serial_identity_id
            machine_sn = record.bound_serial_identity_id
            if not board_sn or not machine_sn:
                continue
            batch.append({
                'company_id': record.company_id.id,
                'binding_id': record.id,
                'serial_no': machine_sn.name,
                'pcb_code': board_sn.name,
            })
        helpers._nqi_create_batch_if_new(
            'sn.wsd.nqi.fit.pcb.serial.bind', batch, 'binding_id')


class NqiFitComponentBirthFromQueue(models.Model):
    _inherit = 'sn.wsd.nqi.fit.component.bind'

    @api.model
    def _nqi_birth_from_component_bindings(self, records):
        helpers = self.env['sn.wsd.nqi.generation.mixin']
        batch = []
        for record in records.sudo():
            parent = record.serial_identity_id
            if not parent:
                continue
            batch.append({
                'company_id': record.company_id.id,
                'component_binding_id': record.id,
                'pcb_code': parent.name,
            })
        helpers._nqi_create_batch_if_new(
            'sn.wsd.nqi.fit.component.bind', batch,
            'component_binding_id')


class SerialOperationHistoryNqi(models.Model):
    _inherit = 'sn.wsd.serial.operation.history'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get('nqi_skip_birth'):
            return records
        try:
            # raw INSERT on the hot path: an ORM create here pulls the
            # pending pass-row flushes into the transaction and costs
            # ~0.5ms/pass; the queue row needs none of that machinery
            _enqueue_birth(self.env.cr, self.env.uid, records[0].company_id.id, 'sn.wsd.serial.operation.history', records.ids)
        except Exception as exc:  # noqa: BLE001 -- never break a pass
            _logger.warning('NQI birth enqueue failed: %s', exc)
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
            _enqueue_birth(self.env.cr, self.env.uid, records[0].company_id.id, 'sn.wsd.serial.binding', records.ids)
        except Exception as exc:  # noqa: BLE001
            _logger.warning('NQI binding enqueue failed: %s', exc)
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
            _enqueue_birth(self.env.cr, self.env.uid, records[0].company_id.id, 'sn.wsd.meter.component.binding', records.ids)
        except Exception as exc:  # noqa: BLE001
            _logger.warning('NQI component-binding enqueue failed: %s', exc)
        return records

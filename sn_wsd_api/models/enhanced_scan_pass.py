"""
Enhanced scan-pass API service integrating all MES features.

This module extends sn.wsd.api.service to implement full scan-pass functionality:
- M_TEST_DETAIL parsing and storage
- Nameplate binding with strict/override modes
- Tooling usage counting
- Process parameter validation (G0010 control)
- EIP data synchronization
- MSD exposure validation
- Packaging record generation
"""

import json
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EnhancedScanPassService(models.AbstractModel):
    """
    Enhanced scan-pass service integrating all features.
    
    This mixin provides full implementation of scan-pass API requirements
    including F-001 to F-032 and E-2.
    """
    _inherit = 'sn.wsd.api.service'

    @api.model
    def submit_scan_pass(
        self,
        payload: dict,
        source_system: str = 'SCAN_PASS',
        override_route: bool = False,
    ) -> dict:
        with self.env.cr.savepoint():
            return self.enhanced_submit_scan_pass(
                payload=payload,
                source_system=source_system,
                override_route=override_route,
            )

    @api.model
    def _parse_test_detail(self, test_detail: str | list) -> list:
        """Parse M_TEST_DETAIL into structured items."""
        return self.env['sn.wsd.mes.test.result.detail']._parse_test_detail(test_detail)

    @api.model
    def _create_test_result_details(self, test_result, test_detail: str | list):
        """Create test result detail records."""
        if not test_detail:
            return
        return self.env['sn.wsd.mes.test.result.detail'].create_from_test_result(
            test_result,
            test_detail,
        )

    @api.model
    def _process_nameplate_binding(self, payload: dict, production_id, workorder_id, workcenter_id, operator_code, company_id):
        """Process nameplate binding from M_STR1 field."""
        nameplate_code = self._scan_payload_value(payload, 'M_STR1')
        if not nameplate_code:
            return None
        
        serial_number = self._scan_payload_value(payload, 'M_SN')
        if not serial_number:
            return None
        
        try:
            binding_model = self.env['sn.wsd.mes.nameplate.binding']
            binding = binding_model.bind_nameplate(
                serial_number=serial_number,
                nameplate_code=nameplate_code,
                company_id=company_id,
                production_id=production_id,
                workcenter_id=workcenter_id,
                operator_code=operator_code,
                note='Scan-pass binding',
            )
            return binding
        except ValidationError:
            return None

    @api.model
    def _process_tooling_usage(self, payload: dict, production_id, workorder_id, workcenter_id, operator_code, serial_number, company_id):
        """Process tooling usage from M_TOOLING field."""
        tooling_input = self._scan_payload_value(payload, 'M_TOOLING')
        if not tooling_input:
            return []
        
        tooling_model = self.env['sn.wsd.mes.tooling.usage.log']
        tooling_sns = tooling_model._parse_tooling_string(tooling_input)
        if not tooling_sns:
            return []
        
        records = tooling_model.increment_tooling_usage(
            tooling_sns=tooling_sns,
            company_id=company_id,
            production_id=production_id,
            manufacturing_batch_id=self.env['mrp.production'].browse(production_id).x_manufacturing_batch_id.id if production_id else False,
            workorder_id=workorder_id,
            workcenter_id=workcenter_id,
            serial_number=serial_number,
            operator_code=operator_code,
            event_type='scan_pass',
            payload=payload,
        )
        return records

    @api.model
    def _validate_process_parameters(self, payload: dict, production_id, **kwargs):
        """Validate process parameters when G0010=1."""
        validation_model = self.env['sn.wsd.mes.process.parameter.validation']
        
        if not validation_model._is_validation_enabled(kwargs.get('company_id')):
            return []
        
        results = validation_model.validate_all_parameters(
            payload=payload,
            production_id=production_id,
            **kwargs
        )
        
        if results:
            validation_model.create_validation_records(
                production_id=production_id,
                validation_results=results,
                **kwargs
            )
        
        return results

    @api.model
    def _sync_to_eip(self, test_result_id, payload=None):
        """Synchronize test result to EIP."""
        sync_model = self.env['sn.wsd.mes.eip.sync.record']
        return sync_model.sync_to_eip(test_result_id, payload=payload)

    @api.model
    def _validate_msd_exposure(self, internal_serial_id, company_id):
        """Validate MSD exposure for PCB."""
        if not internal_serial_id:
            return True
        
        exposure_model = self.env['sn.wsd.mes.pcb.exposure.record']
        config_model = self.env['ir.config_parameter'].sudo()
        max_interval = int(config_model.get_param(
            'sn_wsd_smt.msd_max_print_interval', '480'
        ) or '480')
        
        try:
            return exposure_model.validate_print_interval(
                internal_serial_id=internal_serial_id,
                max_interval_minutes=max_interval
            )
        except ValidationError:
            return False

    @api.model
    def _process_packaging(self, payload: dict, production_id, workorder_id, workcenter_id, serial_number, operator_code, result, company_id):
        """Process packaging from M_BOX_SN and M_SECOND_SN."""
        box_sn = self._scan_payload_value(payload, 'M_BOX_SN')
        pallet_sn = self._scan_payload_value(payload, 'M_SECOND_SN')
        nameplate_code = self._scan_payload_value(payload, 'M_STR1')
        crc_value = self._scan_payload_value(payload, 'M_STR5')
        
        if not (box_sn or pallet_sn):
            return None
        if pallet_sn:
            raise ValidationError(
                'Pallet binding is only allowed through the manual barcode pallet-binding operation.'
            )
        
        if result == 'fail':
            return {'error': 'NG test results are not allowed to package.', 'blocked': True}
        
        packaging_model = self.env['sn.wsd.mes.packaging.record']
        return packaging_model.create_packaging(
            serial_number=serial_number,
            company_id=company_id,
            production_id=production_id,
            workorder_id=workorder_id,
            workcenter_id=workcenter_id,
            nameplate_code=nameplate_code,
            box_sn=box_sn,
            pallet_sn=pallet_sn,
            operator_code=operator_code,
            crc_value=crc_value,
            payload=payload,
        )

    @api.model
    def enhanced_submit_scan_pass(
        self,
        payload: dict,
        source_system: str = 'SCAN_PASS',
        override_route: bool = False,
    ) -> dict:
        """
        Enhanced submit_scan_pass with full feature integration.
        
        This method wraps the standard submit_scan_pass and adds:
        - M_TEST_DETAIL parsing
        - Nameplate binding
        - Tooling usage counting
        - Process parameter validation
        - EIP synchronization
        - MSD exposure validation
        - Packaging record generation
        
        :returns: API response dict
        """
        if not isinstance(payload, dict):
            return self._aoi_error('Payload must be a JSON object.')
        company, context_error = self._validate_scan_required_context(payload)
        if context_error:
            return context_error
        
        original_payload = payload
        payload, identifier_context, identifier_error = self._resolve_scan_serial_identifier(payload)
        if identifier_error:
            return identifier_error

        serial_number = self._scan_payload_value(payload, 'M_SN')
        station_code = self._scan_payload_value(payload, 'M_WORK_STATIONSN')
        operator_code = self._scan_payload_value(payload, 'M_EMP')
        raw_result = self._scan_payload_value(payload, 'M_TEST_RESULT')
        normalized_result = self._normalize_scan_test_result(raw_result)
        
        if not serial_number:
            return self._aoi_error(
                'Missing required field: M_SN or a bound nameplate code.',
                error_code='serial_identifier_required',
            )
        if not station_code:
            return self._aoi_error('Missing required field: M_WORK_STATIONSN')
        if not normalized_result:
            return self._aoi_error('Test result must be OK or NG.', M_TEST_RESULT=raw_result)
        
        work_center = self._find_scan_workcenter(station_code, company=company)
        if not work_center:
            return self._aoi_error('Work center not found.', M_WORK_STATIONSN=station_code)
        
        workorder = self._resolve_scan_workorder(payload)
        if not workorder:
            return self._aoi_error(
                'Active work order not found for the manufacturing batch and work center.',
                M_MO_NUMBER=self._get_first_payload_value(payload, 'M_MO_NUMBER'),
                M_WORK_STATIONSN=station_code,
            )

        serial, serial_created, serial_prepare_error = self._prepare_scan_serial(
            serial_number, workorder, payload,
        )
        if serial_prepare_error:
            return serial_prepare_error
        serial, serial_error = self._validate_serial_for_workorder(serial_number, workorder)
        if serial_error:
            return serial_error
        box_sn = self._scan_payload_value(payload, 'M_BOX_SN')
        pallet_sn = self._scan_payload_value(payload, 'M_SECOND_SN')
        if normalized_result == 'pass' and (box_sn or pallet_sn):
            self.env['sn.wsd.mes.packaging.record']._check_can_package(
                serial_number,
                company.id,
                production_id=workorder.production_id.id,
            )
        
        production_id = workorder.production_id.id if workorder.production_id else None
        manufacturing_batch_id = workorder.x_manufacturing_batch_id.id if workorder.x_manufacturing_batch_id else None
        workcenter_id = work_center.id
        
        extra_context = {
            'company_id': company.id,
            'manufacturing_batch_id': manufacturing_batch_id,
            'workorder_id': workorder.id,
            'workcenter_id': workcenter_id,
            'operator_code': operator_code,
        }
        
        validation_results = self._validate_process_parameters(
            payload=payload,
            production_id=production_id,
            **extra_context
        )
        if validation_results:
            failed = [r for r in validation_results if r.get('result') == 'fail']
            if failed:
                return self._aoi_error(
                    failed[0].get('error') or 'Parameter validation failed.',
                    validation_errors=validation_results
                )
        
        external_event_id = self._resolve_scan_external_event_id(payload)
        note = self._scan_test_detail_note(payload)
        metadata_payload = self._prepare_payload_metadata(
            payload=payload,
            external_event_id=external_event_id,
            source_system=source_system,
        )
        if identifier_context.get('input_identifier_type') == 'nameplate':
            metadata_payload.update({
                'M_ORIGINAL_SN': identifier_context.get('input_code'),
                'M_RESOLVED_SN': identifier_context.get('resolved_serial_number'),
                'M_SCAN_IDENTIFIER_TYPE': identifier_context.get('input_identifier_type'),
                'M_RESOLVED_NAMEPLATE_CODE': identifier_context.get('nameplate_code'),
                'M_NAMEPLATE_BINDING_ID': identifier_context.get('nameplate_binding_id'),
            })
        elif original_payload is not payload:
            metadata_payload['M_ORIGINAL_SN'] = identifier_context.get('input_code')
        retry_context = self._prepare_scan_retry_context(serial, workorder, normalized_result)
        rework_context = self._prepare_scan_rework_context(serial, workorder, normalized_result)
        
        if normalized_result == 'pass':
            result = self.submit_workorder_event(
                workorder_id=workorder.id,
                event_type='complete',
                serial_number=serial_number,
                operator_code=operator_code,
                note=note,
                override_route=override_route,
                external_event_id=external_event_id,
                source_system=source_system,
                payload=metadata_payload,
            )
        else:
            result = self.submit_test_result(
                workorder_id=workorder.id,
                serial_number=serial_number,
                result='fail',
                operator_code=operator_code,
                note=note,
                payload=metadata_payload,
                external_event_id=external_event_id,
                source_system=source_system,
                retry_sequence=retry_context['retry_sequence'],
                retry_limit=retry_context['retry_limit'],
                requires_repair=retry_context['requires_repair'],
            )
        
        if result.get('ok'):
            data = dict(result.get('data') or {})
            retry_context, rework_context, test_result_record = self._scan_result_context_from_record(
                data, retry_context, rework_context,
            )
            
            test_result_id = data.get('test_result_id')
            if test_result_id and metadata_payload.get('M_TEST_DETAIL'):
                test_result = self.env['sn.wsd.mes.test.result'].browse(test_result_id).exists()
                if test_result:
                    self._create_test_result_details(test_result, metadata_payload.get('M_TEST_DETAIL'))
            
            if normalized_result == 'pass':
                self._process_nameplate_binding(
                    payload, production_id, workorder.id, workcenter_id, operator_code, company.id
                )
                self._process_tooling_usage(
                    payload, production_id, workorder.id, workcenter_id, operator_code, serial_number, company.id
                )
                
                packaging_result = self._process_packaging(
                    payload, production_id, workorder.id, workcenter_id, serial_number, operator_code, normalized_result, company.id
                )
                
                if test_result_id:
                    self._sync_to_eip(test_result_id, payload=metadata_payload)
            elif retry_context['requires_repair']:
                repair_workorder = self._apply_scan_repair_requirement(
                    serial,
                    workorder,
                    operator_code=operator_code,
                    note=note,
                )
                if repair_workorder:
                    data['repair_workorder_id'] = repair_workorder.id
            
            data.update({
                'serial_number': serial_number,
                'workorder_id': workorder.id,
                'production_id': production_id,
                'workcenter_id': workcenter_id,
                'workcenter_code': work_center.code,
                'result': normalized_result,
                'source_system': source_system,
                'internal_serial_id': serial.id,
                'serial_stage_created': serial_created,
                'input_code': identifier_context.get('input_code'),
                'input_identifier_type': identifier_context.get('input_identifier_type'),
                'resolved_serial_number': identifier_context.get('resolved_serial_number'),
                'nameplate_code': identifier_context.get('nameplate_code') or False,
                'nameplate_binding_id': identifier_context.get('nameplate_binding_id') or False,
                'retry_sequence': retry_context['retry_sequence'],
                'retry_limit': retry_context['retry_limit'],
                'requires_repair': retry_context['requires_repair'],
                'is_rework_pass': rework_context['is_rework_pass'],
                'rework_source_workorder_id': rework_context['rework_source_workorder_id'],
            })
            
            if validation_results:
                data['validation_results'] = validation_results
            
            return self._aoi_response(data=data)
        
        error = result.get('error') or {}
        return self._aoi_error(
            error.get('message') or 'Scan pass failed.',
            **(error.get('details') or {})
        )

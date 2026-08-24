"""Full interface-field mirror columns for the scan-pass wide list.

One column per uploaded form field (the pass's verbatim snapshot), so the
test-results list can show, search and export everything the device sent.
Multi-value fields keep the pipe-separated raw form. Structured ledgers
(component bindings / pack records / process documents / serial bindings)
stay untouched — these columns are display/search copies.
"""

from odoo import fields, models

# payload key -> field name, the single source for ingest writes and the
# jsonb backfill of existing rows
PAYLOAD_TO_FIELD = {
    'M_SOFTWARE_NAME': 'software_name',
    'M_ADDRESS': 'table_position',
    'M_COLLABORATION_EMP': 'collaborator_code',
    'M_CODE_ID': 'code_id',
    'M_PARAMETER_PLAN': 'parameter_plan',
    'M_PROGRAM_NUM': 'program_num',
    'M_TEST_PLAN': 'test_plan_num',
    'M_SOFTWARE_NUM': 'software_num',
    'M_MAIN_ID': 'pcba_codes',
    'M_MODULE_ID': 'module_codes',
    'M_LEADSEAL_ID': 'leadseal_codes',
    'M_BOX_SN': 'box_sn',
    'M_SECOND_SN': 'pallet_sn',
    'M_STR1': 'internal_code',
    'M_STR2': 'm_str2',
    'M_STR3': 'm_str3',
    'M_STR4': 'm_str4',
    'M_STR5': 'm_str5',
    'M_STR6': 'm_str6',
    'M_STR7': 'm_str7',
    'M_STR8': 'm_str8',
    'M_STR9': 'm_str9',
    'M_STR10': 'm_str10',
    'M_PACK_LEFT_SEAL': 'pack_left_seal',
    'M_PACK_LEFT_SEAL_RF': 'pack_left_seal_rf',
    'M_PACK_RIGHT_SEAL': 'pack_right_seal',
    'M_PACK_RIGHT_SEAL_RF': 'pack_right_seal_rf',
    'M_PACK_DOOR_SEAL': 'pack_door_seal',
    'M_PACK_DOOR_SEAL_RF': 'pack_door_seal_rf',
    'M_PACK_NAMEPLATE_RF': 'pack_nameplate_rf',
    'M_PACK_MODULE': 'pack_module',
    'M_PACK_MAC': 'pack_mac',
    'M_PACK_TOP': 'pack_top',
    'M_PACK_LEFT': 'pack_left',
    'M_PACK_RIGHT': 'pack_right',
    'M_PACK_BACK': 'pack_back',
}


class MesTestResultInterfaceColumns(models.Model):
    _inherit = 'sn.wsd.mes.test.result'

    software_name = fields.Char(
        string='Software Name', help='Verbatim uploaded form field M_SOFTWARE_NAME.')
    table_position = fields.Char(
        string='Table Position', help='Verbatim uploaded form field M_ADDRESS.')
    collaborator_code = fields.Char(
        string='Collaborator', help='Verbatim uploaded form field M_COLLABORATION_EMP.')
    code_id = fields.Char(
        string='Code ID', help='Verbatim uploaded form field M_CODE_ID.')
    parameter_plan = fields.Char(
        string='Parameter Plan', help='Verbatim uploaded form field M_PARAMETER_PLAN.')
    program_num = fields.Char(
        string='Program Number', help='Verbatim uploaded form field M_PROGRAM_NUM.')
    test_plan_num = fields.Char(
        string='Test Plan', help='Verbatim uploaded form field M_TEST_PLAN.')
    software_num = fields.Char(
        string='Software Number', help='Verbatim uploaded form field M_SOFTWARE_NUM.')
    pcba_codes = fields.Char(
        string='PCBA Codes', index=True,
        help='Verbatim uploaded form field M_MAIN_ID (pipe-separated).')
    module_codes = fields.Char(
        string='Module Codes', index=True,
        help='Verbatim uploaded form field M_MODULE_ID (pipe-separated).')
    leadseal_codes = fields.Char(
        string='Lead Seal Codes', index=True,
        help='Verbatim uploaded form field M_LEADSEAL_ID (pipe-separated).')
    box_sn = fields.Char(
        string='Box SN', index=True, help='Verbatim uploaded form field M_BOX_SN.')
    pallet_sn = fields.Char(
        string='Pallet SN', index=True, help='Verbatim uploaded form field M_SECOND_SN.')
    internal_code = fields.Char(
        string='Nameplate Code', index=True,
        help='Verbatim uploaded form field M_STR1 (nameplate scanned with this pass).')
    m_str2 = fields.Char(help='Verbatim uploaded form field M_STR2 (defect code).')
    m_str3 = fields.Char(help='Verbatim uploaded form field M_STR3.')
    m_str4 = fields.Char(help='Verbatim uploaded form field M_STR4.')
    m_str5 = fields.Char(help='Verbatim uploaded form field M_STR5.')
    m_str6 = fields.Char(help='Verbatim uploaded form field M_STR6.')
    m_str7 = fields.Char(help='Verbatim uploaded form field M_STR7.')
    m_str8 = fields.Char(help='Verbatim uploaded form field M_STR8.')
    m_str9 = fields.Char(help='Verbatim uploaded form field M_STR9.')
    m_str10 = fields.Char(help='Verbatim uploaded form field M_STR10.')
    pack_left_seal = fields.Char(help='Verbatim uploaded form field M_PACK_LEFT_SEAL.')
    pack_left_seal_rf = fields.Char(help='Verbatim uploaded form field M_PACK_LEFT_SEAL_RF.')
    pack_right_seal = fields.Char(help='Verbatim uploaded form field M_PACK_RIGHT_SEAL.')
    pack_right_seal_rf = fields.Char(help='Verbatim uploaded form field M_PACK_RIGHT_SEAL_RF.')
    pack_door_seal = fields.Char(help='Verbatim uploaded form field M_PACK_DOOR_SEAL.')
    pack_door_seal_rf = fields.Char(help='Verbatim uploaded form field M_PACK_DOOR_SEAL_RF.')
    pack_nameplate_rf = fields.Char(help='Verbatim uploaded form field M_PACK_NAMEPLATE_RF.')
    pack_module = fields.Char(help='Verbatim uploaded form field M_PACK_MODULE.')
    pack_mac = fields.Char(help='Verbatim uploaded form field M_PACK_MAC.')
    pack_top = fields.Char(help='Verbatim uploaded form field M_PACK_TOP.')
    pack_left = fields.Char(help='Verbatim uploaded form field M_PACK_LEFT.')
    pack_right = fields.Char(help='Verbatim uploaded form field M_PACK_RIGHT.')
    pack_back = fields.Char(help='Verbatim uploaded form field M_PACK_BACK.')

"""Tests of the mapping transform engine (eip-collect-mapping-limits):
the (number, err) transform contract, detail translation rows
(1007/2006), per-type limit judging, the trial button and save-time
validation."""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase


class TestEipTransform(TransactionCase):
    """Transform contract, detail translation rows, per-type limits."""

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.env['sn.wsd.eip.collect.outbox'].search([]).unlink()
        self.company = self.env['res.company'].search(
            [], order='id asc', limit=1)
        self.config = self._ensure_config()
        self.Mapping = self.env['sn.wsd.eip.value.mapping']
        self.Rule = self.env['sn.wsd.eip.clean.rule']
        self.PassRecord = self.env['sn.wsd.eip.pass.record']
        self.Line = self.env['sn.wsd.eip.pass.record.line']
        self.counter = 0

    def _ensure_config(self):
        config = self.env['sn.wsd.eip.config'].search([
            ('company_id', '=', self.company.id),
            ('active', '=', True)], limit=1)
        if config:
            return config
        return self.env['sn.wsd.eip.config'].create({
            'company_id': self.company.id,
            'supplier_code': 'SUP-1',
            'supplier_name': 'Supplier One',
            'base_url': 'http://127.0.0.1:9',
        })

    def _mapping(self, code='1007', eip_field='average_error',
                 source_key='正向-有功-合元', source_kind='detail_item',
                 transform_code=False, **vals):
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', code)
        vals.setdefault('eip_field', eip_field)
        vals.setdefault('source_kind', source_kind)
        vals.setdefault('source_key', source_key)
        if transform_code:
            vals.setdefault('transform_code', transform_code)
        return self.Mapping.create(vals)

    def _source(self, code='1007', **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', code)
        vals.setdefault('test_code', '%s-T%s' % (code, self.counter))
        vals.setdefault('conclusion', 0)
        vals.setdefault('check_time', '2025-11-26 09:00:00')
        vals.setdefault('device_no', 'DX01')
        vals.setdefault('model_code', 'DDSY10217')
        vals.setdefault('pcb_code', 'SN%s' % self.counter)
        vals.setdefault('production_order_no', 'MO001')
        vals.setdefault('work_order_no', 'W001')
        vals.setdefault('test_name', '基本误差详情')
        return self.PassRecord.create(vals)

    def _detail(self, row, project_name, actual, upper, lower='0', seq=1):
        self.Line.create({'record_id': row.id, 'line_type': 'test_detail',
                          'project_name': project_name,
                          'actual_value': actual,
                          'upper_limit': upper, 'lower_limit': lower,
                          'sequence': seq})

    # ---- transform contract: (number, err) ----

    def test_10_multi_read_takes_last_segment(self):
        mapping = self._mapping(
            code='1005', eip_field='current_value', source_kind='detail_item',
            source_key='电池电流实测',
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return float(str(value).split("
                           "'，')[-1])")
        number, err = mapping._eip_call_transform(
            '0.001，0.002，0.003，0.005', 0, 50, '电池电流实测', 1, {})
        self.assertIsNone(err)
        self.assertEqual(number, 0.005)

    def test_11_single_value_passes_through(self):
        mapping = self._mapping(
            code='1005', eip_field='current_value', source_kind='detail_item',
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return float(value)")
        number, err = mapping._eip_call_transform('2.05', 0, 5, 'n', 1, {})
        self.assertIsNone(err)
        self.assertEqual(number, 2.05)

    def test_12_none_means_deliberate_skip(self):
        mapping = self._mapping(
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return None")
        number, err = mapping._eip_call_transform('x', 0, 0, 'n', 1, {})
        self.assertIsNone(number)
        self.assertIsNone(err)

    def test_13_bad_return_type_is_reported(self):
        mapping = self._mapping(
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return 'oops' if value == 'real' else 1.0")
        number, err = mapping._eip_call_transform('1', 0, 0, 'n', 1, {})
        self.assertIsNone(err)
        self.assertEqual(number, 1.0)
        number, err = mapping._eip_call_transform('real', 0, 0, 'n', 1, {})
        self.assertIsNone(number)
        self.assertIn('expected a number', err)

    def test_14_no_env_leak(self):
        """The transform namespace only sees the six arguments: no env,
        cr or registry objects reach the function."""
        mapping = self._mapping(
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return env")
        number, err = mapping._eip_call_transform('1', 0, 0, 'n', 1, {})
        self.assertIsNone(number)
        self.assertTrue(err)  # NameError inside the transform, isolated

    # ---- save-time validation ----

    def test_20_save_blocks_syntax_error(self):
        with self.assertRaises(ValidationError):
            self._mapping(transform_code="def transform(value, low, up, "
                                         "name, seq, detail):\n    return "
                                         "oops <<<")

    def test_21_save_blocks_bad_return_type(self):
        with self.assertRaises(ValidationError):
            self._mapping(transform_code="def transform(value, low, up, "
                                         "name, seq, detail):\n    return "
                                         "'text'")

    def test_22_save_allows_working_code(self):
        mapping = self._mapping(
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return float(value)")
        self.assertTrue(mapping.transform_code)

    # ---- trial button ----

    def test_30_trial_reports_result(self):
        mapping = self._mapping(
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return float(str(value).split("
                           "'，')[-1])")
        mapping.sample_value = '0.001，0.002，0.003，0.005'
        action = mapping.action_test_transform()
        self.assertIn('0.005', action['params']['message'])

    def test_31_trial_reports_error(self):
        mapping = self._mapping(
            transform_code="def transform(value, low, up, name, seq, "
                           "detail):\n    return float(value)")
        mapping.sample_value = 'garbage'
        action = mapping.action_test_transform()
        self.assertIn('error', action['params']['message'])

    # ---- 1007 detail translation rows ----

    def test_40_same_name_discriminated_by_up_limit(self):
        """Two details with the same project name but different upper
        limits: the matching translation row wins, producing H1 / H2."""
        row = self._source()
        self._detail(row, '正向-有功-合元', '-0.020', upper='0.6', seq=1)
        self._detail(row, '正向-有功-合元', '-0.010', upper='0.25', seq=2)
        self._mapping(code='1007', eip_field='average_error',
                      source_kind='detail_translate',
                      source_key='正向-有功-合元', match_up_limit='0.6',
                      target_type='H1', target_test_name='正向-有功-合元-Imax1.0')
        self._mapping(code='1007', eip_field='average_error',
                      source_kind='detail_translate',
                      source_key='正向-有功-合元', match_up_limit='0.25',
                      target_type='H2', target_test_name='正向-有功-合元-Ib1.0')
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payloads = row.outbox_ids.mapped('payload')
        self.assertEqual(sorted(p['AVERAGE_ERROR_TYPE'] for p in payloads),
                         ['H1', 'H2'])
        by_type = {p['AVERAGE_ERROR_TYPE']: p for p in payloads}
        self.assertEqual(by_type['H1']['AVERAGE_ERROR'], -0.02)
        self.assertEqual(by_type['H2']['AVERAGE_ERROR'], -0.01)
        self.assertEqual(by_type['H2']['TEST_NAME'], '正向-有功-合元-Ib1.0')
        self.assertEqual(row.line_ids[0].cleansed_value, '-0.02')

    def test_41_translation_transform_cleanses_the_value(self):
        """A translation row with transform code: the type/name come from
        the target columns, the value is cleansed by the code."""
        row = self._source()
        self._detail(row, '厂家格式误差项', '0.001，0.002，0.005', upper='0.6')
        self._mapping(code='1007', eip_field='average_error',
                      source_kind='detail_translate',
                      source_key='厂家格式误差项', match_up_limit='0.6',
                      target_type='H3', target_test_name='正向-有功-合元-10Itr1.0',
                      transform_code="def transform(value, low, up, name, "
                                     "seq, detail):\n    return float(str("
                                     "value).split('，')[-1])")
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payload = row.outbox_ids.payload
        self.assertEqual(payload['AVERAGE_ERROR_TYPE'], 'H3')
        self.assertEqual(payload['TEST_NAME'], '正向-有功-合元-10Itr1.0')
        self.assertEqual(payload['AVERAGE_ERROR'], 0.005)
        self.assertEqual(row.line_ids[0].cleansed_value, '0.005')

    def test_42_builtin_name_table_still_falls_back(self):
        """No translation row: a detail named exactly like the platform
        table still translates through the builtin fallback."""
        row = self._source()
        self._detail(row, '正向-有功-C相-Imax1.0', '-0.022', upper='0.6')
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payload = row.outbox_ids.payload
        self.assertEqual(payload['AVERAGE_ERROR_TYPE'], 'C1')

    def test_43_untranslated_details_are_skipped(self):
        """Details without a translation (e.g. reverse points the
        platform does not know) are skipped; other details still ship."""
        row = self._source()
        self._detail(row, '正向-有功-C相-Imax1.0', '-0.022', upper='0.6')
        self._detail(row, '反向-有功-第5点', '-0.9', upper='0.6', seq=2)
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        self.assertEqual(len(row.outbox_ids), 1)

    def test_44_all_details_skipped_rejects_the_row(self):
        row = self._source()
        self._detail(row, '反向-有功-第5点', '-0.9', upper='0.6')
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertIn('no valid error-detail lines', row.clean_note)

    # ---- per-type limit rules ----

    def test_50_type_rules_judge_each_detail(self):
        """Type rules: each detail is judged by its own type's limits;
        an out-of-limit detail rejects the whole row."""
        self.Rule.create({'company_id': self.company.id,
                          'info_type_code': '1007',
                          'field_name': 'average_error',
                          'average_error_type': 'C1',
                          'lower_limit': -0.5, 'upper_limit': 0.5})
        row = self._source()
        self._detail(row, '正向-有功-C相-Imax1.0', '-0.700', upper='0.6',
                     seq=1)
        self._detail(row, '正向-有功-B相-Imax1.0', '-0.400', upper='0.6',
                     seq=2)
        row._eip_clean_rows()
        # C1 over limit -> the whole row rejected; B1 had no rule
        self.assertEqual(row.state, 'rejected')
        self.assertIn('average_error=-0.7 < -0.5', row.clean_note)

    def test_51_empty_type_rule_is_the_fallback(self):
        self.Rule.create({'company_id': self.company.id,
                          'info_type_code': '1007',
                          'field_name': 'average_error',
                          'lower_limit': -0.5, 'upper_limit': 0.5})
        row = self._source()
        self._detail(row, '正向-有功-B相-Imax1.0', '-0.700', upper='0.6')
        row._eip_clean_rows()
        # B1 has no exact rule: the empty-type rule judges the detail
        self.assertEqual(row.state, 'rejected')
        self.assertIn('average_error=-0.7 < -0.5', row.clean_note)

    def test_52_no_matching_rule_leaves_the_detail_unjudged(self):
        row = self._source()
        self._detail(row, '正向-有功-B相-Imax1.0', '-0.700', upper='0.6')
        row._eip_clean_rows()
        # no rule at all for B1: the detail ships unjudged
        self.assertEqual(row.state, 'qualified')

    # ---- 2006 translation rows ----

    def test_60_ac_analog_translation(self):
        row = self._source(code='2006')
        row.write({'standard_value': 220.0, 'error_value': 0.5})
        self._detail(row, '厂家A交流第一相', '219.8', upper='0.6')
        self._mapping(code='2006', eip_field='measured_value',
                      source_kind='detail_translate',
                      source_key='厂家A交流第一相', match_up_limit='0.6',
                      target_type='ⅠA', target_test_name='交流模拟量采集A相')
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        payload = row.outbox_ids.payload
        self.assertEqual(payload['AVERAGE_ERROR_TYPE'], 'ⅠA')
        self.assertEqual(payload['MEASURED_VALUE'], 219.8)
        self.assertEqual(payload['STANDARD_VALUE'], 220.0)
        self.assertEqual(payload['ERROR_VALUE'], 0.5)

    def test_61_ac_analog_type_limit(self):
        self.Rule.create({'company_id': self.company.id,
                          'info_type_code': '2006',
                          'field_name': 'measured_value',
                          'average_error_type': 'ⅠA',
                          'lower_limit': 200.0, 'upper_limit': 240.0})
        row = self._source(code='2006')
        row.write({'standard_value': 220.0, 'error_value': 0.5})
        self._detail(row, '交流模拟量采集A相', '250.0', upper='0.6')
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertIn('measured_value=250.0 > 240.0', row.clean_note)

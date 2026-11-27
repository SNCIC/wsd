"""Structured clean issues: the cleansing engine writes every problem
of a row as one ``sn.wsd.eip.clean.issue`` row next to the free-text
clean note (spec eip-collect-cleansing, requirement "structured problems").
"""

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEipCleanIssue(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, lang='en_US'))
        self.env['sn.wsd.eip.collect.outbox'].search([]).unlink()
        self.PassRecord = self.env['sn.wsd.eip.pass.record']
        self.Line = self.env['sn.wsd.eip.pass.record.line']
        self.Issue = self.env['sn.wsd.eip.clean.issue']
        self.Rule = self.env['sn.wsd.eip.clean.rule']
        self.company = self.env['res.company'].search(
            [], order='id asc', limit=1)
        if not self.env['sn.wsd.eip.config'].search([
                ('company_id', '=', self.company.id), ('active', '=', True)],
                limit=1):
            self.env['sn.wsd.eip.config'].create({
                'company_id': self.company.id,
                'supplier_code': 'SUP-1', 'supplier_name': 'Supplier One',
                'base_url': 'http://127.0.0.1:9',
            })
        # seed rules would judge rows this class means to be unjudged
        self.Rule.search([
            ('company_id', '=', self.company.id),
            ('info_type_code', 'in', ['1002', '1004', '1007'])]).unlink()
        self.counter = 0

    def _source(self, code='1002', **vals):
        self.counter += 1
        vals.setdefault('company_id', self.company.id)
        vals.setdefault('info_type_code', code)
        vals.setdefault('test_code', '%s-T%s' % (code, self.counter))
        vals.setdefault('conclusion', 0)
        vals.setdefault('check_time', fields.Datetime.now())
        vals.setdefault('device_no', 'DX01')
        vals.setdefault('model_code', 'DDSY10217')
        vals.setdefault('pcb_code', 'SN001' + str(self.counter))
        vals.setdefault('production_order_no', 'MO001')
        vals.setdefault('work_order_no', 'W001')
        vals.setdefault('test_name', 'Withstand Voltage Test')
        return self.PassRecord.create(vals)

    def _full_1002(self, **vals):
        values = {'check_duration': '60', 'testing_voltage': '4200',
                  'leakage_current': 2.0}
        values.update(vals)
        return self._source(**values)

    def _detail(self, row, project_name, actual, upper, seq=1):
        return self.Line.create({
            'record_id': row.id, 'line_type': 'test_detail',
            'project_name': project_name, 'actual_value': actual,
            'upper_limit': upper, 'lower_limit': '0', 'sequence': seq})

    # ------------------------------------------------------------------
    # missing gate: one issue per missing field
    # ------------------------------------------------------------------

    def test_10_missing_fields_land_as_one_issue_each(self):
        row = self._source()  # no value column at all: 3 missing
        row._eip_clean_rows()
        issues = row.issue_ids.sorted('id')
        self.assertEqual(len(issues), 3)
        self.assertEqual(set(issues.mapped('kind')), {'missing'})
        self.assertEqual(
            set(issues.mapped('field_name')),
            {'check_duration', 'testing_voltage', 'leakage_current'})
        self.assertEqual(
            set(issues.mapped('message')),
            {'missing required: %s' % name for name in
             ('check_duration', 'testing_voltage', 'leakage_current')})
        # the note text is untouched: the issues are its twin
        self.assertIn('missing required: testing_voltage', row.clean_note)
        self.assertEqual(issues.mapped('source_id'), row)
        self.assertEqual(issues.mapped('company_id'), row.company_id)

    def test_11_correction_clears_the_missing_issue(self):
        """A filed correction satisfies the gate: no issue for the
        corrected field any more (the row is judged on raw + fixes)."""
        row = self._source(code='1008')  # 6 archive fields missing
        row._eip_clean_rows()
        self.assertEqual(len(row.issue_ids), 6)
        self.env['sn.wsd.eip.clean.fix'].create({
            'source_id': row.id, 'field_name': 'plant_code',
            'value': 'P1', 'basis': 'issued plant list'})
        row._eip_clean_rows()
        self.assertEqual(len(row.issue_ids), 5)
        self.assertNotIn('plant_code', row.issue_ids.mapped('field_name'))
        # the raw column is still empty: the correction rode along
        self.assertFalse(row.plant_code)

    def test_12_fully_corrected_row_qualifies_without_issues(self):
        row = self._source(code='1008')
        Fix = self.env['sn.wsd.eip.clean.fix']
        Fix.create([{
            'source_id': row.id, 'field_name': name, 'value': 'X',
            'basis': 'archive record',
        } for name in ('plant_code', 'software_version', 'nameplate_code',
                       'table_no', 'table_address', 'asset_management_no')])
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        self.assertFalse(row.issue_ids)
        self.assertFalse(row.clean_note)

    # ------------------------------------------------------------------
    # limit gate: row level and per detail line
    # ------------------------------------------------------------------

    def test_20_row_level_limit_issue_carries_value_and_limits(self):
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '1002',
            'field_name': 'leakage_current',
            'lower_limit': 0.0, 'upper_limit': 5.0})
        row = self._full_1002(leakage_current=7.5)
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        issue = row.issue_ids
        self.assertEqual(len(issue), 1)
        self.assertEqual(issue.kind, 'limit')
        self.assertEqual(issue.field_name, 'leakage_current')
        self.assertEqual(issue.actual_value, 7.5)
        self.assertEqual(issue.lower_limit, 0.0)
        self.assertEqual(issue.upper_limit, 5.0)
        self.assertFalse(issue.line_id)
        self.assertFalse(issue.type_code)
        # the same text the note carries for this problem
        self.assertEqual(issue.message, 'limit fail: leakage_current=7.5 > 5.0')
        self.assertIn(issue.message, row.clean_note)

    def test_21_detail_limit_issue_points_at_the_detail_line(self):
        """1007: the out-of-limit issue names the detail line and its
        type code."""
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '1007',
            'field_name': 'average_error', 'average_error_type': 'C1',
            'lower_limit': -0.5, 'upper_limit': 0.5})
        row = self._source(code='1007')
        bad = self._detail(row, '正向-有功-C相-Imax1.0', '-0.700', '0.6', 1)
        self._detail(row, '正向-有功-B相-Imax1.0', '-0.400', '0.6', 2)
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        issue = row.issue_ids
        self.assertEqual(len(issue), 1)
        self.assertEqual(issue.kind, 'limit')
        self.assertEqual(issue.line_id, bad)
        self.assertEqual(issue.type_code, 'C1')
        self.assertEqual(issue.field_name, 'average_error')
        self.assertAlmostEqual(issue.actual_value, -0.7, places=6)
        self.assertEqual((issue.lower_limit, issue.upper_limit), (-0.5, 0.5))

    def test_22_two_detail_limits_are_two_issues(self):
        self.Rule.create([{
            'company_id': self.company.id, 'info_type_code': '1007',
            'field_name': 'average_error', 'average_error_type': 'C1',
            'lower_limit': -0.5, 'upper_limit': 0.5,
        }, {
            'company_id': self.company.id, 'info_type_code': '1007',
            'field_name': 'average_error', 'average_error_type': 'B1',
            'lower_limit': -0.5, 'upper_limit': 0.5,
        }])
        row = self._source(code='1007')
        self._detail(row, '正向-有功-C相-Imax1.0', '-0.700', '0.6', 1)
        self._detail(row, '正向-有功-B相-Imax1.0', '-0.800', '0.6', 2)
        row._eip_clean_rows()
        self.assertEqual(sorted(row.issue_ids.mapped('type_code')),
                         ['B1', 'C1'])

    def test_23_ac_analog_limit_issue(self):
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '2006',
            'field_name': 'measured_value', 'average_error_type': 'ⅠA',
            'lower_limit': 200.0, 'upper_limit': 250.0})
        row = self._source(
            code='2006', standard_value=220.0, error_value=0.5,
            pcb_code='SN2006')
        self._detail(row, '交流模拟量采集A相', '260.0', '0')
        row._eip_clean_rows()
        issue = row.issue_ids
        self.assertEqual(len(issue), 1)
        self.assertEqual(issue.kind, 'limit')
        self.assertEqual(issue.type_code, 'ⅠA')
        self.assertEqual(issue.field_name, 'measured_value')
        self.assertEqual(issue.actual_value, 260.0)

    # ------------------------------------------------------------------
    # other problems, NG, rebuild, freeze
    # ------------------------------------------------------------------

    def test_30_no_aging_point_is_an_other_issue(self):
        row = self._source(code='1011', pcb_code=False)
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        issue = row.issue_ids
        self.assertEqual(len(issue), 1)
        self.assertEqual(issue.kind, 'other')
        self.assertEqual(issue.message, 'no aging temperature points collected')

    def test_31_untranslated_details_are_an_other_issue(self):
        row = self._source(code='1007')
        self._detail(row, '无法识别的项目', '0.01', '0')
        row._eip_clean_rows()
        issue = row.issue_ids
        self.assertEqual(len(issue), 1)
        self.assertEqual(issue.kind, 'other')
        self.assertIn('no valid error-detail lines', issue.message)

    def test_40_ng_is_not_an_issue(self):
        """The conclusion gate rejects the row but leaves no issue: NG
        lives in the conclusion column, uncleaned rows included."""
        row = self._full_1002(conclusion=1)
        row._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertIn('conclusion failed: 1', row.clean_note)
        self.assertFalse(row.issue_ids)

    def test_41_ng_and_missing_overlap(self):
        row = self._source(conclusion=1)
        row._eip_clean_rows()
        self.assertIn('conclusion failed: 1', row.clean_note)
        self.assertEqual(len(row.issue_ids), 3)
        self.assertEqual(set(row.issue_ids.mapped('kind')), {'missing'})

    def test_50_re_clean_rebuilds_the_whole_set(self):
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '1002',
            'field_name': 'leakage_current',
            'lower_limit': 0.0, 'upper_limit': 5.0})
        row = self._source()  # 3 missing
        row._eip_clean_rows()
        self.assertEqual(len(row.issue_ids), 3)
        # filled by hand, but now out of limit: the old set is gone
        row.write({'check_duration': '60', 'testing_voltage': '4200',
                   'leakage_current': 9.0})
        row._eip_clean_rows()
        self.assertEqual(row.issue_ids.mapped('kind'), ['limit'])
        # in limit: nothing left
        row.write({'leakage_current': 2.0})
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        self.assertFalse(self.Issue.search([('source_id', '=', row.id)]))

    def test_51_deleted_row_takes_its_issues_along(self):
        row = self._source()
        row._eip_clean_rows()
        issue = row.issue_ids
        row.unlink()
        self.assertFalse(issue.exists())

    def test_60_delivered_row_keeps_its_issues(self):
        """Delivered rows are never re-judged: the issue set of their
        last pass stays as it was."""
        self.Rule.create({
            'company_id': self.company.id, 'info_type_code': '1002',
            'field_name': 'leakage_current',
            'lower_limit': 0.0, 'upper_limit': 5.0})
        row = self._full_1002(leakage_current=7.5)
        row._eip_clean_rows()
        issue = row.issue_ids
        self.assertEqual(len(issue), 1)
        # delivered by hand (the endpoint stamps state + upload_time)
        row.write({'state': 'delivered',
                   'upload_time': fields.Datetime.now()})
        self.Rule.search([('info_type_code', '=', '1002')]).unlink()
        row._eip_clean_rows()
        self.assertEqual(row.issue_ids, issue)
        self.assertEqual(issue.kind, 'limit')

    def test_61_uncleaned_row_has_no_issue(self):
        row = self._source()  # plenty missing, never cleansed
        self.assertEqual(row.state, 'pending')
        self.assertFalse(row.issue_ids)

    def test_62_qualified_row_has_no_issue(self):
        row = self._full_1002()
        row._eip_clean_rows()
        self.assertEqual(row.state, 'qualified')
        self.assertFalse(row.issue_ids)

    # ------------------------------------------------------------------
    # permission: a plain MRP user triggers the re-clean
    # ------------------------------------------------------------------

    def test_70_mrp_user_can_trigger_the_clean(self):
        """Issue rows are read-only for MRP users; the engine writes
        them as superuser, so a user's own re-clean does not fail on
        the access right."""
        user = self.env['res.users'].create({
            'name': 'EIP MRP User', 'login': 'eip_mrp_user_issues',
            'group_ids': [(4, self.env.ref('base.group_user').id),
                          (4, self.env.ref('mrp.group_mrp_user').id)],
        })
        user_env = self.env(user=user)
        self.assertFalse(user_env['sn.wsd.eip.clean.issue'].check_access_rights(
            'write', raise_exception=False))
        row = self._source()
        user_env['sn.wsd.eip.pass.record'].browse(row.id)._eip_clean_rows()
        self.assertEqual(row.state, 'rejected')
        self.assertEqual(len(row.issue_ids), 3)


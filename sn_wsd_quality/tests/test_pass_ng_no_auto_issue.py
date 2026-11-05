from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPassNgNoAutoIssue(TransactionCase):
    """NG 过站只落测试结果，不自动开质量问题单、不冻结（报修人工开单）。
    remove-auto-issue-and-station-type"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.defect = cls.env['sn.wsd.quality.defect.code'].create({
            'name': 'NAI Defect', 'code': 'NAID',
            'category': 'other', 'severity': 'minor',
        })

    def _issue_count(self, sn):
        identity = self.env['sn.wsd.serial.identity'].search(
            [('name', '=', sn)], limit=1)
        self.assertTrue(identity)
        return self.env['sn.wsd.quality.issue'].search_count([
            ('serial_identity_id', '=', identity.id)])

    def test_ng_with_defect_code_opens_no_issue(self):
        # spec: ng-rework/spec/NG 后可直接重过同工序（重入放宽）/NG 过站不自动开质量问题单
        self.env['sn.wsd.mes.test.result'].ingest_meter_test_result(
            'SN-NAI-1', result='ng',
            payload={'M_STR2': self.defect.code})
        self.assertEqual(self._issue_count('SN-NAI-1'), 0)

    def test_ng_without_defect_code_opens_no_issue(self):
        # spec: ng-rework/spec/NG 后可直接重过同工序（重入放宽）/NG 过站不自动开质量问题单
        self.env['sn.wsd.mes.test.result'].ingest_meter_test_result(
            'SN-NAI-2', result='ng')
        self.assertEqual(self._issue_count('SN-NAI-2'), 0)

"""Cleansing engine of the production-data collection pipeline.

Judges raw collection rows (three gates: required fields built in per
the spec field tables, failing conclusions built in, measured-value
limits from the rule table) and materialises the passing ones into
outbox snapshots. The payload is built here once -- spec field names,
types, precisions and date formats applied -- so the endpoint layer
stays a dumb FIFO server. The raw columns of a row are never rewritten;
corrections ride along at synthesis; re-cleansing supersedes old
qualified snapshots and delivered rows are frozen forever. The single
trigger is the manual per-work-order re-clean -- no cron, no auto
re-judgement.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# interfaces expanding to one snapshot per detail/point line
AGING_CODES = ('1011', '2010')
ERROR_DETAIL_CODES = ('1007', '2006')

# 1007 type codes <-> test names, both standards of the meter spec
# (platform-issued appendix data: the only Chinese allowed in source,
# dictionary precedent)
AVERAGE_ERROR_TYPE_NAMES = {
    # single phase, 13 and 20 standards
    '正向-有功-Imax1.0': 'D1',
    '正向-有功-Ib1.0': 'D2',
    '正向-有功-Ib0.5L': 'D3',
    '正向-有功-0.05Ib1.0': 'D4',
    '正向-有功-10Itr1.0': 'D2',
    '正向-有功-10Itr0.5L': 'D3',
    '正向-有功-Imin1.0': 'D4',
    # three phase, 13 and 20 standards
    '正向-有功-合元-Imax1.0': 'H1',
    '正向-有功-合元-Ib1.0': 'H2',
    '正向-有功-合元-Ib0.5L': 'H3',
    '正向-有功-合元-0.05Ib1.0': 'H4',
    '正向-有功-合元-10Itr1.0': 'H2',
    '正向-有功-合元-10Itr0.5L': 'H3',
    '正向-有功-合元-Imin1.0': 'H4',
    '正向-有功-A相-Imax1.0': 'A1',
    '正向-有功-A相-Ib1.0': 'A2',
    '正向-有功-A相-10Itr1.0': 'A2',
    '正向-有功-B相-Imax1.0': 'B1',
    '正向-有功-B相-Ib1.0': 'B2',
    '正向-有功-B相-10Itr1.0': 'B2',
    '正向-有功-C相-Imax1.0': 'C1',
    '正向-有功-C相-Ib1.0': 'C2',
    '正向-有功-C相-10Itr1.0': 'C2',
}

# 2006 AC-analog type codes per test name. Platform caveat: the 1-type
# concentrators / type-1 transformer terminals and the type-3
# transformer terminals share the same test names (the spec resolves
# them by device type, which the payload does not carry) -- type-3
# devices are labeled with the 1-codes and must be checked at joint
# testing.
AC_ANALOG_TYPE_NAMES = {
    '交流模拟量采集A相': 'ⅠA',
    '交流模拟量采集B相': 'ⅠB',
    '交流模拟量采集C相': 'ⅠC',
    '交流模拟量采集': 'Ⅱ1',
}

# payload fields every interface carries, spec order
BASE_PAYLOAD_FIELDS = [
    'STANDARD_VERSION', 'PRODUCTION_ORDER_ID', 'WORK_ORDER_CODE',
    'INFO_TYPE_CODE', 'DEVICE_NO', 'TEST_CODE', 'MODEL_CODE', 'PCB_CODE',
    'CHECK_TIME', 'CREATE_TIME', 'UPLOAD_TIME', 'CONCLUSION',
]

# spec field name -> (row column, formatter). text passes through;
# datetime keeps the stored wall time (device data joins on it);
# decN rounds to the spec precision and ships as a JSON number.
PAYLOAD_COLUMNS = {
    'TEST_NAME': ('test_name', 'text'),
    'CURRENT_VALUE': ('current_value', 'dec3'),
    'WARMING_ZONE': ('warming_zone', 'dec1'),
    'CONSTANT_TEMPERATURE_ZONE': ('constant_temperature_zone', 'dec1'),
    'WELDING_ZONE': ('welding_zone', 'dec1'),
    'COOLING_ZONE': ('cooling_zone', 'dec1'),
    'PREHEATING_AREA': ('preheating_area', 'dec1'),
    'STANDARD_VALUE': ('standard_value', 'dec1'),
    'CHECK_DURATION': ('check_duration', 'text'),
    'TESTING_VOLTAGE': ('testing_voltage', 'text'),
    'LEAKAGE_CURRENT': ('leakage_current', 'dec3'),
    'ALLOWABLE_ERROR': ('allowable_error', 'text'),
    'REAL_ERROR': ('real_error', 'dec3'),
    'SOFTWARE_VERSION': ('software_version', 'text'),
    'PLANT_CODE': ('plant_code', 'text'),
    'NAMEPLATE_CODE': ('nameplate_code', 'text'),
    'TABLE_NO': ('table_no', 'text'),
    'TABLE_ADDRESS': ('table_address', 'text'),
    'ASSET_MANAGEMENT_NO': ('asset_management_no', 'text'),
    'MEASURED_VALUE': ('measured_value', 'dec1'),
    'ERROR_VALUE': ('error_value', 'dec3'),
    'LOGIC_ADDRESS': ('logic_address', 'text'),
    'BUREAU_NUM': ('bureau_num', 'text'),
}

# per-interface payload additions on top of the base (the spec field
# tables; the test-process interfaces also carry TEST_NAME)
# row-level value columns the limit gate judges per interface (only
# fields whose limits are meaningful; type-dimension rules never apply
# to row-level fields)
VALUE_RULE_FIELDS = {
    '1002': ['check_duration', 'testing_voltage', 'leakage_current'],
    '1004': ['allowable_error', 'real_error'],
    '1005': ['current_value'],
    '2003': ['check_duration', 'testing_voltage', 'leakage_current'],
    '2004': ['plant_code', 'logic_address', 'bureau_num'],
    '2006': ['standard_value', 'error_value'],
    '2007': ['current_value'],
}

def _eip_float_or_none(raw):
    """Parse a raw value to float; empty / junk -> None."""
    if raw is None or raw == '':
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _eip_match_rule(rules, field_name, type_code=None):
    """Pick the limit rule for one field from the interface's rule
    list: exact type match first, then the empty-type fallback rule;
    None when nothing matches."""
    for rule in rules:
        if rule.field_name == field_name and type_code \
                and rule.average_error_type == type_code:
            return rule
    for rule in rules:
        if rule.field_name == field_name and not rule.average_error_type:
            return rule
    return None


INTERFACE_PAYLOAD_FIELDS = {
    '1001': [],
    '1002': ['TEST_NAME', 'CHECK_DURATION', 'TESTING_VOLTAGE',
             'LEAKAGE_CURRENT'],
    '1003': [],
    '1004': ['TEST_NAME', 'ALLOWABLE_ERROR', 'REAL_ERROR'],
    '1005': ['CURRENT_VALUE'],
    '1006': ['TEST_NAME'],
    '1007': ['TEST_NAME', 'AVERAGE_ERROR_TYPE', 'AVERAGE_ERROR'],
    '1008': ['TEST_NAME', 'SOFTWARE_VERSION', 'PLANT_CODE',
             'NAMEPLATE_CODE', 'TABLE_NO', 'TABLE_ADDRESS',
             'ASSET_MANAGEMENT_NO'],
    '1009': ['WARMING_ZONE', 'CONSTANT_TEMPERATURE_ZONE', 'WELDING_ZONE',
             'COOLING_ZONE'],
    '1010': ['PREHEATING_AREA', 'WELDING_ZONE'],
    '1011': [],
    '2001': [],
    '2002': [],
    '2003': ['TEST_NAME', 'CHECK_DURATION', 'TESTING_VOLTAGE',
             'LEAKAGE_CURRENT'],
    '2004': ['TEST_NAME', 'PLANT_CODE', 'LOGIC_ADDRESS', 'BUREAU_NUM'],
    '2005': ['TEST_NAME'],
    '2006': ['TEST_NAME', 'AVERAGE_ERROR_TYPE', 'STANDARD_VALUE',
             'MEASURED_VALUE', 'ERROR_VALUE'],
    '2007': ['CURRENT_VALUE'],
    '2008': ['WARMING_ZONE', 'CONSTANT_TEMPERATURE_ZONE', 'WELDING_ZONE',
             'COOLING_ZONE'],
    '2009': ['PREHEATING_AREA', 'WELDING_ZONE'],
    '2010': [],
}

# required row columns per interface, from the spec field tables.
# pipeline-guaranteed columns (info_type_code, standard_version,
# conclusion) are not re-judged; upload_time is stamped by delivery.
COMMON_REQUIRED = [
    'production_order_no', 'work_order_no', 'device_no', 'test_code',
    'model_code', 'check_time', 'create_time',
]
CLEAN_REQUIRED = {
    '1001': COMMON_REQUIRED + ['pcb_code'],
    '1002': COMMON_REQUIRED + ['pcb_code', 'test_name', 'check_duration',
                               'testing_voltage', 'leakage_current'],
    '1003': COMMON_REQUIRED + ['pcb_code'],
    '1004': COMMON_REQUIRED + ['pcb_code', 'test_name', 'allowable_error',
                               'real_error'],
    '1005': COMMON_REQUIRED + ['pcb_code', 'current_value'],
    '1006': COMMON_REQUIRED + ['pcb_code', 'test_name'],
    '1007': COMMON_REQUIRED + ['pcb_code', 'test_name'],
    '1008': COMMON_REQUIRED + ['pcb_code', 'test_name', 'software_version',
                               'plant_code', 'nameplate_code', 'table_no',
                               'table_address', 'asset_management_no'],
    '1009': COMMON_REQUIRED + ['pcb_code', 'warming_zone',
                               'constant_temperature_zone', 'welding_zone',
                               'cooling_zone'],
    '1010': COMMON_REQUIRED + ['pcb_code', 'preheating_area',
                               'welding_zone'],
    '1011': COMMON_REQUIRED,
    '2001': COMMON_REQUIRED + ['pcb_code'],
    '2002': COMMON_REQUIRED + ['pcb_code'],
    '2003': COMMON_REQUIRED + ['pcb_code', 'test_name', 'check_duration',
                               'testing_voltage', 'leakage_current'],
    '2004': COMMON_REQUIRED + ['pcb_code', 'test_name', 'plant_code',
                               'logic_address', 'bureau_num'],
    '2005': COMMON_REQUIRED + ['pcb_code', 'test_name'],
    '2006': COMMON_REQUIRED + ['pcb_code', 'test_name', 'standard_value',
                               'error_value'],
    '2007': COMMON_REQUIRED + ['pcb_code', 'current_value'],
    '2008': COMMON_REQUIRED + ['pcb_code', 'warming_zone',
                               'constant_temperature_zone', 'welding_zone',
                               'cooling_zone'],
    '2009': COMMON_REQUIRED + ['pcb_code', 'preheating_area',
                               'welding_zone'],
    '2010': COMMON_REQUIRED,
}
CLEAN_REQUIRED.update({
})


def _eip_add_issue(issues, issue):
    """Collect one structured problem next to its text; a caller that
    passes no list only wanted the text."""
    if issues is not None:
        issues.append(issue)


def _fmt_dt(value):
    """Spec datetime format ('yyyy-MM-dd HH:mm:ss'); the stored wall
    time is used verbatim -- device packets and passes join on it."""
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else ''


class EipPassRecordClean(models.Model):
    _inherit = 'sn.wsd.eip.pass.record'

    # ------------------------------------------------------------------
    # gates + synthesis
    # ------------------------------------------------------------------
    def _eip_clean_rows(self):
        """Judge and snapshot ``self`` (triggered per work order by the
        manual wizard, or on the rows a batch correction just fixed).
        Delivered rows are skipped (frozen)."""
        rules_by_company = {}
        for rule in self.env['sn.wsd.eip.clean.rule'].search([]):
            rules_by_company.setdefault(rule.company_id.id, {}).setdefault(
                rule.info_type_code, []).append(rule)
        family_by_code = {
            item.code: item.family
            for item in self.env['sn.wsd.eip.collect.interface'].search([])}
        Outbox = self.env['sn.wsd.eip.collect.outbox']
        for record in self:
            if record.state == 'delivered':
                continue
            record._eip_backfill_family()
            code = record.info_type_code
            # archive corrections overlay the raw columns before the
            # gates: the row is judged on raw + corrections (synthesis
            # order), the raw columns themselves stay untouched
            fixes = {fix.field_name: fix.value for fix in record.fix_ids}
            problems = []
            # the structured twin of the problem texts: one entry per
            # problem, written as clean-issue rows once judged (NG is
            # not an issue, the conclusion column says it)
            issues = []
            for fname in CLEAN_REQUIRED.get(code, []):
                if not fixes.get(fname, record[fname]):
                    problems.append('missing required: %s' % fname)
                    issues.append({
                        'kind': 'missing',
                        'field_name': fname,
                        'message': problems[-1],
                    })
            if record.conclusion == 1:
                # the conclusion gate: a failing test never ships
                problems.append('conclusion failed: 1')
            rules = rules_by_company.get(
                record.company_id.id, {}).get(code, [])
            for field_name in VALUE_RULE_FIELDS.get(code, []):
                rule = _eip_match_rule(rules, field_name, None)
                problem = rule and rule._eip_limit_problem(record[field_name])
                if problem:
                    problems.append('limit fail: %s' % problem)
                    issues.append({
                        'kind': 'limit',
                        'field_name': field_name,
                        'actual_value': record[field_name],
                        'lower_limit': rule.lower_limit,
                        'upper_limit': rule.upper_limit,
                        'message': problems[-1],
                    })
            now = fields.Datetime.now()
            payloads = []
            if code in AGING_CODES:
                payloads = record._eip_aging_payloads(
                    now, problems, fixes, issues)
            elif code == '1007':
                payloads = record._eip_error_detail_payloads(
                    now, problems, fixes, rules, issues)
            elif code == '2006':
                payloads = record._eip_ac_analog_payloads(
                    now, problems, fixes, rules, issues)
            elif code in CLEAN_REQUIRED:
                payloads = [record._eip_standard_payload(code, now, fixes)]
            else:
                problems.append('interface %s has no payload definition' %
                                code)
                issues.append({'kind': 'other', 'message': problems[-1]})
            if not payloads and not problems:
                problems.append('no deliverable records')
                issues.append({'kind': 'other', 'message': problems[-1]})
            # the issue set mirrors the latest pass: rebuilt whole
            record.issue_ids.sudo().unlink()
            if issues:
                self.env['sn.wsd.eip.clean.issue'].sudo().create([
                    dict(issue, source_id=record.id) for issue in issues])
            # re-generation replaces stale snapshots: undelivered ones are
            # deleted outright (user decision 2026-11-27, no superseded
            # state); delivered ones are frozen and never touched here
            record.outbox_ids.filtered(
                lambda snap: snap.state == 'qualified'
            ).unlink()
            if problems or not payloads:
                record.write({
                    'state': 'rejected',
                    'clean_time': now,
                    'clean_note': '; '.join(problems)[:2000]
                    or 'no deliverable records',
                })
            else:
                Outbox.create([{
                    'company_id': record.company_id.id,
                    'source_id': record.id,
                    'info_type_code': code,
                    'family': family_by_code.get(code, 'meter'),
                    'test_code': payload.get('TEST_CODE'),
                    'payload': payload,
                } for payload in payloads])
                record.write({
                    'state': 'qualified',
                    'clean_time': now,
                    'clean_note': False,
                })

    def _eip_standard_payload(self, code, upload_time, fixes=None):
        """One data record built from the row columns with the archive
        corrections overlaid (non-expansion interfaces)."""
        fixes = fixes or {}
        payload = self._eip_base_payload(upload_time, fixes=fixes)
        for spec_name in INTERFACE_PAYLOAD_FIELDS.get(code, []):
            column, kind = PAYLOAD_COLUMNS[spec_name]
            payload[spec_name] = self._eip_format_value(
                fixes.get(column, self[column]), kind)
        return payload

    def _eip_base_payload(self, upload_time, with_pcb=True, fixes=None):
        fixes = fixes or {}
        payload = {
            'STANDARD_VERSION': int(self.standard_version or 2),
            'PRODUCTION_ORDER_ID': self.production_order_no or '',
            'WORK_ORDER_CODE': self.work_order_no or '',
            'INFO_TYPE_CODE': self.info_type_code or '',
            'DEVICE_NO': self.device_no or '',
            'TEST_CODE': self.test_code or '',
            'MODEL_CODE': fixes.get('model_code', self.model_code) or '',
            'PCB_CODE': self.pcb_code or '',
            'CHECK_TIME': _fmt_dt(self.check_time),
            'CREATE_TIME': _fmt_dt(self.create_time),
            'UPLOAD_TIME': _fmt_dt(upload_time),
            'CONCLUSION': int(self.conclusion or 0),
        }
        if not with_pcb:
            payload.pop('PCB_CODE')
        return payload

    def _eip_format_value(self, raw, kind):
        if kind == 'text':
            return str(raw or '')
        if kind == 'datetime':
            return _fmt_dt(raw)
        if kind == 'date':
            return raw.strftime('%Y-%m-%d') if raw else ''
        if kind == 'int':
            return int(round(float(raw or 0)))
        value = float(raw or 0.0)
        if kind == 'dec1':
            return round(value, 1)
        if kind == 'dec2':
            return round(value, 2)
        return round(value, 3)

    def _eip_error_detail_payloads(self, upload_time, problems, fixes=None,
                                   rules=None, issues=None):
        """1007: one record per test-detail line. Each line is
        translated to (type code, test name, value) by its
        detail_translate mapping row -- transform code first, the
        platform name table as the fallback; lines without any
        translation are skipped. Per-type limit rules judge the
        cleansed value; an out-of-limit detail rejects the whole
        row."""
        translations = {}
        for mapping in self.env['sn.wsd.eip.value.mapping'].search([
                ('info_type_code', '=', '1007'),
                ('source_kind', '=', 'detail_translate'),
                ('company_id', 'in', [self.company_id.id, False])]):
            translations.setdefault(
                (mapping.source_key or '').strip(), []).append(mapping)
        payloads = []
        skipped = []
        for index, line in enumerate(self.line_ids.filtered(
                lambda item: item.line_type == 'test_detail'), 1):
            name = (line.project_name or '').strip()
            try:
                value = float(str(line.actual_value).strip())
            except (TypeError, ValueError):
                value = None
            candidates = translations.get(name) or []
            picked = None
            if candidates:
                exact = [m for m in candidates
                         if _eip_float_or_none(m.match_up_limit)
                         is not None
                         and _eip_float_or_none(m.match_up_limit)
                         == _eip_float_or_none(line.upper_limit)]
                if exact:
                    picked = exact[0]
                elif len(candidates) == 1 and _eip_float_or_none(
                        candidates[0].match_up_limit) is None:
                    picked = candidates[0]
            type_code = test_name = None
            if picked:
                type_code = picked.target_type
                test_name = picked.target_test_name
                if picked.transform_code:
                    number, err = picked._eip_call_transform(
                        line.actual_value, line.lower_limit,
                        line.upper_limit, name, index,
                        {'project_name': line.project_name,
                         'lower_limit': line.lower_limit,
                         'upper_limit': line.upper_limit,
                         'actual_value': line.actual_value})
                    if err:
                        skipped.append('%s: %s' % (name, err))
                        continue
                    if number is None:
                        skipped.append('%s: transform skipped' % name)
                        continue
                    value = number
            else:
                type_code = AVERAGE_ERROR_TYPE_NAMES.get(name)
                test_name = name
            if value is None:
                skipped.append('%s: empty value' % name)
                continue
            if not type_code:
                skipped.append('%s: no translation' % name)
                continue
            rule = _eip_match_rule(rules or [], 'average_error', type_code)
            if rule:
                problem = rule._eip_limit_problem(value)
                if problem:
                    problems.append('limit fail: %s' % problem)
                    _eip_add_issue(issues, {
                        'kind': 'limit',
                        'line_id': line.id,
                        'field_name': 'average_error',
                        'type_code': type_code,
                        'actual_value': value,
                        'lower_limit': rule.lower_limit,
                        'upper_limit': rule.upper_limit,
                        'message': problems[-1],
                    })
            line.cleansed_value = str(round(value, 3))
            payload = self._eip_base_payload(
                upload_time, with_pcb=True, fixes=fixes)
            payload['TEST_NAME'] = test_name
            payload['AVERAGE_ERROR_TYPE'] = type_code
            payload['AVERAGE_ERROR'] = round(value, 3)
            payloads.append(payload)
        if not payloads:
            problems.append(
                'no valid error-detail lines (untranslated names or empty '
                'values)' + ('; skipped: %s' % '; '.join(skipped[:3])
                             if skipped else ''))
            _eip_add_issue(issues, {
                'kind': 'other', 'message': problems[-1]})
        return payloads

    def _eip_ac_analog_payloads(self, upload_time, problems, fixes=None,
                                rules=None, issues=None):
        """2006: one record per test-detail line -- the type code and
        measured value come from the detail_translate mapping row
        (transform code first, platform name table fallback), standard
        and error values stay row columns. Per-type limit rules judge
        the measured value."""
        translations = {}
        for mapping in self.env['sn.wsd.eip.value.mapping'].search([
                ('info_type_code', '=', '2006'),
                ('source_kind', '=', 'detail_translate'),
                ('company_id', 'in', [self.company_id.id, False])]):
            translations.setdefault(
                (mapping.source_key or '').strip(), []).append(mapping)
        payloads = []
        skipped = []
        for index, line in enumerate(self.line_ids.filtered(
                lambda item: item.line_type == 'test_detail'), 1):
            name = (line.project_name or '').strip()
            try:
                measured = float(str(line.actual_value).strip())
            except (TypeError, ValueError):
                measured = None
            candidates = translations.get(name) or []
            picked = None
            if candidates:
                exact = [m for m in candidates
                         if _eip_float_or_none(m.match_up_limit)
                         is not None
                         and _eip_float_or_none(m.match_up_limit)
                         == _eip_float_or_none(line.upper_limit)]
                if exact:
                    picked = exact[0]
                elif len(candidates) == 1 and _eip_float_or_none(
                        candidates[0].match_up_limit) is None:
                    picked = candidates[0]
            type_code = test_name = None
            if picked:
                type_code = picked.target_type
                test_name = picked.target_test_name
                if picked.transform_code:
                    number, err = picked._eip_call_transform(
                        line.actual_value, line.lower_limit,
                        line.upper_limit, name, index,
                        {'project_name': line.project_name,
                         'lower_limit': line.lower_limit,
                         'upper_limit': line.upper_limit,
                         'actual_value': line.actual_value})
                    if err:
                        skipped.append('%s: %s' % (name, err))
                        continue
                    if number is None:
                        skipped.append('%s: transform skipped' % name)
                        continue
                    measured = number
            else:
                type_code = AC_ANALOG_TYPE_NAMES.get(name)
                test_name = name
            if measured is None:
                skipped.append('%s: empty value' % name)
                continue
            if not type_code:
                skipped.append('%s: no translation' % name)
                continue
            rule = _eip_match_rule(rules or [], 'measured_value', type_code)
            if rule:
                problem = rule._eip_limit_problem(measured)
                if problem:
                    problems.append('limit fail: %s' % problem)
                    _eip_add_issue(issues, {
                        'kind': 'limit',
                        'line_id': line.id,
                        'field_name': 'measured_value',
                        'type_code': type_code,
                        'actual_value': measured,
                        'lower_limit': rule.lower_limit,
                        'upper_limit': rule.upper_limit,
                        'message': problems[-1],
                    })
            line.cleansed_value = str(round(measured, 1))
            payload = self._eip_base_payload(
                upload_time, with_pcb=True, fixes=fixes)
            payload['TEST_NAME'] = test_name
            payload['AVERAGE_ERROR_TYPE'] = type_code
            payload['STANDARD_VALUE'] = round(
                self.standard_value or 0.0, 1)
            payload['MEASURED_VALUE'] = round(measured, 1)
            payload['ERROR_VALUE'] = round(self.error_value or 0.0, 2)
            payloads.append(payload)
        if not payloads:
            problems.append(
                'no valid ac-analog lines (untranslated names or empty '
                'values)' + ('; skipped: %s' % '; '.join(skipped[:3])
                             if skipped else ''))
            _eip_add_issue(issues, {
                'kind': 'other', 'message': problems[-1]})
        return payloads

    def _eip_aging_payloads(self, upload_time, problems, fixes=None,
                            issues=None):
        """1011/2010: one record per aging point of the window (the spec
        wants >= 6 points per order -- volume is a process duty, the
        engine ships what the window holds)."""
        payloads = []
        for point in self.line_ids.filtered(
                lambda item: item.line_type == 'aging_point'):
            try:
                value = float(str(point.actual_value).strip())
            except (TypeError, ValueError):
                value = None
            if value is None:
                continue
            payload = self._eip_base_payload(
                upload_time, with_pcb=False, fixes=fixes)
            payload['AGINGROOM_TEMPERATURE'] = round(value, 1)
            payload['STANDARD_VALUE'] = round(
                self.standard_value or 0.0, 1)
            if point.point_time:
                payload['CHECK_TIME'] = _fmt_dt(point.point_time)
            payloads.append(payload)
        if not payloads:
            problems.append('no aging temperature points collected')
            _eip_add_issue(issues, {
                'kind': 'other', 'message': problems[-1]})
        return payloads

    # ------------------------------------------------------------------
    # trigger (manual, per work order -- the only cleansing entry)
    # ------------------------------------------------------------------
    @api.model
    def _eip_clean_by_order(self, work_order_no):
        """Cleanse / re-clean every collection row of one work order:
        the single manual trigger (no cron, no auto re-clean). Returns
        the rows judged."""
        rows = self.search([
            ('work_order_no', '=', work_order_no),
            ('company_id', '=', self.env.company.id),
        ])
        if not rows:
            raise UserError(_(
                'No collection rows for work order %s.', work_order_no))
        rows._eip_clean_rows()
        return rows

    def action_eip_re_clean(self):
        """Cleanse the selected rows in place (used by the batch
        correction wizard, which owns the rows it corrected)."""
        self._eip_clean_rows()
        return True

    def action_open_correction_wizard(self):
        """Open the correction wizard scoped to this row (server-side
        context build -- the button context cannot call str())."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Correction',
            'res_model': 'sn.wsd.eip.clean.fix.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_record_ids': str(self.id)},
        }

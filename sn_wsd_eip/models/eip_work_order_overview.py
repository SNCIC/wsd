"""Work order data overview: the server side.

One page shows every piece of collected EIP production data of one
work order (the MES order number): process steps, raw-material
inspection, packing storage, shipping. Two model methods feed the OWL
client action:

* ``get_overview`` -- header + summary tables, aggregated in SQL;
* ``get_detail`` -- one page of the records behind a clicked number.

Performance contract (spec "performance"): the summary is aggregated
in the database over the few columns it needs and never loads a
collection row into the ORM; the detail is paginated on the server and
the problems of a page are read in one query. The query count of both
calls is fixed, it does not grow with the row count.

The MES order number is the work order key and nothing more: it
is matched against the work order column of the collected rows and
rides in the payload. The page derives nothing else through the MES
order (user decision 2026-11-26).

Counting rule of the pass summary: units are SN, deduplicated -- one
unit tested three times is one unit. Every flag column counts the
units having at least one row in that state, so the flag columns
overlap (a unit can be NG and missing a required field) and must not
be summed.
"""
from collections import defaultdict
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .eip_clean_engine import CLEAN_REQUIRED, VALUE_RULE_FIELDS

# the value columns of each interface, in display order (user request
# 2026-11-27: the detail table shows every column of the clicked step,
# and only those). A step absent here shows no value columns.
DETAIL_CODE_COLUMNS = {
    '1002': ('check_duration', 'testing_voltage', 'leakage_current'),
    '1004': ('allowable_error', 'real_error'),
    '1005': ('current_value',),
    '1007': ('average_error_type', 'average_error', 'software_version'),
    '1008': ('software_version', 'plant_code', 'nameplate_code',
             'table_no', 'table_address', 'asset_management_no'),
    '1009': ('warming_zone', 'constant_temperature_zone',
             'welding_zone', 'cooling_zone'),
    '1010': ('preheating_area', 'welding_zone'),
    '1011': ('agingroom_temperature', 'standard_value'),
    '2003': ('check_duration', 'testing_voltage', 'leakage_current'),
    '2004': ('plant_code', 'logic_address', 'bureau_num'),
    '2006': ('average_error_type', 'standard_value', 'measured_value',
             'error_value'),
    '2007': ('current_value',),
    '2008': ('warming_zone', 'constant_temperature_zone',
             'welding_zone', 'cooling_zone'),
    '2009': ('preheating_area', 'welding_zone'),
    '2010': ('agingroom_temperature', 'standard_value'),
}

DETAIL_PAGE_SIZE = 80

# clickable numbers of each tab
PASS_FLAGS = ('units', 'ng', 'missing', 'limit', 'pending', 'rejected')
DOC_FLAGS = ('all', 'ng', 'pending', 'delivered')
SHIP_FLAGS = ('all', 'shipped', 'not_shipped', 'pending', 'delivered')
TAB_FLAGS = {'pass': PASS_FLAGS, 'raw': DOC_FLAGS, 'pack': DOC_FLAGS,
             'ship': SHIP_FLAGS}

# what an interface code collects. Process steps are the EIP interface
# codes of the two production-data specs -- nothing to do with the
# route of the MES order (user decision 2026-11-26).
PACK_CODES = ('1090', '2090')
SHIP_CODES = ('1091', '2091')
PROCESS_RANGES = {'meter': (1001, 1011), 'collector': (2001, 2010)}
RAW_RANGES = {'meter': (1012, 1018), 'collector': (2011, 2014)}


def _interface_kind(code, family):
    if code in PACK_CODES:
        return 'pack'
    if code in SHIP_CODES:
        return 'ship'
    if code.endswith('-REPORT'):
        return 'report'
    try:
        number = int(code)
    except (TypeError, ValueError):
        return 'other'
    for kind, ranges in (('pass', PROCESS_RANGES), ('raw', RAW_RANGES)):
        low, high = ranges.get(family, (0, -1))
        if low <= number <= high:
            return kind
    return 'other'


def _code_family(code):
    """Spec family an interface code belongs to by its first digit
    (1xxx meters, 2xxx collection devices)."""
    return 'collector' if str(code or '')[:1] == '2' else 'meter'


TAB_MODELS = {
    'pass': 'sn.wsd.eip.pass.record',
    'raw': 'sn.wsd.eip.raw.record',
    'pack': 'sn.wsd.eip.pack.record',
    'ship': 'sn.wsd.eip.ship.record',
}

# columns read per document tab
DOC_FIELDS = {
    'raw': ['test_code', 'material_check_batch', 'material_batch',
            'check_time', 'conclusion', 'state'],
    'pack': ['test_code', 'nameplate_code', 'number', 'storage_date',
             'conclusion', 'state'],
    'ship': ['test_code', 'nameplate_start', 'nameplate_final', 'number',
             'deliver_date', 'deliver_status', 'state'],
}

# document tab flags -> domain on top of work order + interface code
DOC_FLAG_DOMAINS = {
    'raw': {'all': [], 'ng': [('conclusion', '=', 1)],
            'pending': [('state', '=', 'pending')],
            'delivered': [('state', '=', 'delivered')]},
    'pack': {'all': [], 'ng': [('conclusion', '=', 1)],
             'pending': [('state', '=', 'pending')],
             'delivered': [('state', '=', 'delivered')]},
    'ship': {'all': [], 'shipped': [('deliver_status', '=', '1')],
             'not_shipped': [('deliver_status', '=', '0')],
             'pending': [('state', '=', 'pending')],
             'delivered': [('state', '=', 'delivered')]},
}

# the problem kinds a pass detail page lists row by row
PASS_FLAG_KINDS = {'missing': 'missing', 'limit': 'limit'}

# row filter of one pass flag, on alias r. missing / limit read the
# combined flags: the persisted judgement of judged rows, the live
# evaluation of pending ones (temp table built by _eip_prepare_live)
_PASS_FLAG_SQL = {
    'units': '',
    'ng': ' AND r.conclusion = 1',
    'missing': (' AND COALESCE(lf.has_missing, pi.has_missing, false)'),
    'limit': (' AND COALESCE(lf.has_limit, pi.has_limit, false)'),
    'pending': " AND r.state = 'pending'",
    'rejected': " AND r.state = 'rejected'",
}

# every wide-table value column the detail table shows (user request
# 2026-11-27: all columns, every step; a column the step does not use
# shows a dash)
DETAIL_VALUE_COLUMNS = (
    'current_value', 'warming_zone', 'constant_temperature_zone',
    'welding_zone', 'cooling_zone', 'preheating_area',
    'agingroom_temperature', 'standard_value', 'check_duration',
    'testing_voltage', 'leakage_current', 'allowable_error',
    'real_error', 'average_error_type', 'average_error',
    'software_version', 'plant_code', 'nameplate_code', 'table_no',
    'table_address', 'asset_management_no', 'measured_value',
    'error_value', 'logic_address', 'bureau_num',
)

# detail-expansion interfaces: their per-type limit gate needs the
# translation/transform machinery, so it is only judged when the rows
# are generated; until then such units are neither qualified nor
# counted as out of limit
LIVE_UNKNOWN_CODES = ('1007', '2006')

LIVE_FLAG_TABLE = 'eip_overview_live_flags'


# ``{identity}`` is the SN identity table, filled in at call time.
# The units CTE is the heart: one row per (step, SN) -- a unit tested
# three times is one unit -- carrying "has any row in that state" flags.
# Every flag column then counts units, so the columns overlap (a unit
# can be NG and missing a required field) and must not be summed.
_PASS_SUMMARY = (
    "WITH src AS ("
    "  SELECT r.id, r.info_type_code, r.state, r.conclusion, "
    "         r.check_time, r.production_order_no, r.test_name,"
    # dedupe key: the SN number itself. Taken from the identity while
    # the row is linked, else from the snapshot column (clear-pass
    # drops the link, the snapshot stays) -- a unit is one unit either way
    "         COALESCE(si.name, r.sn_name) AS sn_key"
    "  FROM sn_wsd_eip_pass_record r"
    "  LEFT JOIN {identity} si ON si.id = r.serial_identity_id"
    "  WHERE r.company_id = %(company)s AND r.work_order_no = %(wo)s), "
    # per-row problem flags: the persisted judgement of judged rows
    # merged with the live evaluation of pending ones (see
    # _eip_prepare_live). A row with two problems shows twice in the
    # joins, bool_or does not care; coalesce keeps NOT (...) honest.
    "flags AS ("
    "  SELECT s.id, "
    "         COALESCE(pi.has_missing, lf.has_missing, false) AS missing,"
    "         COALESCE(pi.has_limit, lf.has_limit, false) AS over_limit,"
    "         COALESCE(lf.unknown_limit, false) AS unknown "
    "  FROM src s "
    "  LEFT JOIN (SELECT i.source_id, "
    "                    bool_or(i.kind = 'missing') AS has_missing, "
    "                    bool_or(i.kind = 'limit') AS has_limit "
    "             FROM sn_wsd_eip_clean_issue i GROUP BY i.source_id)"
    "           pi ON pi.source_id = s.id "
    "  LEFT JOIN " + LIVE_FLAG_TABLE + " lf ON lf.id = s.id), "
    "units AS ("
    "  SELECT s.info_type_code AS code, "
    "         s.sn_key AS sn_key, "
    "         COALESCE(bool_or(s.conclusion = 1), false) AS ng, "
    "         COALESCE(bool_or(f.missing), false) AS missing, "
    "         COALESCE(bool_or(f.over_limit), false) AS over_limit, "
    "         COALESCE(bool_or(s.state = 'pending'), false) AS pending, "
    "         COALESCE(bool_or(s.state = 'rejected'), false) AS rejected, "
    "         COALESCE(bool_or(f.unknown), false) AS unknown "
    "  FROM src s JOIN flags f ON f.id = s.id"
    "  GROUP BY s.info_type_code, s.sn_key), "
    "steps AS ("
    "  SELECT info_type_code, MAX(test_name) AS test_name,"
    "         MIN(check_time) AS first_time, MAX(check_time) AS last_time,"
    "         MAX(production_order_no) AS production_order_no "
    "  FROM src GROUP BY info_type_code) "
    "SELECT n.info_type_code, n.test_name, "
    "       COUNT(u.sn_key), "
    "       COUNT(u.sn_key) FILTER (WHERE u.ng), "
    "       COUNT(u.sn_key) FILTER (WHERE u.missing), "
    "       COUNT(u.sn_key) FILTER (WHERE u.over_limit), "
    "       COUNT(u.sn_key) FILTER (WHERE u.pending), "
    "       COUNT(u.sn_key) FILTER (WHERE u.rejected), "
    "       COUNT(u.sn_key) FILTER (WHERE NOT (u.ng OR u.missing "
    "           OR u.over_limit OR u.rejected) AND NOT u.unknown), "
    "       n.first_time, n.last_time, n.production_order_no "
    "FROM steps n JOIN units u ON u.code = n.info_type_code "
    "GROUP BY n.info_type_code, n.test_name, n.first_time, n.last_time, "
    "         n.production_order_no")


class EipPassRecordOverview(models.Model):
    _inherit = 'sn.wsd.eip.pass.record'

    _company_work_order_idx = models.Index('(company_id, work_order_no)')

    # ------------------------------------------------------------------
    # summary
    # ------------------------------------------------------------------
    @api.model
    def get_overview(self, work_order_no):
        """Header + summary tables of one work order. Raises when the
        work order has no collected data at all."""
        work_order_no = (work_order_no or '').strip()
        if not work_order_no:
            raise UserError(_('Type a work order number.'))
        cr = self.env.cr
        params = {'company': self.env.company.id, 'wo': work_order_no}
        docs = "(company_id = %(company)s AND work_order_no = %(wo)s)"
        # raw SQL below: flush this transaction's pending writes first
        # (a cleansing that just ran, a delivery stamp)
        self.env.flush_all()
        # live judgement of the pending rows, read-only (see the
        # helper): the summary merges it with the persisted judgement
        self._eip_prepare_live(params)
        # the summary collapses the rows into one per (step, SN): a
        # hash aggregate over hundreds of thousands of groups that the
        # default work_mem spills to disk (about three times slower on
        # the benchmark). Scoped to this transaction / request.
        cr.execute("SET LOCAL work_mem = '128MB'")
        cr.execute(_PASS_SUMMARY.format(
            identity=self.env['sn.wsd.serial.identity']._table),
            params)
        pass_rows = cr.fetchall()
        cr.execute(
            "SELECT info_type_code, COUNT(*), "
            "       COUNT(*) FILTER (WHERE conclusion = 1), "
            "       COUNT(*) FILTER (WHERE state = 'pending'), "
            "       COUNT(*) FILTER (WHERE state = 'delivered') "
            "FROM sn_wsd_eip_raw_record WHERE " + docs + " "
            "GROUP BY info_type_code ORDER BY info_type_code", params)
        raw_rows = cr.fetchall()
        cr.execute(
            "SELECT info_type_code, COUNT(*), COALESCE(SUM(number), 0), "
            "       COALESCE(SUM(number) FILTER (WHERE conclusion = 1), 0),"
            "       COUNT(*) FILTER (WHERE state = 'pending'), "
            "       COUNT(*) FILTER (WHERE state = 'delivered') "
            "FROM sn_wsd_eip_pack_record WHERE " + docs + " "
            "GROUP BY info_type_code ORDER BY info_type_code", params)
        pack_rows = cr.fetchall()
        cr.execute(
            "SELECT info_type_code, COUNT(*), COALESCE(SUM(number), 0), "
            "       COUNT(*) FILTER (WHERE deliver_status = '1'), "
            "       COUNT(*) FILTER (WHERE deliver_status = '0'), "
            "       COUNT(*) FILTER (WHERE state = 'pending'), "
            "       COUNT(*) FILTER (WHERE state = 'delivered') "
            "FROM sn_wsd_eip_ship_record WHERE " + docs + " "
            "GROUP BY info_type_code ORDER BY info_type_code", params)
        ship_rows = cr.fetchall()
        cr.execute(
            "SELECT procedure_code, COUNT(*) FROM sn_wsd_eip_raw_report "
            "WHERE company_id = %(company)s "
            "AND production_work_no = %(wo)s "
            "GROUP BY procedure_code", params)
        # reports carry the inspection procedure they belong to: one
        # count per raw-inspection interface code
        report_counts = dict(cr.fetchall())
        if not (pass_rows or raw_rows or pack_rows or ship_rows):
            raise UserError(_(
                'No collected data for work order %s.', work_order_no))

        # every enabled interface of the work order's spec family is
        # listed, collected or not; the four tabs always show
        registry = self._overview_registry()
        families = self._overview_families(
            pass_rows, raw_rows, pack_rows, ship_rows)
        # data on a code the registry does not know still gets a name
        extra_codes = sorted(
            {row[0] for row in pass_rows + raw_rows + pack_rows
             + ship_rows} - set(registry))
        names = {code: registry[code][0] for code in registry}
        # one grouped read instead of search + read
        names.update({
            code: name
            for code, name, _count in self.env[
                'sn.wsd.eip.collect.interface']._read_group(
                [('code', 'in', extra_codes)],
                ['code', 'name'], ['__count'])} if extra_codes else {})
        return {
            'work_order_no': work_order_no,
            'header': self._overview_header(pass_rows, params),
            'tabs': ['pass', 'raw', 'pack', 'ship'],
            'pass': self._overview_pass_rows(pass_rows, names, families),
            'raw': self._overview_doc_rows(
                raw_rows, names, families, 'raw', report_counts),
            'pack': self._overview_doc_rows(
                pack_rows, names, families, 'pack'),
            'ship': self._overview_doc_rows(
                ship_rows, names, families, 'ship'),
        }

    def _overview_registry(self):
        """Enabled collect interfaces: code -> (name, family), code
        order. One grouped read."""
        return {
            code: (name, family)
            for code, name, family, _count in self.env[
                'sn.wsd.eip.collect.interface']._read_group(
                [], ['code', 'name', 'family'], ['__count'])}

    def _overview_families(self, pass_rows, raw_rows, pack_rows,
                           ship_rows):
        """Spec families (meter / collector) the work order covers,
        from the interface codes it has data on (1xxx / 2xxx); meters
        when the picture is unclear."""
        families = {_code_family(row[0]) for row in
                    pass_rows + raw_rows + pack_rows + ship_rows}
        return sorted(families) or ['meter']

    def _overview_header(self, pass_rows, params):
        """Head line: production order and first / last check, all
        read off the collected rows themselves. The MES order number
        is only the work order key here -- nothing is looked up
        through the MES order."""
        production_order_no = ''
        first_time = last_time = None
        planned_qty = None
        if pass_rows:
            first = pass_rows[0]
            # code, name, units, ng, missing, limit, pending, rejected,
            # qualified, first_time, last_time, production_order_no
            first_time, last_time = first[9], first[10]
            production_order_no = first[11] or ''
        else:
            self.env.cr.execute(
                "SELECT production_order_no FROM ("
                "  SELECT production_order_no FROM sn_wsd_eip_raw_record "
                "  WHERE company_id = %(company)s "
                "        AND work_order_no = %(wo)s"
                "  UNION ALL "
                "  SELECT production_order_no FROM sn_wsd_eip_pack_record "
                "  WHERE company_id = %(company)s "
                "        AND work_order_no = %(wo)s"
                "  UNION ALL "
                "  SELECT production_order_no FROM sn_wsd_eip_ship_record "
                "  WHERE company_id = %(company)s "
                "        AND work_order_no = %(wo)s) docs "
                "WHERE production_order_no IS NOT NULL LIMIT 1", params)
            row = self.env.cr.fetchone()
            production_order_no = row[0] if row else ''
        # the production quantity of the work order: the EIP work
        # order ledger of this number (the overview key is the work
        # order number, so this is a by-number read; nothing is read
        # through the MES order)
        work = self.env['sn.wsd.eip.work.order'].search([
            ('wo_no', '=', params['wo']),
            ('company_id', '=', params['company'])], limit=1)
        if work and work.amount:
            planned_qty = work.amount
        return {
            'production_order_no': production_order_no,
            'planned_qty': planned_qty,
            'first_check_time': self._overview_fmt_dt(first_time),
            'last_check_time': self._overview_fmt_dt(last_time),
        }

    def _overview_fmt_dt(self, value):
        if not value:
            return ''
        return fields.Datetime.context_timestamp(
            self, value).strftime('%Y-%m-%d %H:%M:%S')

    def _overview_pass_rows(self, rows, names, families):
        """Every enabled process-step interface of the work order's
        spec families in code order -- a step without collected data
        shows zeros -- then the codes that have data but are not an
        enabled process-step interface, worst first (most flagged
        units), then by code. ``has_limit`` tells whether the
        out-of-limit column means anything for the step."""
        by_code = {row[0]: row for row in rows}
        listed = [
            code for code in sorted(names)
            if _interface_kind(code, _code_family(code)) == 'pass'
            and _code_family(code) in families]
        listed_codes = set(listed)
        # a step with no active rule has nothing to judge: its
        # out-of-limit column is a dash on the page
        limited = {code for code, _count in self.env[
            'sn.wsd.eip.clean.rule']._read_group(
            [('company_id', '=', self.env.company.id),
             ('info_type_code', 'in', sorted(by_code)),
             ('active', '=', True)],
            ['info_type_code'], ['__count'])} if by_code else set()
        keys = ('units', 'ng', 'missing', 'limit', 'pending', 'rejected',
                'qualified')
        result = []
        for code in listed:
            data = by_code.pop(code, None)
            result.append(dict({
                'code': code,
                'name': names.get(code, code),
                'operation': data[1] if data else '',
                'has_limit': code in limited,
            }, **dict(zip(keys, data[2:] if data else (0,) * 7))))
        extras = [dict({
            'code': row[0],
            'name': names.get(row[0], row[0]),
            'operation': row[1] or '',
            'has_limit': row[0] in limited,
        }, **dict(zip(keys, row[2:]))) for row in by_code.values()]
        extras.sort(key=lambda item: (
            -(item['ng'] + item['missing'] + item['limit']), item['code']))
        return result + extras

    def _overview_doc_rows(self, rows, names, families, tab,
                           report_counts=None):
        """Raw material / packing / shipping: every enabled interface of
        the tab in code order, zeros where nothing was recorded, then
        the codes that have data but are not an enabled interface."""
        by_code = {row[0]: row for row in rows}
        # the aggregated columns after the code: raw = count, NG,
        # pending, delivered; packing = rows, quantity, NG quantity,
        # pending, delivered; shipping = batches, quantity, shipped,
        # not shipped, pending, delivered
        empty = {'raw': (0, 0, 0, 0), 'pack': (0, 0, 0, 0, 0),
                 'ship': (0, 0, 0, 0, 0, 0)}[tab]
        result = []
        for code in sorted(names):
            if (_interface_kind(code, _code_family(code)) == tab
                    and _code_family(code) in families):
                data = by_code.pop(code, None)
                result.append(self._overview_doc_row(
                    code, names, tab, data[1:] if data else empty,
                    report_counts))
        for code in sorted(by_code):
            result.append(self._overview_doc_row(
                code, names, tab, by_code[code][1:]))
        return result

    def _overview_doc_row(self, code, names, tab, data,
                          report_counts=None):
        item = {'code': code, 'name': names.get(code, code)}
        if tab == 'raw':
            item.update(zip(('count', 'ng', 'pending', 'delivered'), data))
            # the reports of this inspection procedure
            item['reports'] = (report_counts or {}).get(code, 0)
        elif tab == 'pack':
            # first aggregate is the record count, the page sums quantities
            item.update(zip(('qty', 'ng_qty', 'pending', 'delivered'),
                            data[1:]))
        else:
            item.update(zip(
                ('batches', 'qty', 'shipped', 'not_shipped', 'pending',
                 'delivered'), data))
        return item

    # ------------------------------------------------------------------
    # detail
    # ------------------------------------------------------------------
    @api.model
    def get_detail(self, work_order_no, tab, code, flag,
                   limit=DETAIL_PAGE_SIZE, offset=0, domain=None):
        """One page of the records behind a clicked number, filtered
        by the search area's conditions (a plain domain list)."""
        if tab not in TAB_MODELS:
            raise UserError(_('Unknown tab %s.', tab))
        if flag not in TAB_FLAGS[tab]:
            raise UserError(_('Unknown number %s.', flag))
        work_order_no = (work_order_no or '').strip()
        limit = max(1, min(int(limit or DETAIL_PAGE_SIZE), 200))
        offset = max(0, int(offset or 0))
        domain = list(domain or [])
        if tab == 'pass':
            return self._detail_pass(work_order_no, code, flag, limit,
                                     offset, domain)
        Model = self.env[TAB_MODELS[tab]]
        domain = [
            ('company_id', '=', self.env.company.id),
            ('work_order_no', '=', work_order_no),
            ('info_type_code', '=', code),
        ] + DOC_FLAG_DOMAINS[tab][flag] + domain
        total = Model.search_count(domain)
        rows = Model.search_read(
            domain, DOC_FIELDS[tab], limit=limit, offset=offset,
            order='id DESC')
        for row in rows:
            # datetimes come back in UTC: hand the page local wall time
            for name, value in row.items():
                if isinstance(value, datetime):
                    row[name] = self._overview_fmt_dt(value)
        return {'total': total, 'rows': rows}

    def _detail_pass(self, work_order_no, code, flag, limit, offset,
                     domain=None):
        cr = self.env.cr
        # raw SQL below: flush this transaction's pending writes first
        self.env.flush_all()
        params = {
            'company': self.env.company.id, 'wo': work_order_no,
            'code': code, 'kind': PASS_FLAG_KINDS.get(flag, ''),
            'limit': limit, 'offset': offset,
        }
        # live judgement of the pending rows (shared with the summary)
        live_issues = self._eip_prepare_live(
            {'company': self.env.company.id, 'wo': work_order_no})
        where = ("r.company_id = %(company)s "
                 "AND r.work_order_no = %(wo)s "
                 "AND r.info_type_code = %(code)s"
                 + _PASS_FLAG_SQL[flag])
        joins = ""
        if flag in PASS_FLAG_KINDS:
            joins = (
                " LEFT JOIN (SELECT i.source_id, "
                "bool_or(i.kind = 'missing') AS has_missing, "
                "bool_or(i.kind = 'limit') AS has_limit "
                "FROM sn_wsd_eip_clean_issue i GROUP BY i.source_id) pi "
                "ON pi.source_id = r.id "
                " LEFT JOIN " + LIVE_FLAG_TABLE + " lf ON lf.id = r.id ")
        cr.execute(
            "SELECT COUNT(*) FROM sn_wsd_eip_pass_record r" + joins +
            " WHERE " + where, params)
        total = cr.fetchone()[0]
        # stable paging: newest check first, id breaks ties
        cr.execute(
            "SELECT r.id FROM sn_wsd_eip_pass_record r" + joins +
            " WHERE " + where +
            " ORDER BY r.check_time DESC NULLS LAST, r.id DESC "
            "LIMIT %(limit)s OFFSET %(offset)s", params)
        ids = [row[0] for row in cr.fetchall()]
        if domain:
            # the search area's conditions: narrow the flagged rows
            # through the ORM so the domain is evaluated properly
            domain = [('id', 'in', ids)] + domain
            total = self.search_count(domain)
            ids = self.search(domain, order='check_time DESC NULLS LAST,'
                                         ' id DESC', limit=limit,
                              offset=offset).ids
        rows = []
        issues = {}
        spec_columns = []
        if ids:
            # the page rows in one read; the columns are few on purpose
            self.browse(ids).read(['sn_name', 'check_time',
                                   'workcenter_id', 'device_no', 'state',
                                   'conclusion'])
            issues = self._detail_issues(ids, flag)
            # the live problems of the page's pending rows ride in
            for record_id in ids:
                if record_id in live_issues:
                    issues[record_id] = live_issues[record_id]
            # the clicked step's own spec value columns
            spec_columns, values_by_id = self._detail_spec_values(code, ids)
            for record_id in ids:
                record = self.browse(record_id)
                rows.append({
                    'id': record_id,
                    'sn': record.sn_name or '',
                    'check_time': self._overview_fmt_dt(record.check_time),
                    'workcenter': (
                        record.workcenter_id.display_name or ''),
                    'device_no': record.device_no or '',
                    'state': record.state,
                    'conclusion': record.conclusion,
                    'issues': issues.get(record_id, []),
                    'values': values_by_id.get(record_id, []),
                })
        return {'total': total, 'rows': rows, 'columns': spec_columns}

    # ------------------------------------------------------------------
    # live judgement of pending rows (read-only)
    # ------------------------------------------------------------------
    @api.model
    def _eip_prepare_live(self, params):
        """Judge the pending rows of one work order in memory -- the
        required-field and row-level limit gates are deterministic
        from the raw columns plus the filed corrections -- and park
        the flags in a session temp table the summary / detail SQL
        join. Nothing is written to the collection tables; the next
        real cleansing overwrites whatever this concludes. Returns the
        live problems per row for the detail drill-down."""
        cr = self.env.cr
        cr.execute("DROP TABLE IF EXISTS " + LIVE_FLAG_TABLE)
        cr.execute(
            "CREATE TEMP TABLE " + LIVE_FLAG_TABLE + " ("
            "id bigint PRIMARY KEY, has_missing boolean, "
            "has_limit boolean, unknown_limit boolean) "
            "ON COMMIT DROP")
        cr.execute(
            "SELECT id, info_type_code, conclusion "
            "FROM sn_wsd_eip_pass_record "
            "WHERE company_id = %(company)s AND work_order_no = %(wo)s "
            "AND state = 'pending'", params)
        pending = cr.fetchall()
        live_issues = {}
        if not pending:
            return live_issues
        # the columns the two offline gates read
        columns = sorted(
            {column for columns in CLEAN_REQUIRED.values()
             for column in columns}
            | {column for columns in VALUE_RULE_FIELDS.values()
               for column in columns}
            | {'id', 'info_type_code'})
        cr.execute(
            "SELECT %s FROM sn_wsd_eip_pass_record WHERE id = ANY(%%s)"
            % ', '.join(columns),
            ([row[0] for row in pending],))
        rows = cr.fetchall()
        cr.execute(
            "SELECT f.source_id, f.field_name FROM sn_wsd_eip_clean_fix f "
            "WHERE f.source_id = ANY(%s)",
            ([row[0] for row in pending],))
        fixes = defaultdict(set)
        for source_id, field_name in cr.fetchall():
            fixes[source_id].add(field_name)
        # the row-level rules (empty type): what the engine would use
        rule_map = defaultdict(dict)
        for rule in self.env['sn.wsd.eip.clean.rule'].search([
                ('company_id', '=', params['company']),
                ('average_error_type', 'in', (False, ''))]):
            rule_map[rule.info_type_code][rule.field_name] = rule
        flag_rows = []
        for row in rows:
            values = dict(zip(columns, row))
            row_id = values.pop('id')
            code = values.pop('info_type_code')
            fixes_set = fixes.get(row_id, set())
            problems = []
            issues = []
            for field_name in CLEAN_REQUIRED.get(code, []):
                if not fixes_set.intersection({field_name}) \
                        and not values.get(field_name):
                    problems.append('missing')
                    issues.append({
                        'kind': 'missing', 'field_name': field_name,
                        'message': 'missing required: %s' % field_name,
                    })
            for field_name in VALUE_RULE_FIELDS.get(code, []):
                rule = rule_map.get(code, {}).get(field_name)
                problem = rule and rule._eip_limit_problem(
                    values.get(field_name))
                if problem:
                    problems.append('limit')
                    issues.append({
                        'kind': 'limit', 'field_name': field_name,
                        'actual_value': values.get(field_name),
                        'lower_limit': rule.lower_limit,
                        'upper_limit': rule.upper_limit,
                        'message': 'limit fail: %s' % problem,
                    })
            has_missing = 'missing' in problems
            has_limit = 'limit' in problems
            unknown = code in LIVE_UNKNOWN_CODES
            if issues:
                live_issues[row_id] = issues
            flag_rows.append((row_id, has_missing, has_limit, unknown))
        cr.executemany(
            "INSERT INTO " + LIVE_FLAG_TABLE + " "
            "(id, has_missing, has_limit, unknown_limit) "
            "VALUES (%s, %s, %s, %s)", flag_rows)
        return live_issues

    def _detail_spec_values(self, code, ids):
        """The clicked step's own value columns: (column name,
        translated field label) pairs once, and each row's values in
        the same order."""
        columns = list(DETAIL_CODE_COLUMNS.get(code, ()))
        if not columns or not ids:
            return [], {}
        descriptions = self.fields_get(columns, ['string'])
        labeled = [(column, descriptions[column]['string'])
                   for column in columns]
        values_by_id = {}
        for row in self.browse(ids).read(columns):
            values_by_id[row['id']] = [
                '' if value is False else
                (self._overview_fmt_dt(value)
                 if isinstance(value, datetime) else value)
                for value in (row[column] for column in columns)]
        return labeled, values_by_id

    def _detail_issues(self, ids, flag):
        """The problems of the clicked kind on the page rows: one
        query for the whole page, grouped by row."""
        kind = PASS_FLAG_KINDS.get(flag)
        if not kind or not ids:
            return {}
        issues = self.env['sn.wsd.eip.clean.issue'].search_read(
            [('source_id', 'in', ids), ('kind', '=', kind)],
            ['source_id', 'kind', 'type_code', 'field_name',
             'actual_value', 'lower_limit', 'upper_limit', 'message'])
        grouped = defaultdict(list)
        for issue in issues:
            issue['source_id'] = issue['source_id'][0] if isinstance(
                issue['source_id'], (list, tuple)) else issue['source_id']
            grouped[issue.pop('source_id')].append(issue)
            issue.pop('id', None)
        return grouped

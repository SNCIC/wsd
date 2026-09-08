# -*- coding: utf-8 -*-
"""Pure-stdlib parser for the ERP tree-structured BOM Excel template.

Reads an .xlsx stream exported by the ERP (row 1 = headers, following rows are
hierarchical BOM levels expressed as "0", ".1", "..2", "...3", "....4").

The reader walks the OOXML zip directly (shared strings + inline strings), so
it does not depend on openpyxl behaviour and matches the proven import script
used to seed wsd mrp.bom.

Column layout follows the ERP export template, e.g.:
BOM层级 / 子项物料编码 / 物料名称 / 规格型号 / 物料属性 / BOM版本 / 数据状态 /
单位 / 用量:分子 / 用量:分母 / 标准用量 / 子项类型 / 是否跳层 / 是否禁用 /
生产车间 / 工艺路线 / 质检方案 / 默认仓库 / ...

This module contains no Odoo import; it is a plain reusable helper.
"""

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

_A = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

REQUIRED_HEADERS = (
    'BOM层级',
    '子项物料编码',
    '物料名称',
    '物料属性',
    'BOM版本',
    '单位',
    '标准用量',
    '是否禁用',
)


def _cell_text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _to_float(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_workbook(data):
    archive = zipfile.ZipFile(BytesIO(data))
    wb = ET.fromstring(archive.read('xl/workbook.xml'))
    rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    rid_to_target = {rel.get('Id'): rel.get('Target') for rel in rels}
    sheets = {}
    for sheet in wb.find('%ssheets' % _A):
        sheets[sheet.get('name')] = sheet.get('{%s}id' % _R)
    shared = []
    if 'xl/sharedStrings.xml' in archive.namelist():
        sst = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        for si in sst.findall('%ssi' % _A):
            shared.append(''.join(t.text or '' for t in si.iter('%st' % _A)))
    return archive, sheets, rid_to_target, shared


def _read_sheet(archive, rid_to_target, shared, rid):
    target = (rid_to_target[rid] or '').lstrip('/')
    if not target.startswith('xl/'):
        target = 'xl/' + target
    sheet = ET.fromstring(archive.read(target))
    rows = {}
    for cell in sheet.iter('%sc' % _A):
        ref = cell.get('r')
        match = re.match(r'([A-Z]+)(\d+)', ref or '')
        if not match:
            continue
        col, row = match.group(1), int(match.group(2))
        cell_type = cell.get('t')
        value_node = cell.find('%sv' % _A)
        inline = cell.find('%sis' % _A)
        value = None
        if cell_type == 's' and value_node is not None:
            index = int(value_node.text)
            value = shared[index] if index < len(shared) else None
        elif value_node is not None:
            value = value_node.text
        elif inline is not None:
            value = ''.join(t.text or '' for t in inline.iter('%st' % _A))
        if value is not None:
            rows.setdefault(row, {})[col] = value
    return rows


def _col_index(letter):
    total = 0
    for char in letter:
        total = total * 26 + (ord(char) - 64)
    return total


def _collect_sheet(rows):
    """Turn the {row: {col: value}} map into (header_cols, data_row_records)."""
    row_numbers = sorted(rows)
    if not row_numbers:
        return None
    header = rows[row_numbers[0]]
    header_cols = {value: col for col, value in header.items() if value}
    if not all(h in header_cols for h in REQUIRED_HEADERS):
        return None
    records = []
    for row_number in row_numbers[1:]:
        cell_map = rows[row_number]
        record = {'row': row_number}
        for name, col in header_cols.items():
            record[name] = cell_map.get(col)
        records.append(record)
    return header_cols, records


def parse_bom_xlsx(data):
    """Parse an ERP BOM .xlsx into top-level and sub-assembly BOM candidates.

    Returns:
        {
          'sheet': str,
          'raw_count': int,
          'disabled_count': int,
          'top': [node, ...],
          'subs': [node, ...],   # de-duplicated by 子项物料编码
        }
        node = {'row','code','name','spec','attr','bom_version','uom',
                'workshop','disabled','std_qty','depth','line_count','lines'}
        line = {'row','code','name','spec','uom','std_qty','disabled','workshop'}
    """
    archive, sheets, rid_to_target, shared = _load_workbook(data)
    try:
        for sheet_name, rid in sheets.items():
            rows = _read_sheet(archive, rid_to_target, shared, rid)
            collected = _collect_sheet(rows)
            if not collected:
                continue
            header_cols, records = collected
            return _build_result(sheet_name, header_cols, records)
        raise ValueError(
            'Template columns not recognized. One sheet must contain headers: %s.'
            % ' / '.join(REQUIRED_HEADERS)
        )
    finally:
        archive.close()


def _build_result(sheet_name, header_cols, records):
    raw_count = 0
    disabled_count = 0
    nodes = []
    stack = []  # list of (depth, node_dict)

    def cell(record, name):
        return _cell_text(record.get(name))

    for record in records:
        code = cell(record, '子项物料编码')
        name = cell(record, '物料名称')
        if not code and not name:
            continue
        raw_count += 1
        level_raw = cell(record, 'BOM层级')
        depth = 0 if level_raw in ('0', '') else level_raw.count('.')
        disabled = cell(record, '是否禁用') == '是'
        if disabled:
            disabled_count += 1
        std_qty = _to_float(cell(record, '标准用量'))
        if std_qty is None:
            num = _to_float(cell(record, '用量:分子'))
            den = _to_float(cell(record, '用量:分母'))
            if num is not None and den:
                std_qty = num / den
        node = {
            'row': record['row'],
            'depth': depth,
            'code': code,
            'name': name,
            'spec': cell(record, '规格型号'),
            'attr': cell(record, '物料属性'),
            'bom_version': cell(record, 'BOM版本'),
            'uom': cell(record, '单位'),
            'workshop': cell(record, '生产车间'),
            'disabled': disabled,
            'std_qty': std_qty,
            'children': [],
        }
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1]['children'].append(node)
        else:
            nodes.append(node)
        stack.append((depth, node))

    def _to_line(child):
        return {
            'row': child['row'],
            'code': child['code'],
            'name': child['name'],
            'spec': child['spec'],
            'uom': child['uom'],
            'std_qty': child['std_qty'],
            'disabled': child['disabled'],
            'workshop': child['workshop'],
        }

    def _to_bom(node):
        return {
            'row': node['row'],
            'depth': node['depth'],
            'code': node['code'],
            'name': node['name'],
            'spec': node['spec'],
            'attr': node['attr'],
            'bom_version': node['bom_version'],
            'uom': node['uom'],
            'workshop': node['workshop'],
            'disabled': node['disabled'],
            'std_qty': node['std_qty'],
            'line_count': len(node['children']),
            'lines': [_to_line(child) for child in node['children']],
        }

    top = []
    subs = []
    seen_sub = set()

    def walk(node):
        if node['depth'] == 0 and node['children']:
            top.append(_to_bom(node))
        for child in node['children']:
            if child['children']:
                child_bom = _to_bom(child)
                if child_bom['code'] and child_bom['code'] not in seen_sub:
                    seen_sub.add(child_bom['code'])
                    subs.append(child_bom)
            walk(child)

    for node in nodes:
        walk(node)
    return {
        'sheet': sheet_name,
        'raw_count': raw_count,
        'disabled_count': disabled_count,
        'top': top,
        'subs': subs,
    }

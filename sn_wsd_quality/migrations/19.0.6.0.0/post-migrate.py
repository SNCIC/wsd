"""Upgrade baseline for OQC disposition events (oqc-disposition-closure
decision 6, batch 1).

One-shot: every existing station-mode OQC inspection gets baseline events
for its known abnormal boards, built from the evidence visible at upgrade
time (NG exit list, failing cells, NG/scrap station history, confirmed
scrap records, active rework vouchers). No historical measurements,
timestamps or operators are fabricated: the operator is OdooBot and the
event time is the migration moment. The logic lives on the inspection
model (`_oqc_build_baseline`) so tests exercise the exact same code.
"""

import logging

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tools import sql

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    if not sql.table_exists(cr, 'sn_wsd_quality_inspection'):
        return
    if not sql.table_exists(cr, 'sn_wsd_quality_oqc_disposition_event'):
        return
    env = Environment(cr, SUPERUSER_ID, {})
    inspections = env['sn.wsd.quality.inspection'].search([
        ('inspection_type', '=', 'oqc'),
        ('mes_order_id', '!=', False),
        ('mes_order_id.x_manage_mode', '!=', 'report'),
    ])
    try:
        events = inspections._oqc_build_baseline()
    except Exception:
        # 不吞掉事件创建失败（决策 6）：升级必须可验证地完成基线
        _logger.exception(
            'sn_wsd_quality 19.0.6.0.0: OQC disposition baseline failed')
        raise
    _logger.info(
        'sn_wsd_quality 19.0.6.0.0: %s baseline disposition event(s) '
        'created for %s station-mode OQC inspection(s)',
        len(events), len(inspections))

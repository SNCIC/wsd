import logging

from odoo.tools import sql

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # pass-history-on-enter：为存量 WIP 行补立在制历史行（result=
    # in_progress、out_date 留空），使升级前的在制板在台账一步可见；
    # 其后续出站走回填路径（定位 in_progress 行回写判定），不新建行。
    if not sql.table_exists(cr, 'sn_wsd_serial_wip') \
            or not sql.table_exists(cr, 'sn_wsd_serial_operation_history'):
        return
    cr.execute("""
        INSERT INTO sn_wsd_serial_operation_history
            (create_uid, create_date, write_uid, write_date,
             serial_identity_id, mes_order_id, route_operation_id,
             workcenter_id, result, in_date, out_date, company_id)
        SELECT w.create_uid, w.create_date, w.write_uid, w.write_date,
               w.serial_identity_id, w.mes_order_id, w.route_operation_id,
               w.workcenter_id, 'in_progress', w.in_date, NULL, w.company_id
          FROM sn_wsd_serial_wip w
    """)
    cr.execute("SELECT count(*) FROM sn_wsd_serial_wip")
    _logger.info(
        'sn_wsd_mrp 19.0.13.0.0: backfilled %s in-progress history rows '
        'from WIP', cr.fetchone()[0])

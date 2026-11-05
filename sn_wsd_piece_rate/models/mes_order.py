import logging

from odoo import models

_logger = logging.getLogger(__name__)


class MesOrder(models.Model):
    """report-daily-workbench：报工提交即尽力生成计件草稿。

    后置钩子在报工行落库、分配落好之后运行：qty_ok>0、单价命中、业务
    月未关、参与人齐备才建草稿（参与人/比例原样复制、单价快照、业务
    日期=报工时间）。任一条件不满足或异常 → 捕获跳过，绝不阻断报工；
    行靠 x_piece_settled=False 自然落在「待分配」。
    """
    _inherit = 'sn.wsd.mes.order'

    def report_operation_qty(self, route_operation, qty_ok, qty_ng=0.0,
                             qty_scrap=0.0, scrap_reason=False,
                             participant_vals=None, team_id=False):
        report = super().report_operation_qty(
            route_operation, qty_ok, qty_ng=qty_ng, qty_scrap=qty_scrap,
            scrap_reason=scrap_reason, participant_vals=participant_vals,
            team_id=team_id)
        if report:
            try:
                report._piece_maybe_auto_settlement()
            except Exception:
                # best effort: a settlement hiccup must never roll back a
                # valid report -- the row simply stays 'to allocate'
                _logger.exception(
                    'report-daily-workbench: auto piece settlement draft '
                    'failed for operation report %s; reporting is '
                    'unaffected.', report.id)
        return report

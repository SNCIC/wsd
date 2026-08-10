from odoo import api, models


class StockTraceabilityReport(models.TransientModel):
    _inherit = 'stock.traceability.report'

    @api.model
    def _get_linked_move_lines(self, move_line):
        move_lines, is_used = super()._get_linked_move_lines(move_line)
        if not move_lines and move_line.move_id.reel_split_role == 'produce':
            move_lines = move_line.consume_line_ids
        if not is_used and move_line.move_id.reel_split_role == 'consume':
            is_used = move_line.produce_line_ids
        return move_lines, is_used

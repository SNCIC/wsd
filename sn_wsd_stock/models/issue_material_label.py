from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Operation types an issue label can be printed for: operations moving goods
# out of a location. The MES material issue / return / over-pick operations
# share the internal code, so they are covered by the same whitelist, while
# receipts keep their own flow (one label per internal batch at goods-in).
ISSUE_LABEL_PICKING_TYPE_CODES = ('internal', 'outgoing')


class StockPicking(models.Model):
    """Issue material labels (领料标签) on the operations moving goods out.

    Receipts label whole internal batches (one label per lot, quantity =
    lot.initial_quantity). Non-reel materials are however issued / transferred
    by an exact quantity, so the goods leaving a location need a label
    describing what actually leaves: those labels are printed from the
    operation lines, whose quantity is the issued quantity, and they reuse the
    incoming layout on a stock.move.line bound template.

    Scope: internal transfers (including the MES material issue, return and
    over-pick operations) and outgoing deliveries.
    """

    _inherit = 'stock.picking'

    can_print_issue_material_labels = fields.Boolean(
        string='Can Print Issue Material Labels',
        compute='_compute_can_print_issue_material_labels',
    )

    def _is_issue_material_label_picking(self):
        """Whether this operation may print issue labels."""
        self.ensure_one()
        return (
            self.state != 'cancel'
            and self.picking_type_id.code in ISSUE_LABEL_PICKING_TYPE_CODES
        )

    def _issue_material_label_lines(self):
        """Operations an issue label can be printed for (whole operation).

        Electronic reel materials are excluded: a reel leaves the warehouse as
        the whole reel, so its receipt label already describes it and there is
        nothing to reprint.
        """
        self.ensure_one()
        if not self._is_issue_material_label_picking():
            return self.env['stock.move.line']
        # done operations keep their lines on the picking; fall back to the
        # moves for the states where the picking level one2many is empty
        lines = self.move_line_ids or self.move_ids.move_line_ids
        return lines.filtered(
            lambda line: line._is_issue_material_label_candidate())

    @api.depends('picking_type_id', 'state', 'move_line_ids.quantity',
                 'move_line_ids.lot_id', 'move_line_ids.product_id')
    def _compute_can_print_issue_material_labels(self):
        for picking in self:
            picking.can_print_issue_material_labels = bool(
                picking._issue_material_label_lines())

    def action_print_issue_material_labels(self):
        """Print one label per eligible operation line of the whole picking."""
        self.ensure_one()
        lines = self._issue_material_label_lines()
        if not lines:
            raise UserError(_(
                'Nothing to print: this operation has no tracked non-reel '
                'material line with an issued quantity.'))
        action = self.env.ref(
            'sn_wsd_stock.action_report_issue_material_label_zpl'
        ).report_action(lines, config=False)
        action['close_on_report_download'] = True
        return action


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    x_can_print_issue_material_label = fields.Boolean(
        string='Can Print Issue Material Label',
        compute='_compute_x_can_print_issue_material_label',
    )
    material_label_location = fields.Char(
        string='Material Label Location',
        compute='_compute_material_label_location',
        help='Location printed on the material label: the final path segment '
             'of the operation destination (the line side for an issue, the '
             'rack for a receipt).',
    )

    @api.depends('quantity', 'lot_id', 'product_id',
                 'picking_id.picking_type_id', 'picking_id.state')
    def _compute_x_can_print_issue_material_label(self):
        for line in self:
            line.x_can_print_issue_material_label = (
                line._is_issue_material_label_candidate())

    @api.depends('location_dest_id.complete_name')
    def _compute_material_label_location(self):
        for line in self:
            location_name = line.location_dest_id.complete_name or ''
            line.material_label_location = (
                location_name.rsplit('/', 1)[-1].strip()
                if location_name else False
            )

    def _is_issue_material_label_candidate(self):
        """An issue label describes goods actually leaving the warehouse:
        a tracked (lot) non-reel material with an issued quantity."""
        self.ensure_one()
        picking = self.picking_id or self.move_id.picking_id
        if (not picking or not picking._is_issue_material_label_picking()
                or self.quantity <= 0
                or self.product_id.tracking != 'lot'
                or not self.lot_id):
            return False
        return not self.product_id._is_reel_material()

    def action_print_issue_material_label(self):
        """Print the label of a single operation line."""
        self.ensure_one()
        if not self._is_issue_material_label_candidate():
            raise UserError(_(
                'An issue material label can only be printed for a tracked '
                'non-reel material line with an issued quantity.'))
        action = self.env.ref(
            'sn_wsd_stock.action_report_issue_material_label_zpl'
        ).report_action(self, config=False)
        action['close_on_report_download'] = True
        return action

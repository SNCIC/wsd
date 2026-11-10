from odoo import api, fields, models


class SnPrnMixin(models.AbstractModel):
    """Common data of the documents printed on the dot-matrix printer.

    Every sheet shows the page count of the print job and, on the finance and
    warehouse forms, how many times the document has been printed: the counter
    is kept on the document so a reprint can be told from the first copy.
    """

    _name = 'sn.prn.mixin'
    _description = 'Dot-Matrix Sheet Support'

    sn_prn_print_count = fields.Integer(
        string='Print Count',
        default=0,
        copy=False,
        readonly=True,
        help='Number of times the dot-matrix sheet of this document has been '
             'printed.',
    )
    sn_prn_note = fields.Text(
        string='Print Remark',
        help='Remark printed on the dot-matrix sheet of this document.',
    )
    sn_prn_reviewer_id = fields.Many2one(
        'res.users',
        string='Approved By',
        copy=False,
        help='Name printed on the approval line of the dot-matrix sheet.',
    )
    sn_prn_keeper_id = fields.Many2one(
        'hr.employee',
        string='Warehouse Keeper',
        copy=False,
        help='Name printed on the keeper line of the dot-matrix sheet.',
    )
    sn_prn_inspector_id = fields.Many2one(
        'hr.employee',
        string='Inspected By',
        copy=False,
        help='Name printed on the inspection line of the dot-matrix sheet. '
             'Kept on the document rather than read from the quality control, '
             'because a sheet is also printed for the transfers that no '
             'inspection covers.',
    )

    def _sn_prn_next_print_count(self):
        """Count this print job and return the number each sheet shows.

        The counter belongs to the document, not to the print job: a batch of
        fifty transfers advances fifty counters by one.
        """
        counts = {}
        for record in self:
            count = (record.sn_prn_print_count or 0) + 1
            counts[record.id] = count
            record.sudo().sn_prn_print_count = count
        return counts

    @api.model
    def _sn_prn_number(self, value, decimals=None):
        """A number as the sheets print it.

        Without `decimals` the trailing zeroes of a quantity are dropped, which
        is what the paper forms show; an amount keeps the two decimals of its
        column even when they are zero.
        """
        if decimals is None:
            text = ('%.6f' % (value or 0.0)).rstrip('0').rstrip('.')
        else:
            text = '%.*f' % (decimals, value or 0.0)
        return text or '0'

    def _sn_prn_action(self, route, ids_key='ids'):
        """URL action that hands the ESC/P stream of a selection to SNERP.

        SNERP intercepts the download and sends the bytes unchanged to the
        selected dot-matrix printer queue.
        """
        return {
            'type': 'ir.actions.act_url',
            'url': '%s?%s=%s' % (
                route, ids_key,
                ','.join(str(record_id) for record_id in self.ids)),
            'target': 'self',
        }

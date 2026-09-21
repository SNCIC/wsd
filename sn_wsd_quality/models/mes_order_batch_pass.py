from odoo import _, models
from odoo.exceptions import ValidationError


class MesOrderBatchPassQuality(models.Model):
    _inherit = 'sn.wsd.mes.order'

    def _batch_pass_gate_checks(self, route_operation):
        """FAI restriction for batch station passes: the first-article
        gate only guards the feeding station, a mid-route first-article
        operation has no gate of its own -- batch-passing it would
        silently skip the first article. The match is deliberately
        coarse (any active FAI scheme on this operation of the company
        blocks); better to over-block than to let boards bypass their
        first article."""
        super()._batch_pass_gate_checks(route_operation)
        self.ensure_one()
        Scheme = self.env['sn.wsd.quality.inspection.scheme']
        scheme = Scheme.search([
            ('inspection_type', '=', 'fai'),
            ('operation_id', '=', route_operation.operation_id.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if scheme:
            raise ValidationError(_(
                'Operation %(op)s is covered by first-article inspection '
                'scheme %(scheme)s: batch pass would skip the first '
                'article. It is not allowed.',
                op=route_operation.display_label, scheme=scheme.display_name))

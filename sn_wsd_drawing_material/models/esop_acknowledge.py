from odoo import fields, models


class SnWsdEsopAcknowledge(models.Model):
    """Read-acknowledgement of one ESOP document version by one employee.

    Who saw which version and when -- the audit trail behind the
    "updated to Vx" banner on the ESOP page.
    """
    _name = 'sn.wsd.esop.acknowledge'
    _description = 'ESOP Document Acknowledgement'
    _order = 'id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
    )
    document_id = fields.Many2one(
        'sn.wsd.esop.document',
        string='ESOP Document',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        related='document_id.company_id',
        store=True,
        index=True,
    )
    version = fields.Char(string='Version', required=True)
    ack_datetime = fields.Datetime(
        string='Acknowledged On',
        default=fields.Datetime.now,
        required=True,
    )

    _employee_version_uniq = models.Constraint(
        'unique(employee_id, document_id, version)',
        'This employee already acknowledged this document version.',
    )

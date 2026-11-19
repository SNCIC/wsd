from odoo import fields, models


class AccountMoveLine(models.Model):
    """Department the expense of a vendor bill is booked for.

    The paper expense invoice of the account carries the department that uses
    the service, next to the amount: the reader of the sheet charges the cost to
    that department. It defaults to the department of the user who enters the
    bill and stays editable, because the department of the invoice is not
    always the one of its author.
    """

    _inherit = 'account.move.line'

    sn_prn_department_id = fields.Many2one(
        'hr.department',
        string='Used By',
        check_company=True,
        default=lambda self: self._default_sn_prn_department_id(),
        help='Department printed in the department column of the expense '
             'invoice sheet.',
    )

    def _default_sn_prn_department_id(self):
        """Department of the employee of the user entering the bill."""
        return self.env.user.employee_id.department_id

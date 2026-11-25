# -*- coding: utf-8 -*-
"""Kingdee condition number on ``account.payment.term``.

The account keeps its receivable and payable conditions (``BD_RecCondition``,
``BD_PaymentCondition``) as instalment schemes: each line carries a rate, a
prepaid flag and a due-date algorithm (end of month, fixed day, days after
invoice...). An Odoo term is a percentage / days line. The two are **not** one
to one, so a condition is never derived from the account: an administrator links
an Odoo term to the account condition it stands for by storing its number here.

The customer import resolves ``FRECCONDITIONID`` through this field, the same way
it resolves a currency through its ISO code and a salesman through its name.
"""

from odoo import fields, models


class AccountPaymentTerm(models.Model):
    """A payment term of Odoo, linked to the condition of the account."""

    _inherit = "account.payment.term"

    kingdee_number = fields.Char(
        string="Kingdee Number",
        copy=False,
        index=True,
        help="Number (FNumber) of the Kingdee receivable (BD_RecCondition) or "
             "payment (BD_PaymentCondition) condition this term stands for. Fill "
             "it in to let the Kingdee customer import set the payment terms of a "
             "customer; a condition nobody linked stays empty on import and only "
             "its code and name are kept on the customer.",
    )

    _kingdee_number_unique = models.Constraint(
        "UNIQUE(kingdee_number)",
        "The Kingdee condition number must be unique.",
    )

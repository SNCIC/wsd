from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EipInterface(models.Model):
    """One row per interface of the EIP order-push spec (11 preset).

    The operation-type literals are data on purpose: if the remote
    side turns out to expect lowercase headers, adjust them here,
    not in code.
    """
    _name = 'sn.wsd.eip.interface'
    _description = 'EIP Interface'
    _order = 'sequence, code, id'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(
        string='Code', required=True, index=True,
        help='Stable key used by the code to fetch the interface.')
    path = fields.Char(
        string='Path', required=True,
        help='Path appended to the config base URL, '
             'e.g. /api/supplier-so.')
    direction = fields.Selection(
        [('pull', 'Pull'), ('push', 'Push')],
        string='Direction', required=True)
    operatetype_add = fields.Char(
        string='Operate Type (Add)', required=True, default='ADD',
        help='Operatetype header literal for new records.')
    operatetype_update = fields.Char(
        string='Operate Type (Update)', required=True, default='UPDATE',
        help='Operatetype header literal for updates.')
    operatetype_query = fields.Char(
        string='Operate Type (Query)', required=True, default='QUERY',
        help='Operatetype header literal for queries.')
    sequence = fields.Integer(string='Sequence')
    active = fields.Boolean(
        string='Active', default=True,
        help='Disabled interfaces are never called.')
    note = fields.Char(string='Note')

    _code_uniq = models.Constraint(
        'unique(code)',
        'The interface code must be unique.',
    )

    @api.model
    def _eip_interface(self, code):
        """Return the interface record for ``code``.

        The search runs without the active filter so an archived row
        raises the explicit disabled error instead of not-configured.
        """
        interface = self.with_context(active_test=False).search(
            [('code', '=', code)], limit=1)
        if not interface:
            raise UserError(_(
                'EIP interface "%s" is not configured.', code))
        if not interface.active:
            raise UserError(_('EIP interface "%s" is disabled.', code))
        return interface

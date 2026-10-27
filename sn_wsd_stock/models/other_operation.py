from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class StockPicking(models.Model):
    """Carry the department, the employee and the type of the other operations.

    The other deliveries leave the stock and the other receipts enter it
    without a sales or a purchase order. Both are booked on a virtual location
    (inventory usage) whose stock valuation account is the account of the
    operation, so the type of the document selects that location: the location
    of the type replaces the default location of the operation type, which is
    the inventory adjustment one.
    """

    _inherit = 'stock.picking'

    sn_issue_department_id = fields.Many2one(
        'hr.department',
        string='Issuing Department',
        check_company=True,
        help='Department taking the goods out of the stock.',
    )
    sn_issue_employee_id = fields.Many2one(
        'hr.employee',
        string='Issuing Employee',
        check_company=True,
        help='Employee taking the goods out of the stock, filtered on the '
             'issuing department.',
    )
    sn_issue_type_id = fields.Many2one(
        'sn.wsd.stock.other.operation.type',
        string='Issue Type',
        check_company=True,
        ondelete='restrict',
        domain=[('operation', 'in', ('other_out', 'both'))],
        help='Type of the other delivery. It selects the virtual location the '
             'goods leave to, hence the stock valuation account of the '
             'operation.',
    )
    sn_issue_location_id = fields.Many2one(
        'stock.location',
        string='Issue Location',
        related='location_dest_id',
        help='Virtual location the goods leave to, read from the issue type.',
    )
    sn_receive_department_id = fields.Many2one(
        'hr.department',
        string='Receiving Department',
        check_company=True,
        help='Department the goods enter the stock for.',
    )
    sn_receive_employee_id = fields.Many2one(
        'hr.employee',
        string='Receiving Employee',
        check_company=True,
        help='Employee bringing the goods into the stock, filtered on the '
             'receiving department.',
    )
    sn_receive_type_id = fields.Many2one(
        'sn.wsd.stock.other.operation.type',
        string='Receipt Type',
        check_company=True,
        ondelete='restrict',
        domain=[('operation', 'in', ('other_in', 'both'))],
        help='Type of the other receipt. It selects the virtual location the '
             'goods come from, hence the stock valuation account of the '
             'operation.',
    )
    sn_receive_location_id = fields.Many2one(
        'stock.location',
        string='Receipt Location',
        related='location_id',
        help='Virtual location the goods come from, read from the receipt '
             'type.',
    )

    def _sn_get_other_operation_kind(self):
        """Return the other operation this transfer belongs to, if any."""
        self.ensure_one()
        picking_type = self.picking_type_id
        warehouse = picking_type.warehouse_id
        if not warehouse:
            return False
        if picking_type == warehouse.other_out_type_id:
            return 'other_out'
        if picking_type == warehouse.other_in_type_id:
            return 'other_in'
        return False

    def _sn_get_other_operation_location(self, kind):
        """Virtual location of the type, or the default one of the operation."""
        self.ensure_one()
        if kind == 'other_out':
            operation_type = self.sn_issue_type_id
            default_location = self.picking_type_id.default_location_dest_id
        else:
            operation_type = self.sn_receive_type_id
            default_location = self.picking_type_id.default_location_src_id
        return operation_type.location_id or default_location

    def _sn_apply_other_operation_locations(self):
        """Put the other operations on the virtual location of their type.

        The location of a transfer is a computed field depending on the
        operation type and on the contact: the defaults are applied after the
        write, and the contact may replace the destination with its own
        customer location. Both are corrected here, on the transfer and, by
        the standard write, on its moves.
        """
        for picking in self:
            if picking.state in ('done', 'cancel'):
                continue
            kind = picking._sn_get_other_operation_kind()
            if not kind:
                continue
            location = picking._sn_get_other_operation_location(kind)
            field_name = 'location_dest_id' if kind == 'other_out' else 'location_id'
            if location and picking[field_name] != location:
                picking.with_context(
                    sn_skip_other_operation_location=True,
                ).write({field_name: location.id})

    def _sn_check_other_operation_types(self):
        """Refuse to validate an other operation without its type."""
        for picking in self:
            kind = picking._sn_get_other_operation_kind()
            if kind == 'other_out' and not picking.sn_issue_type_id:
                raise UserError(_(
                    'Select an issue type on the other delivery %s before '
                    'validating it.', picking.name))
            if kind == 'other_in' and not picking.sn_receive_type_id:
                raise UserError(_(
                    'Select a receipt type on the other receipt %s before '
                    'validating it.', picking.name))

    @api.onchange('sn_issue_department_id')
    def _onchange_sn_issue_department_id(self):
        if self.sn_issue_employee_id.department_id != self.sn_issue_department_id:
            self.sn_issue_employee_id = False

    @api.onchange('sn_receive_department_id')
    def _onchange_sn_receive_department_id(self):
        if self.sn_receive_employee_id.department_id != self.sn_receive_department_id:
            self.sn_receive_employee_id = False

    @api.onchange('sn_issue_type_id')
    def _onchange_sn_issue_type_id(self):
        if self.sn_issue_type_id.location_id:
            self.location_dest_id = self.sn_issue_type_id.location_id

    @api.onchange('sn_receive_type_id')
    def _onchange_sn_receive_type_id(self):
        if self.sn_receive_type_id.location_id:
            self.location_id = self.sn_receive_type_id.location_id

    @api.constrains(
        'sn_issue_type_id', 'sn_receive_type_id',
        'sn_issue_department_id', 'sn_issue_employee_id',
        'sn_receive_department_id', 'sn_receive_employee_id',
    )
    def _check_other_operation_fields(self):
        for picking in self:
            issue_type = picking.sn_issue_type_id
            if issue_type and issue_type.operation not in ('other_out', 'both'):
                raise ValidationError(_(
                    'The type %s cannot be used on an other delivery.',
                    issue_type.display_name))
            receive_type = picking.sn_receive_type_id
            if receive_type and receive_type.operation not in ('other_in', 'both'):
                raise ValidationError(_(
                    'The type %s cannot be used on an other receipt.',
                    receive_type.display_name))
            if (picking.sn_issue_employee_id and picking.sn_issue_department_id
                    and picking.sn_issue_employee_id.department_id
                    != picking.sn_issue_department_id):
                raise ValidationError(_(
                    'The issuing employee %(employee)s does not belong to the '
                    'department %(department)s.',
                    employee=picking.sn_issue_employee_id.display_name,
                    department=picking.sn_issue_department_id.display_name))
            if (picking.sn_receive_employee_id and picking.sn_receive_department_id
                    and picking.sn_receive_employee_id.department_id
                    != picking.sn_receive_department_id):
                raise ValidationError(_(
                    'The receiving employee %(employee)s does not belong to '
                    'the department %(department)s.',
                    employee=picking.sn_receive_employee_id.display_name,
                    department=picking.sn_receive_department_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        pickings._sn_apply_other_operation_locations()
        return pickings

    def write(self, vals):
        res = super().write(vals)
        # The contact of the transfer is part of the computed locations: it
        # replaces the destination with its customer location on a delivery.
        if (not self.env.context.get('sn_skip_other_operation_location')
                and {'picking_type_id', 'partner_id', 'sn_issue_type_id',
                     'sn_receive_type_id'} & set(vals)):
            self._sn_apply_other_operation_locations()
        return res

    def _action_done(self):
        self._sn_check_other_operation_types()
        self._sn_apply_other_operation_locations()
        return super()._action_done()

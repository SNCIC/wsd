from odoo import _, api, fields, models
from odoo.fields import Command
from odoo.exceptions import ValidationError


class MaintenanceTemplate(models.Model):
    """Per-equipment-type template of maintenance and spot check items.

    One template per equipment type (unique). When a check/maintenance
    task is generated later, its items come from here.
    """
    _name = 'sn.wsd.device.maint.template'
    _description = 'Spot Check / Maintenance Template'
    _order = 'equipment_type_id, id'

    equipment_type_id = fields.Many2one(
        'sn.wsd.device.equipment.type', string='Equipment Type', index=True)
    maintenance_item_ids = fields.One2many(
        'sn.wsd.device.maint.item', 'template_id',
        string='Maintenance Items',
        domain=[('item_type', '=', 'maintenance')])
    spot_check_item_ids = fields.One2many(
        'sn.wsd.device.maint.item', 'template_id',
        string='Spot Check Items',
        domain=[('item_type', '=', 'spot_check')])
    maintenance_count = fields.Integer(
        string='Maintenance Item Count', compute='_compute_counts')
    spot_check_count = fields.Integer(
        string='Spot Check Item Count', compute='_compute_counts')

    # NULL equipment_type_id (draft copies) is allowed: several drafts can
    # coexist, but a configured type can only have one template.
    _equipment_type_unique = models.Constraint(
        'UNIQUE(equipment_type_id)',
        'Only one template per equipment type is allowed.')

    def _compute_counts(self):
        for template in self:
            template.maintenance_count = len(template.maintenance_item_ids)
            template.spot_check_count = len(template.spot_check_item_ids)

    @api.depends('equipment_type_id')
    def _compute_display_name(self):
        for template in self:
            template.display_name = (
                template.equipment_type_id.name or _('Draft'))

    def _check_has_items(self):
        """A template must hold at least one maintenance or spot check item."""
        for template in self:
            if not template.maintenance_item_ids and \
                    not template.spot_check_item_ids:
                raise ValidationError(_(
                    'At least one maintenance item or spot check item '
                    'is required.'))

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        # @api.constrains on one2many fields does not fire when the o2m is
        # absent from the create vals, so enforce the rule here as well.
        templates._check_has_items()
        return templates

    def write(self, vals):
        result = super().write(vals)
        if 'maintenance_item_ids' in vals or 'spot_check_item_ids' in vals:
            self._check_has_items()
        return result

    def action_duplicate(self):
        """Copy the whole template (items included) as a draft without
        equipment type, so the user only has to pick the new type."""
        self.ensure_one()
        new_template = self.create({
            'equipment_type_id': False,
            'maintenance_item_ids': [
                Command.create(item.copy_data()[0])
                for item in self.maintenance_item_ids],
            'spot_check_item_ids': [
                Command.create(item.copy_data()[0])
                for item in self.spot_check_item_ids],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sn.wsd.device.maint.template',
            'res_id': new_template.id,
            'view_mode': 'form',
            'target': 'current',
        }


class MaintenanceItem(models.Model):
    """One check/maintenance line of a template.

    Maintenance items and spot check items share this model; the two
    template one2many fields split them via item_type.
    """
    _name = 'sn.wsd.device.maint.item'
    _description = 'Spot Check / Maintenance Item'
    _order = 'sequence, id'
    _rec_name = 'name'

    template_id = fields.Many2one(
        'sn.wsd.device.maint.template', string='Template',
        required=True, ondelete='cascade', index=True)
    item_type = fields.Selection(
        selection=[
            ('maintenance', 'Maintenance'),
            ('spot_check', 'Spot Check'),
        ], string='Item Type', required=True, default='maintenance')
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Item Description', required=True)
    method = fields.Text(string='Maintenance Method')
    guide_file = fields.Binary(
        string='Guide Media', attachment=True)
    guide_filename = fields.Char(string='Guide Media Filename')
    planned_hours = fields.Float(
        string='Planned Hours (h)', digits=(5, 2))
    value_type = fields.Selection(
        selection=[
            ('range', 'Range Value'),
            ('fixed', 'Fixed Value'),
            ('status', 'Status Value'),
        ], string='Value Type', default='status')
    upper_limit = fields.Float(string='Upper Limit', digits=(12, 4))
    lower_limit = fields.Float(string='Lower Limit', digits=(12, 4))
    unit = fields.Char(string='Unit')
    note = fields.Text(string='Notes')

    @api.onchange('value_type')
    def _onchange_value_type(self):
        """Clear the limits that make no sense for the chosen value type."""
        if self.value_type in ('fixed', 'status'):
            self.lower_limit = 0.0
        if self.value_type == 'status':
            self.upper_limit = 0.0

    @api.constrains('value_type', 'upper_limit', 'lower_limit')
    def _check_limits(self):
        for item in self:
            if item.value_type == 'range':
                if not item.upper_limit and not item.lower_limit:
                    raise ValidationError(_(
                        'Item "%s": both the upper limit and the lower '
                        'limit are required for a range value.', item.name))
                if item.lower_limit > item.upper_limit:
                    raise ValidationError(_(
                        'Item "%s": the lower limit must not exceed the '
                        'upper limit.', item.name))
            elif item.value_type == 'fixed':
                if not item.upper_limit:
                    raise ValidationError(_(
                        'Item "%s": the upper limit is required for a '
                        'fixed value.', item.name))
                if item.lower_limit:
                    raise ValidationError(_(
                        'Item "%s": the lower limit must stay empty for a '
                        'fixed value.', item.name))
            else:  # status
                if item.upper_limit or item.lower_limit:
                    raise ValidationError(_(
                        'Item "%s": both limits must stay empty for a '
                        'status value.', item.name))

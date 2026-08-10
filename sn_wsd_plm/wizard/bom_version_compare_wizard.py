from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class BomVersionCompareWizard(models.TransientModel):
    _name = 'sn.wsd.bom.version.compare.wizard'
    _description = 'BoM Version Comparison'

    comparison_mode = fields.Selection(
        [
            ('bom', 'BoM'),
            ('route', 'Process Route'),
        ],
        string='Comparison Mode',
        default='bom',
        required=True,
    )
    base_bom_id = fields.Many2one(
        'mrp.bom',
        string='Base Revision',
        domain="[('id', 'in', available_bom_ids)]",
    )
    target_bom_id = fields.Many2one(
        'mrp.bom',
        string='Target Revision',
        domain="[('id', 'in', available_bom_ids)]",
    )
    available_bom_ids = fields.Many2many(
        'mrp.bom',
        compute='_compute_available_bom_ids',
    )
    base_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Base Route Revision',
        domain="[('id', 'in', available_route_ids)]",
    )
    target_route_id = fields.Many2one(
        'sn.wsd.process.route',
        string='Target Route Revision',
        domain="[('id', 'in', available_route_ids)]",
    )
    available_route_ids = fields.Many2many(
        'sn.wsd.process.route',
        compute='_compute_available_route_ids',
    )
    line_ids = fields.One2many(
        'sn.wsd.bom.version.compare.line',
        'wizard_id',
        string='Comparison Lines',
    )
    component_line_ids = fields.One2many(
        'sn.wsd.bom.version.compare.line',
        'wizard_id',
        string='Component Lines',
        domain=[('category', '=', 'component')],
    )
    byproduct_line_ids = fields.One2many(
        'sn.wsd.bom.version.compare.line',
        'wizard_id',
        string='By-product Lines',
        domain=[('category', '=', 'byproduct')],
    )
    route_operation_line_ids = fields.One2many(
        'sn.wsd.bom.version.compare.line',
        'wizard_id',
        string='Process Route Operation Lines',
        domain=[('category', '=', 'route_operation')],
    )
    setting_change_count = fields.Integer(string='Setting Changes', readonly=True)
    added_count = fields.Integer(string='Added', readonly=True)
    removed_count = fields.Integer(string='Removed', readonly=True)
    updated_count = fields.Integer(string='Changed', readonly=True)
    unchanged_count = fields.Integer(string='Unchanged', readonly=True)
    total_change_count = fields.Integer(string='Total Changes', readonly=True)

    @api.depends('base_bom_id', 'target_bom_id')
    def _compute_available_bom_ids(self):
        active_bom = self.env['mrp.bom'].browse(self.env.context.get('active_id')).exists()
        for wizard in self:
            anchor = wizard.target_bom_id or wizard.base_bom_id or active_bom
            wizard.available_bom_ids = self.env['mrp.bom']
            if anchor:
                wizard.available_bom_ids = self.env['mrp.bom'].with_context(active_test=False).search(
                    anchor._get_revision_family_domain(),
                    order='create_date desc, id desc',
                )

    @api.depends('base_route_id', 'target_route_id')
    def _compute_available_route_ids(self):
        active_route = self.env['sn.wsd.process.route'].browse(self.env.context.get('active_id')).exists()
        for wizard in self:
            anchor = wizard.target_route_id or wizard.base_route_id or active_route
            wizard.available_route_ids = self.env['sn.wsd.process.route']
            if anchor:
                wizard.available_route_ids = self.env['sn.wsd.process.route'].with_context(active_test=False).search(
                    anchor._get_revision_family_domain(),
                    order='create_date desc, id desc',
                )

    @api.constrains('comparison_mode', 'base_bom_id', 'target_bom_id', 'base_route_id', 'target_route_id')
    def _check_comparison_scope(self):
        for wizard in self:
            if wizard.comparison_mode == 'bom':
                if not wizard.base_bom_id or not wizard.target_bom_id:
                    raise ValidationError(_('Select two revisions to compare.'))
                if wizard.base_bom_id == wizard.target_bom_id:
                    raise ValidationError(_('Select two different revisions to compare.'))
                family = self.env['mrp.bom'].with_context(active_test=False).search(
                    wizard.target_bom_id._get_revision_family_domain()
                )
                if wizard.base_bom_id not in family:
                    raise ValidationError(_('The selected revisions must belong to the same BoM revision family.'))
            else:
                if not wizard.base_route_id or not wizard.target_route_id:
                    raise ValidationError(_('Select two route revisions to compare.'))
                if wizard.base_route_id == wizard.target_route_id:
                    raise ValidationError(_('Select two different route revisions to compare.'))
                family = self.env['sn.wsd.process.route'].with_context(active_test=False).search(
                    wizard.target_route_id._get_revision_family_domain()
                )
                if wizard.base_route_id not in family:
                    raise ValidationError(_('The selected revisions must belong to the same process route revision family.'))

    @api.onchange('comparison_mode', 'base_bom_id', 'target_bom_id', 'base_route_id', 'target_route_id')
    def _onchange_comparison(self):
        if self._has_complete_comparison():
            self._rebuild_comparison()
        else:
            self.line_ids = [fields.Command.clear()]
            self._reset_counts()

    def action_compare(self):
        self.ensure_one()
        self._check_comparison_scope()
        self._rebuild_comparison()
        return {
            'type': 'ir.actions.act_window',
            'name': _('BoM Version Comparison'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
        }

    def _has_complete_comparison(self):
        self.ensure_one()
        if self.comparison_mode == 'bom':
            return bool(self.base_bom_id and self.target_bom_id and self.base_bom_id != self.target_bom_id)
        return bool(self.base_route_id and self.target_route_id and self.base_route_id != self.target_route_id)

    def _reset_counts(self):
        self.setting_change_count = 0
        self.added_count = 0
        self.removed_count = 0
        self.updated_count = 0
        self.unchanged_count = 0
        self.total_change_count = 0

    def _rebuild_comparison(self):
        self.ensure_one()
        values_list = []
        if self.comparison_mode == 'bom':
            values_list.extend(self._get_material_comparison_values('component'))
        else:
            values_list.extend(self._get_route_operation_comparison_values(self.base_route_id, self.target_route_id))

        all_values = values_list
        visible_values = [
            values for values in all_values if values['change_type'] != 'unchanged'
        ]
        self.line_ids = [fields.Command.clear()] + [
            fields.Command.create(values) for values in visible_values
        ]
        self.setting_change_count = 0
        self.added_count = len([values for values in all_values if values['change_type'] == 'add'])
        self.removed_count = len([values for values in all_values if values['change_type'] == 'remove'])
        self.updated_count = len([
            values for values in all_values
            if values['change_type'] == 'update'
        ])
        self.unchanged_count = 0
        self.total_change_count = self.added_count + self.removed_count + self.updated_count

    def _get_material_comparison_values(self, category):
        base_lines = self.base_bom_id.bom_line_ids if category == 'component' else self.base_bom_id.byproduct_ids
        target_lines = self.target_bom_id.bom_line_ids if category == 'component' else self.target_bom_id.byproduct_ids
        pairs = self._pair_records(base_lines, target_lines, self._get_material_key)
        return [self._prepare_material_line(category, base_line, target_line) for base_line, target_line in pairs]

    def _get_route_operation_comparison_values(self, base_route, target_route):
        base_operations = base_route.route_operation_ids if base_route else self.env['sn.wsd.process.route.operation']
        target_operations = target_route.route_operation_ids if target_route else self.env['sn.wsd.process.route.operation']
        pairs = self._pair_records(base_operations, target_operations, self._get_route_operation_key)
        return [
            self._prepare_route_operation_line(base_operation, target_operation)
            for base_operation, target_operation in pairs
        ]

    @api.model
    def _pair_records(self, base_records, target_records, key_method):
        base_groups = defaultdict(list)
        target_groups = defaultdict(list)
        for record in base_records.sorted(lambda item: (item.sequence, item.id)):
            base_groups[key_method(record)].append(record)
        for record in target_records.sorted(lambda item: (item.sequence, item.id)):
            target_groups[key_method(record)].append(record)
        pairs = []
        for key in sorted(set(base_groups) | set(target_groups), key=str):
            base_group = base_groups[key]
            target_group = target_groups[key]
            size = max(len(base_group), len(target_group))
            pairs.extend([
                (
                    base_group[index] if index < len(base_group) else base_records[:0],
                    target_group[index] if index < len(target_group) else target_records[:0],
                )
                for index in range(size)
            ])
        return pairs

    @api.model
    def _get_material_key(self, line):
        substitution_role = line.x_substitution_role if line._name == 'mrp.bom.line' else False
        return (
            line.product_id.id,
            tuple(sorted(line.bom_product_template_attribute_value_ids.ids)),
            substitution_role or '',
        )

    @api.model
    def _get_operation_key(self, operation):
        return operation.x_step_code or operation.name or str(operation.id)

    @api.model
    def _get_route_operation_key(self, operation):
        return operation.x_step_code or operation.operation_id.code or operation.name or str(operation.id)

    def _prepare_material_line(self, category, base_line, target_line):
        line = target_line or base_line
        if not base_line:
            change_type = 'add'
        elif not target_line:
            change_type = 'remove'
        else:
            changed = any([
                self._float_differs(base_line.product_qty, target_line.product_qty, base_line.product_uom_id, target_line.product_uom_id),
                base_line.product_uom_id != target_line.product_uom_id,
                base_line.sequence != target_line.sequence,
                category == 'byproduct' and base_line.cost_share != target_line.cost_share,
            ])
            change_type = 'update' if changed else 'unchanged'
        return {
            'category': category,
            'change_type': change_type,
            'product_id': line.product_id.id,
            'item_name': line.product_id.display_name,
            'product_code': line.product_id.default_code or '',
            'old_qty': base_line.product_qty if base_line else 0.0,
            'new_qty': target_line.product_qty if target_line else 0.0,
            'old_uom_id': base_line.product_uom_id.id if base_line else False,
            'new_uom_id': target_line.product_uom_id.id if target_line else False,
            'old_operation': self._operation_label(base_line.operation_id) if base_line else '',
            'new_operation': self._operation_label(target_line.operation_id) if target_line else '',
            'old_sequence': base_line.sequence if base_line else 0,
            'new_sequence': target_line.sequence if target_line else 0,
        }

    def _prepare_operation_line(self, base_operation, target_operation):
        operation = target_operation or base_operation
        if not base_operation:
            change_type = 'add'
        elif not target_operation:
            change_type = 'remove'
        else:
            changed = any([
                base_operation.name != target_operation.name,
                base_operation.workcenter_id != target_operation.workcenter_id,
                base_operation.sequence != target_operation.sequence,
                base_operation.time_mode != target_operation.time_mode,
                base_operation.time_mode_batch != target_operation.time_mode_batch,
                self._float_differs(base_operation.time_cycle_manual, target_operation.time_cycle_manual),
                self._dependency_labels(base_operation) != self._dependency_labels(target_operation),
                base_operation.active != target_operation.active,
            ])
            change_type = 'update' if changed else 'unchanged'
        return {
            'category': 'operation',
            'change_type': change_type,
            'item_name': operation.name,
            'operation_code': operation.x_step_code or '',
            'old_sequence': base_operation.sequence if base_operation else 0,
            'new_sequence': target_operation.sequence if target_operation else 0,
            'old_workcenter': base_operation.workcenter_id.display_name if base_operation else '',
            'new_workcenter': target_operation.workcenter_id.display_name if target_operation else '',
            'old_duration': base_operation.time_cycle_manual if base_operation else 0.0,
            'new_duration': target_operation.time_cycle_manual if target_operation else 0.0,
            'old_dependency': self._dependency_labels(base_operation) if base_operation else '',
            'new_dependency': self._dependency_labels(target_operation) if target_operation else '',
        }

    def _prepare_route_operation_line(self, base_operation, target_operation):
        operation = target_operation or base_operation
        if not base_operation:
            change_type = 'add'
        elif not target_operation:
            change_type = 'remove'
        else:
            changed = any([
                base_operation.operation_id != target_operation.operation_id,
                base_operation.workcenter_id != target_operation.workcenter_id,
                base_operation.sequence != target_operation.sequence,
                base_operation.time_mode != target_operation.time_mode,
                base_operation.time_mode_batch != target_operation.time_mode_batch,
                self._float_differs(base_operation.time_cycle_manual, target_operation.time_cycle_manual),
                base_operation.cost_mode != target_operation.cost_mode,
                self._route_dependency_labels(base_operation) != self._route_dependency_labels(target_operation),
                self._route_control_labels(base_operation) != self._route_control_labels(target_operation),
            ])
            change_type = 'update' if changed else 'unchanged'
        return {
            'category': 'route_operation',
            'change_type': change_type,
            'item_name': operation.name,
            'operation_code': operation.x_step_code or '',
            'old_sequence': base_operation.sequence if base_operation else 0,
            'new_sequence': target_operation.sequence if target_operation else 0,
            'old_workcenter': base_operation.workcenter_id.display_name if base_operation else '',
            'new_workcenter': target_operation.workcenter_id.display_name if target_operation else '',
            'old_duration': base_operation.time_cycle_manual if base_operation else 0.0,
            'new_duration': target_operation.time_cycle_manual if target_operation else 0.0,
            'old_dependency': self._route_dependency_labels(base_operation) if base_operation else '',
            'new_dependency': self._route_dependency_labels(target_operation) if target_operation else '',
            'old_value': self._route_operation_detail_label(base_operation) if base_operation else '',
            'new_value': self._route_operation_detail_label(target_operation) if target_operation else '',
        }

    @api.model
    def _operation_label(self, operation):
        if not operation:
            return ''
        return f'[{operation.x_step_code}] {operation.name}' if operation.x_step_code else operation.name

    @api.model
    def _route_compare_label(self, route):
        if not route:
            return ''
        return ' / '.join(filter(None, [route.code, route.name]))

    @api.model
    def _dependency_labels(self, operation):
        return ', '.join(operation.blocked_by_operation_ids.sorted('sequence').mapped(
            lambda dependency: dependency.x_step_code or dependency.name
        ))

    @api.model
    def _route_dependency_labels(self, operation):
        return ', '.join(operation.blocked_by_route_operation_ids.sorted('sequence').mapped(
            lambda dependency: dependency.x_step_code or dependency.name
        ))

    @api.model
    def _route_control_labels(self, operation):
        labels = []
        if operation.x_allow_entry:
            labels.append(_('Allow Entry'))
        if operation.x_allow_reentry:
            labels.append(_('Allow Reentry'))
        if operation.x_allow_repair_return:
            labels.append(_('Allow Repair Return'))
        if operation.x_allow_skip_with_override:
            labels.append(_('Allow Skip With Override'))
        return ', '.join(labels) or '-'

    def _route_operation_detail_label(self, operation):
        return '; '.join(filter(None, [
            _('Duration Computation: %s') % self._selection_label(operation, 'time_mode'),
            _('Computed On Last: %s') % operation.time_mode_batch,
            _('Cost Based On: %s') % self._selection_label(operation, 'cost_mode'),
            _('Route Control: %s') % self._route_control_labels(operation),
        ]))

    @api.model
    def _change_type_from_presence(self, base_record, target_record, old_value, new_value):
        if not base_record and target_record:
            return 'add'
        if base_record and not target_record:
            return 'remove'
        return 'unchanged' if old_value == new_value else 'update'

    @api.model
    def _float_differs(self, base_value, target_value, base_uom=False, target_uom=False):
        roundings = [uom.rounding for uom in (base_uom, target_uom) if uom]
        precision_rounding = min(roundings) if roundings else 0.000001
        return bool(float_compare(base_value, target_value, precision_rounding=precision_rounding))

    @api.model
    def _format_number(self, value):
        return f'{value:g}'

    @api.model
    def _format_datetime(self, value):
        return fields.Datetime.to_string(value) if value else ''

    @api.model
    def _selection_label(self, record, field_name):
        if not record:
            return ''
        selection = dict(record.fields_get([field_name])[field_name]['selection'])
        return selection.get(record[field_name], record[field_name] or '')


class BomVersionCompareLine(models.TransientModel):
    _name = 'sn.wsd.bom.version.compare.line'
    _description = 'BoM Version Comparison Line'
    _order = 'category, change_type, product_code, item_name, id'

    wizard_id = fields.Many2one(
        'sn.wsd.bom.version.compare.wizard',
        required=True,
        ondelete='cascade',
    )
    category = fields.Selection([
        ('setting', 'BoM Settings'),
        ('component', 'Components'),
        ('byproduct', 'By-products'),
        ('operation', 'Operations'),
        ('route_setting', 'Process Route Settings'),
        ('route_operation', 'Process Route Operations'),
    ], required=True, index=True)
    change_type = fields.Selection([
        ('add', 'Added'),
        ('remove', 'Removed'),
        ('update', 'Changed'),
        ('unchanged', 'Unchanged'),
    ], string='Difference', required=True, index=True)
    item_name = fields.Char(string='Item', required=True)
    product_id = fields.Many2one('product.product', string='Material', readonly=True)
    product_code = fields.Char(string='Material Code', readonly=True)
    old_value = fields.Char(string='Base Value', readonly=True)
    new_value = fields.Char(string='Target Value', readonly=True)
    old_qty = fields.Float(string='Base Qty', digits='Product Unit', readonly=True)
    new_qty = fields.Float(string='Target Qty', digits='Product Unit', readonly=True)
    old_uom_id = fields.Many2one('uom.uom', string='Base Unit', readonly=True)
    new_uom_id = fields.Many2one('uom.uom', string='Target Unit', readonly=True)
    old_operation = fields.Char(string='Base Operation', readonly=True)
    new_operation = fields.Char(string='Target Operation', readonly=True)
    operation_code = fields.Char(string='Operation Code', readonly=True)
    old_sequence = fields.Integer(string='Base Sequence', readonly=True)
    new_sequence = fields.Integer(string='Target Sequence', readonly=True)
    old_workcenter = fields.Char(string='Base Work Center', readonly=True)
    new_workcenter = fields.Char(string='Target Work Center', readonly=True)
    old_duration = fields.Float(string='Base Duration (min)', readonly=True)
    new_duration = fields.Float(string='Target Duration (min)', readonly=True)
    old_dependency = fields.Char(string='Base Predecessors', readonly=True)
    new_dependency = fields.Char(string='Target Predecessors', readonly=True)

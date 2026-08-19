from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EquipmentType(models.Model):
    """Equipment type dictionary (searchable dropdown on the ledger)."""
    _name = 'sn.wsd.device.equipment.type'
    _description = 'Equipment Type'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)


class DeviceLocation(models.Model):
    """Physical location tree: Factory > Workshop > Line > Station."""
    _name = 'sn.wsd.device.location'
    _description = 'Device Location'
    _order = 'parent_path, id'
    _parent_store = True
    _rec_name = 'complete_name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    parent_id = fields.Many2one(
        'sn.wsd.device.location', string='Parent Location', index=True,
        ondelete='restrict')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many(
        'sn.wsd.device.location', 'parent_id', string='Child Locations')
    kind = fields.Selection(
        selection=[
            ('factory', 'Factory'),
            ('workshop', 'Workshop'),
            ('line', 'Production Line'),
            ('station', 'Work Station'),
        ], string='Location Kind')
    complete_name = fields.Char(
        string='Complete Name', compute='_compute_complete_name',
        recursive=True, store=True)

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for location in self:
            if location.parent_id:
                location.complete_name = _(
                    '%(parent)s / %(own)s',
                    parent=location.parent_id.complete_name, own=location.name)
            else:
                location.complete_name = location.name


class Equipment(models.Model):
    """Equipment ledger: master record of every shop-floor device."""
    _name = 'sn.wsd.device.equipment'
    _description = 'Equipment Ledger'
    _order = 'code'
    _rec_name = 'code'
    _check_company_auto = True

    # ===== Group 1: basic information =====
    code = fields.Char(string='Equipment Code', required=True, index=True)
    name = fields.Char(string='Equipment Name', required=True)
    equipment_kind = fields.Selection(
        selection=[('device', 'Equipment'), ('tooling', 'Tooling')],
        string='Equipment Kind', default='device')
    name_sgcc = fields.Char(string='State Grid Equipment Name')
    name_csg = fields.Char(string='Southern Grid Equipment Name')
    model = fields.Char(string='Equipment Model')
    model_sgcc = fields.Char(string='State Grid Equipment Model')
    model_csg = fields.Char(string='Southern Grid Equipment Model')
    is_state_grid_bid = fields.Boolean(string='State Grid Bid Equipment')
    is_southern_grid_bid = fields.Boolean(string='Southern Grid Bid Equipment')
    equipment_type_id = fields.Many2one(
        'sn.wsd.device.equipment.type', string='Equipment Type', index=True)
    equipment_class = fields.Selection(
        selection=[
            ('a', 'Class A (Critical)'),
            ('b', 'Class B (Important)'),
            ('c', 'Class C (General)'),
        ], string='Equipment Class')
    equipment_status = fields.Selection(
        selection=[
            ('enabled', 'In Use'),
            ('repair', 'Under Repair'),
            ('sealed', 'Sealed'),
            ('scrapped', 'Scrapped'),
        ], string='Equipment Status', default='enabled', index=True)
    image = fields.Image(string='Equipment Picture', max_width=1920, max_height=1920)
    length_cm = fields.Float(string='Length (cm)', digits=(10, 1))
    width_cm = fields.Float(string='Width (cm)', digits=(10, 1))
    height_cm = fields.Float(string='Height (cm)', digits=(10, 1))
    weight_kg = fields.Float(string='Weight (kg)', digits=(10, 2))
    applicable_product_category_id = fields.Many2one(
        'product.category', string='Applicable Product')
    invoice_number = fields.Char(string='Invoice Number')
    invoice_equipment_name = fields.Char(string='Invoice Equipment Name')
    contract_number = fields.Char(string='Contract Number')
    contract_equipment_name = fields.Char(string='Contract Equipment Name')
    position_count = fields.Integer(string='Meter Position Count')

    # ===== Group 2: manufacturer information =====
    manufacturer = fields.Char(string='Manufacturer')
    manufacturer_sgcc = fields.Char(string='State Grid Manufacturer')
    manufacturer_csg = fields.Char(string='Southern Grid Manufacturer')
    serial_no = fields.Char(string='Factory Serial Number')
    serial_no_sgcc = fields.Char(string='State Grid Serial Number')
    serial_no_csg = fields.Char(string='Southern Grid Serial Number')
    manufacture_date = fields.Date(string='Manufacture Date')

    # ===== Group 3: purchase information =====
    original_value = fields.Float(
        string='Original Value (CNY)', digits=(16, 2))
    supplier_id = fields.Many2one(
        'res.partner', string='Supplier', index=True, check_company=True,
        # Keep the domain valid on base-only databases: supplier_rank
        # only exists when the account module is installed.
        domain=[('is_company', '=', True)])
    commissioning_date = fields.Date(string='Commissioning Date')

    # ===== Group 4: location and ownership =====
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    department_id = fields.Many2one(
        'hr.department', string='Usage Department', check_company=True)
    location_id = fields.Many2one(
        'sn.wsd.device.location', string='Installation Location', index=True)
    usage_user_id = fields.Many2one(
        'res.users', string='Usage Responsible', check_company=True)
    maintenance_user_id = fields.Many2one(
        'res.users', string='Maintenance Responsible', check_company=True)
    calibration_user_id = fields.Many2one(
        'res.users', string='Calibration Responsible', check_company=True)

    # ===== Group 5: technical parameters =====
    total_power_kw = fields.Float(string='Total Power (kW)', digits=(10, 2))
    air_consumption = fields.Float(
        string='Air Consumption (m3/h)', digits=(10, 2))

    # ===== Group 6: maintenance parameters (read-only, filled by other modules) =====
    last_internal_calibration_date = fields.Datetime(
        string='Last Internal Calibration', readonly=True)
    last_external_calibration_date = fields.Datetime(
        string='Last Certified Calibration', readonly=True)
    last_spot_check_date = fields.Datetime(
        string='Last Spot Check', readonly=True)
    last_maintenance_date = fields.Datetime(
        string='Last Maintenance', readonly=True)
    last_repair_date = fields.Datetime(
        string='Last Repair', readonly=True)

    # ===== documents =====
    document_ids = fields.One2many(
        'sn.wsd.device.equipment.document', 'equipment_id',
        string='Equipment Documents')
    document_count = fields.Integer(
        string='Document Count', compute='_compute_document_count')

    def _compute_document_count(self):
        groups = self.env['sn.wsd.device.equipment.document']._read_group(
            [('equipment_id', 'in', self.ids)], ['equipment_id'], ['__count'])
        counts = {equipment.id: count for equipment, count in groups}
        for record in self:
            record.document_count = counts.get(record.id, 0)

    @api.constrains('code')
    def _check_unique_code(self):
        for record in self:
            duplicate = self.search_count(
                [('code', '=', record.code), ('id', '!=', record.id)])
            if duplicate:
                raise ValidationError(_(
                    "Equipment code must be unique: %s", record.code))

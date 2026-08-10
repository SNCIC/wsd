from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class StockLot(models.Model):
    _inherit = 'stock.lot'

    is_msd_material = fields.Boolean(related='product_id.is_msd_material', store=True)
    msl_level_id = fields.Many2one(related='product_id.msl_level_id', store=True)
    component_thickness = fields.Float(related='product_id.component_thickness', store=True)
    msd_rule_id = fields.Many2one(
        'sn.msd.control.rule',
        string='MSD Control Rule',
        compute='_compute_msd_rule_id',
        store=True,
    )
    msd_state = fields.Selection(
        [
            ('sealed', 'Sealed'),
            ('opened', 'Opened'),
            ('baking', 'Baking'),
            ('dry', 'Dry'),
            ('scrapped', 'Scrapped'),
        ],
        string='MSD State',
        default='sealed',
        tracking=True,
    )
    msd_unseal_count = fields.Integer(string='Unseal Count', default=0, readonly=True)
    msd_bake_count = fields.Integer(string='Bake Count', default=0, readonly=True)
    msd_exposure_start = fields.Datetime(string='Exposure Start', readonly=True)
    msd_cumulative_exposure_minutes = fields.Float(string='Cumulative Exposure Minutes', default=0.0, readonly=True)
    msd_current_exposure_minutes = fields.Float(
        string='Current Exposure Minutes',
        compute='_compute_msd_current_values',
    )
    msd_total_exposure_minutes = fields.Float(
        string='Total Exposure Minutes',
        compute='_compute_msd_current_values',
    )
    msd_bake_start = fields.Datetime(string='Bake Start', readonly=True)
    msd_target_bake_minutes = fields.Integer(string='Target Bake Minutes', readonly=True)
    msd_baked_minutes = fields.Float(
        string='Baked Minutes',
        compute='_compute_msd_current_values',
    )
    msd_expected_bake_end = fields.Datetime(
        string='Expected Bake End',
        compute='_compute_msd_expected_bake_end',
        store=True,
    )
    msd_oven_info = fields.Char(string='Oven Information', tracking=True)

    @api.depends('product_id', 'product_id.is_msd_material', 'product_id.msl_level_id', 'product_id.component_thickness', 'company_id')
    def _compute_msd_rule_id(self):
        rule_model = self.env['sn.msd.control.rule']
        for lot in self:
            company = lot.company_id or self.env.company
            lot.msd_rule_id = rule_model._match_rule(lot.product_id, company=company)

    @api.depends('msd_state', 'msd_exposure_start', 'msd_cumulative_exposure_minutes', 'msd_bake_start')
    def _compute_msd_current_values(self):
        now = fields.Datetime.now()
        for lot in self:
            current_exposure = 0.0
            baked_minutes = 0.0
            if lot.is_msd_material and lot.msd_state == 'opened' and lot.msd_exposure_start:
                current_exposure = max((now - lot.msd_exposure_start).total_seconds() / 60.0, 0.0)
            if lot.is_msd_material and lot.msd_state == 'baking' and lot.msd_bake_start:
                baked_minutes = max((now - lot.msd_bake_start).total_seconds() / 60.0, 0.0)
            lot.msd_current_exposure_minutes = current_exposure
            lot.msd_total_exposure_minutes = lot.msd_cumulative_exposure_minutes + current_exposure
            lot.msd_baked_minutes = baked_minutes

    @api.depends('msd_bake_start', 'msd_target_bake_minutes')
    def _compute_msd_expected_bake_end(self):
        for lot in self:
            if lot.msd_bake_start and lot.msd_target_bake_minutes:
                lot.msd_expected_bake_end = fields.Datetime.add(lot.msd_bake_start, minutes=lot.msd_target_bake_minutes)
            else:
                lot.msd_expected_bake_end = False

    def _msd_ensure_rule(self):
        self.ensure_one()
        if not self.is_msd_material:
            return self.env['sn.msd.control.rule']
        if not self.product_id.msl_level_id or self.product_id.component_thickness <= 0:
            raise ValidationError(_('MSD material setup is incomplete. Maintain the MSL level and component thickness.'))
        if not self.msd_rule_id:
            raise ValidationError(_('No MSD control rule matches this material MSL level and component thickness.'))
        return self.msd_rule_id

    def _msd_current_exposure_minutes_now(self):
        self.ensure_one()
        if self.msd_state != 'opened' or not self.msd_exposure_start:
            return 0.0
        return max((fields.Datetime.now() - self.msd_exposure_start).total_seconds() / 60.0, 0.0)

    def _msd_close_exposure(self):
        for lot in self.filtered(lambda record: record.is_msd_material and record.msd_state == 'opened' and record.msd_exposure_start):
            exposure_minutes = lot._msd_current_exposure_minutes_now()
            lot.write({
                'msd_cumulative_exposure_minutes': lot.msd_cumulative_exposure_minutes + exposure_minutes,
                'msd_exposure_start': False,
            })

    def _msd_initialize_sealed(self):
        for lot in self.filtered('is_msd_material'):
            if lot.msd_state not in ('sealed', 'opened', 'baking', 'dry', 'scrapped'):
                lot.msd_state = 'sealed'
            if not lot.msd_state:
                lot.msd_state = 'sealed'

    def action_msd_unseal(self):
        for lot in self:
            if not lot.is_msd_material:
                continue
            lot._msd_ensure_rule()
            if lot.msd_state == 'scrapped':
                raise UserError(_('Scrapped MSD material cannot be unsealed.'))
            if lot.msd_state == 'baking':
                raise UserError(_('MSD material under baking cannot be unsealed.'))
            if lot.msd_state == 'opened':
                continue
            lot.write({
                'msd_state': 'opened',
                'msd_exposure_start': fields.Datetime.now(),
                'msd_unseal_count': lot.msd_unseal_count + 1,
            })
        return True

    def action_msd_seal(self):
        for lot in self:
            if not lot.is_msd_material:
                continue
            lot._msd_ensure_rule()
            lot._msd_validate_can_stop_exposure()
            lot._msd_close_exposure()
            lot.write({'msd_state': 'sealed'})
        return True

    def action_msd_set_dry(self):
        for lot in self:
            if not lot.is_msd_material:
                continue
            lot._msd_ensure_rule()
            lot._msd_validate_can_stop_exposure()
            lot._msd_close_exposure()
            lot.write({'msd_state': 'dry'})
        return True

    def action_msd_scrap(self):
        self._msd_close_exposure()
        self.filtered('is_msd_material').write({'msd_state': 'scrapped'})
        return True

    def action_open_msd_bake_wizard(self):
        self.ensure_one()
        self._msd_ensure_rule()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Start MSD Baking'),
            'res_model': 'sn.msd.bake.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lot_id': self.id},
        }

    def action_msd_finish_bake(self):
        for lot in self:
            if not lot.is_msd_material or lot.msd_state != 'baking':
                continue
            if lot.msd_expected_bake_end and fields.Datetime.now() < lot.msd_expected_bake_end:
                raise UserError(_('The configured bake duration is not complete.'))
            lot.write({
                'msd_state': 'dry',
                'msd_bake_start': False,
                'msd_target_bake_minutes': 0,
            })
        return True

    def _msd_validate_can_stop_exposure(self):
        self.ensure_one()
        if self.msd_state != 'opened':
            return
        rule = self._msd_ensure_rule()
        if self._msd_current_exposure_minutes_now() >= rule.standard_exposure_minutes:
            raise UserError(_('The current exposure exceeds the standard exposure limit. Bake the material before sealing or drying it.'))

    def _msd_validate_can_start_bake(self, bake_minutes):
        self.ensure_one()
        rule = self._msd_ensure_rule()
        current_exposure = self._msd_current_exposure_minutes_now()
        if current_exposure < rule.standard_exposure_minutes:
            remaining = rule.standard_exposure_minutes - current_exposure
            raise UserError(_('The current exposure has not exceeded the standard exposure limit. Remaining minutes: %.2f') % remaining)
        if self.msd_bake_count >= rule.bake_count_limit:
            raise UserError(_('The MSD bake count limit has been reached.'))
        if bake_minutes < rule.bake_duration_min or bake_minutes > rule.bake_duration_max:
            raise UserError(_('The bake minutes must be within the configured range.'))

    def _msd_start_bake(self, bake_minutes, oven_info=False):
        for lot in self:
            lot._msd_validate_can_start_bake(bake_minutes)
            lot._msd_close_exposure()
            lot.write({
                'msd_state': 'baking',
                'msd_bake_start': fields.Datetime.now(),
                'msd_target_bake_minutes': bake_minutes,
                'msd_oven_info': oven_info,
                'msd_bake_count': lot.msd_bake_count + 1,
            })
        return True

    def _msd_validate_for_use(self, auto_unseal=False):
        for lot in self.filtered('is_msd_material'):
            rule = lot._msd_ensure_rule()
            if lot.msd_state == 'scrapped':
                raise ValidationError(_('The MSD material is scrapped and cannot be used.'))
            if lot.msd_state == 'baking':
                raise ValidationError(_('The MSD material is baking and cannot be used.'))
            if lot.msd_state == 'sealed':
                if auto_unseal:
                    lot.action_msd_unseal()
                else:
                    raise ValidationError(_('The MSD material is sealed and must be unsealed before use.'))
            total_exposure = lot.msd_cumulative_exposure_minutes + lot._msd_current_exposure_minutes_now()
            if total_exposure >= rule.cumulative_exposure_minutes:
                lot.action_msd_scrap()
                raise ValidationError(_('The MSD cumulative exposure limit has been reached. The material must be scrapped.'))
            current_exposure = lot._msd_current_exposure_minutes_now()
            if current_exposure >= rule.standard_exposure_minutes:
                raise ValidationError(_('The MSD current exposure limit has been reached. Bake the material before use.'))
        return True

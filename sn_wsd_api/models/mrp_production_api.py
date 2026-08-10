from odoo import fields, models, _
from odoo.exceptions import ValidationError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _get_current_online_production(self, workcenter=None, production_line=None, workshop=None):
        workcenter = workcenter or self.env['mrp.workcenter']
        production_line = production_line or workcenter.x_production_line_id
        workshop = workshop or workcenter.x_workshop_id or production_line.workshop_id
        domain = [
            ('x_online_state', '=', 'online'),
            ('state', 'not in', ['done', 'cancel']),
        ]
        if workshop:
            domain.append(('x_workshop_id', '=', workshop.id))
        if production_line:
            domain.append(('x_production_line_id', '=', production_line.id))
        if workcenter and workcenter.company_id:
            domain.append(('company_id', '=', workcenter.company_id.id))
        return self.search(domain, order='date_start desc, id desc', limit=1)

    def _get_current_online_workorder(self, workcenter=None):
        self.ensure_one()
        workorders = self.workorder_ids.filtered(lambda wo: wo.state not in ('done', 'cancel'))
        if workcenter:
            scoped = workorders.filtered(lambda wo: wo.x_mes_workcenter_id == workcenter or wo.workcenter_id == workcenter)
            if scoped:
                ready_scoped = scoped.filtered(lambda wo: wo.state in ('ready', 'progress'))
                return (ready_scoped or scoped).sorted(lambda wo: (wo.sequence, wo.id))[:1]
        ready_workorders = workorders.filtered(lambda wo: wo.state in ('ready', 'progress'))
        return (ready_workorders or workorders).sorted(lambda wo: (wo.sequence, wo.id))[:1]

    def _get_or_create_finished_lot(self, serial_no, panel_no=False):
        self.ensure_one()
        lot = self.env['stock.lot'].search([
            ('name', '=', serial_no),
            ('product_id', '=', self.product_id.id),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not lot:
            identity = self.env['sn.wsd.serial.identity'].get_or_create(
                serial_no,
                self.company_id,
                origin_type='external',
                origin_production_id=self,
            )
            lot = self.env['stock.lot'].create({
                'name': serial_no,
                'product_id': self.product_id.id,
                'company_id': self.company_id.id,
                'x_panel_no': panel_no,
                'x_serial_identity_id': identity.id,
            })
        else:
            updates = {}
            if panel_no and lot.x_panel_no != panel_no:
                updates['x_panel_no'] = panel_no
            if not lot.x_serial_identity_id:
                updates['x_serial_identity_id'] = self.env['sn.wsd.serial.identity'].get_or_create(
                    serial_no,
                    self.company_id,
                    origin_type='external',
                    origin_production_id=self,
                ).id
            if updates:
                lot.write(updates)
        return lot

    def api_upload_finished_serials(self, serials):
        self.ensure_one()
        if not self.x_has_smt_operations:
            raise ValidationError(_('Finished serial upload is only allowed for SMT manufacturing orders.'))
        if self.state in ('done', 'cancel'):
            raise ValidationError(_('Finished serials cannot be uploaded to a done or cancelled manufacturing order.'))
        if not serials:
            raise ValidationError(_('No serial numbers were provided.'))
        normalized = []
        seen = set()
        for item in serials:
            serial_no = item.get('serial_no') if isinstance(item, dict) else item
            panel_no = item.get('panel_no') if isinstance(item, dict) else False
            serial_no = (serial_no or '').strip()
            panel_no = (panel_no or '').strip() or False
            if not serial_no:
                raise ValidationError(_('Serial number is required.'))
            if serial_no in seen:
                continue
            seen.add(serial_no)
            normalized.append((panel_no, serial_no))
        lots = self.env['stock.lot']
        for panel_no, serial_no in normalized:
            lot = self._get_or_create_finished_lot(serial_no, panel_no=panel_no)
            lots |= lot
        existing_lots = self.lot_producing_ids
        self.lot_producing_ids = [fields.Command.set((existing_lots | lots).ids)]
        if self.product_tracking == 'serial':
            self.qty_producing = len(self.lot_producing_ids)
            self.set_qty_producing()
        return {
            'ok': True,
            'production_id': self.id,
            'serial_count': len(lots),
            'archive_ids': [],
            'lot_ids': lots.ids,
        }

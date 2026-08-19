from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EquipmentDocSyncWizard(models.TransientModel):
    """Copy the documents of one equipment to another."""
    _name = 'sn.wsd.device.doc.sync.wizard'
    _description = 'Equipment Document Sync'

    source_equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Source Equipment', required=True,
        domain=[('document_ids', '!=', False)])
    target_equipment_id = fields.Many2one(
        'sn.wsd.device.equipment', string='Target Equipment', required=True)
    sync_mode = fields.Selection(
        selection=[
            ('overwrite', 'Overwrite'),
            ('skip', 'Skip Existing'),
        ], string='Sync Mode', default='skip', required=True,
        help="Overwrite: delete every document of the target equipment, then "
             "copy all documents of the source equipment.\n"
             "Skip Existing: documents already on the target with the same "
             "name are kept; the missing ones are copied.")
    source_document_count = fields.Integer(
        string='Source Documents', compute='_compute_source_document_count')

    @api.depends('source_equipment_id')
    def _compute_source_document_count(self):
        for wizard in self:
            wizard.source_document_count = len(
                wizard.source_equipment_id.document_ids)

    def action_sync(self):
        self.ensure_one()
        source = self.source_equipment_id
        target = self.target_equipment_id
        if source == target:
            raise UserError(_('Source and target equipment must differ.'))
        if not source.document_ids:
            raise UserError(_('Source equipment has no document to sync.'))

        if self.sync_mode == 'overwrite':
            target.document_ids.unlink()
            to_copy = source.document_ids
        else:
            existing_names = set(target.document_ids.mapped('name'))
            to_copy = source.document_ids.filtered(
                lambda doc: doc.name not in existing_names)

        sync_note = _(
            'Synced by %(user)s on %(date)s from equipment %(code)s',
            user=self.env.user.name,
            date=fields.Datetime.now(),
            code=source.code)
        for doc in to_copy:
            doc.copy({'equipment_id': target.id, 'note': sync_note})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Document Sync'),
                'message': _(
                    '%(count)s document(s) synced to %(code)s.',
                    count=len(to_copy), code=target.code),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

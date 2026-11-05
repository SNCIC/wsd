from odoo import models


class AccountMoveSend(models.AbstractModel):
    """Attach the invoice PDF to the bill of the counterpart company, so the
    accountant of the buying company works with the same document."""

    _inherit = 'account.move.send'

    def _generate_and_send_invoices(self, moves, from_cron=False, allow_raising=True,
                                    allow_fallback_pdf=False, **custom_settings):
        res = super()._generate_and_send_invoices(
            moves,
            from_cron=from_cron,
            allow_raising=allow_raising,
            allow_fallback_pdf=allow_fallback_pdf,
            **custom_settings,
        )
        company_partner_ids = self.env['res.company'].sudo().search([]).partner_id.ids
        moves_with_attachment = moves.filtered(
            lambda move: bool(move.message_main_attachment_id)
            and move.is_sale_document(include_receipts=True)
            and move.commercial_partner_id.id in company_partner_ids
            and move.company_id.intercompany_user_id
        )
        if not moves_with_attachment:
            return res
        bills = self.env['account.move'].sudo().search([
            ('move_type', 'in', self.env['account.move'].get_purchase_types(include_receipts=True)),
            ('auto_generated', '=', True),
            ('auto_invoice_id', 'in', moves_with_attachment.ids),
        ])
        for bill in bills:
            source_invoice = bill.auto_invoice_id
            attachment = source_invoice.message_main_attachment_id
            if not attachment:
                continue
            bill.message_main_attachment_id = self.env['ir.attachment'] \
                .with_user(bill.company_id.intercompany_user_id) \
                .with_company(bill.company_id) \
                .create({
                    'name': '%s.pdf' % source_invoice.name,
                    'type': 'binary',
                    'mimetype': 'application/pdf',
                    'raw': attachment.raw,
                    'res_model': 'account.move',
                    'res_id': bill.id,
                })
        return res

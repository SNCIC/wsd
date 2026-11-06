from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    """Generate the vendor bill of the counterpart company when a customer
    invoice or credit note is posted, and keep the two documents linked."""

    _name = 'account.move'
    _inherit = ['account.move', 'sn.intercompany.sync.mixin']

    auto_generated = fields.Boolean(
        string='Auto Generated Document',
        copy=False,
        default=False,
        help="Set on the bills created by the inter-company rules.")
    auto_invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Source Invoice',
        readonly=True,
        copy=False,
        index='btree_not_null',
        help="Customer invoice or credit note of the other company this "
             "document was generated from.")

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def _post(self, soft=True):
        invoices_map = {}
        posted = super()._post(soft)
        for invoice in posted.filtered(
                lambda move: move.is_sale_document() and not move.auto_generated):
            agreement, direction, company = invoice._sn_resolve('account.move')
            if not company:
                continue
            if agreement and not direction:
                continue
            if agreement:
                invoice._sn_bind(agreement, direction)
            elif not company.sudo().intercompany_generate_bills_refund:
                continue
            invoices_map.setdefault(company, self.env['account.move'])
            invoices_map[company] += invoice
        for company, invoices in invoices_map.items():
            self._check_intercompany_invoice_configuration(company, invoices)
            context = dict(self.env.context, default_company_id=company.id)
            context.pop('default_journal_id', None)
            context.pop('default_invoice_payment_term_id', None)
            invoices \
                .with_user(self._sn_invoice_user(company, invoices)) \
                .with_context(context) \
                .with_company(company) \
                ._inter_company_create_invoices()
        return posted

    def _sn_invoice_user(self, company, invoices):
        agreement = invoices[:1].intercompany_agreement_id
        if agreement and agreement.sync_user_id:
            return agreement.sync_user_id
        return company.sudo().intercompany_user_id

    def _check_intercompany_invoice_configuration(self, company, invoices):
        if not self._sn_invoice_user(company, invoices):
            raise UserError(_(
                "Set the user used to create the inter-company documents of "
                "%(company)s before posting an invoice that targets it.",
                company=company.display_name,
            ))
        if not company.sudo().intercompany_purchase_journal_id:
            raise UserError(_(
                "Configure the purchase journal used by the inter-company rules "
                "of %(company)s before posting an invoice that targets it.",
                company=company.display_name,
            ))

    def _inter_company_create_invoices(self):
        """Create the bills of the current company matching ``self``."""
        invoices_vals_per_type = {}
        inverse_types = {
            'out_invoice': 'in_invoice',
            'out_refund': 'in_refund',
        }
        for invoice in self:
            invoice_vals = invoice._inter_company_prepare_invoice_data(
                inverse_types[invoice.move_type])
            invoice_vals['invoice_line_ids'] = []
            for line in invoice.invoice_line_ids:
                invoice_vals['invoice_line_ids'].append(
                    (0, 0, line._inter_company_prepare_invoice_line_data()))
            new_invoice = invoice.with_context(
                default_move_type=invoice_vals['move_type']).new(invoice_vals)
            for line in new_invoice.invoice_line_ids.filtered(
                    lambda aml: aml.display_type not in ('line_section', 'line_subsection', 'line_note')):
                price_unit = line.price_unit
                line.tax_ids = line._get_computed_taxes()
                line.price_unit = price_unit
            invoice_vals = new_invoice._convert_to_write(new_invoice._cache)
            invoice_vals.pop('line_ids', None)
            invoice_vals['origin_invoice'] = invoice
            invoices_vals_per_type.setdefault(invoice_vals['move_type'], [])
            invoices_vals_per_type[invoice_vals['move_type']].append(invoice_vals)
        moves = self.env['account.move']
        for invoice_type, invoices_vals in invoices_vals_per_type.items():
            for invoice_vals in invoices_vals:
                origin_invoice = invoice_vals.pop('origin_invoice')
                move = self.with_context(default_type=invoice_type).create(invoice_vals)
                move.message_post(body=_(
                    "Automatically generated from %(origin)s of company %(company)s.",
                    origin=origin_invoice.name,
                    company=origin_invoice.company_id.name,
                ))
                origin_invoice._sn_log('create', target=move)
                if self.env.company.intercompany_document_state == 'posted':
                    move._post(soft=True)
                moves += move
        return moves

    def _inter_company_prepare_invoice_data(self, invoice_type):
        """Values of the bill created in the current company, header only."""
        self.ensure_one()
        delivery_partner_id = self.company_id.partner_id.address_get(['delivery'])['delivery']
        delivery_partner = self.env['res.partner'].browse(delivery_partner_id)
        fiscal_position = self.env['account.fiscal.position']._get_fiscal_position(
            self.company_id.partner_id, delivery=delivery_partner)
        agreement = self.intercompany_agreement_id
        return {
            'move_type': invoice_type,
            'ref': self.name,
            'partner_id': self.company_id.partner_id.id,
            'currency_id': self.currency_id.id,
            'auto_generated': True,
            'auto_invoice_id': self.id,
            'company_id': self.env.company.id,
            'invoice_date': self.invoice_date,
            'invoice_date_due': self.invoice_date_due,
            'payment_reference': self.payment_reference,
            'invoice_origin': _('%(company)s Invoice: %(entry)s',
                                company=self.company_id.name, entry=self.name),
            'fiscal_position_id': fiscal_position.id,
            'journal_id': self.env.company.intercompany_purchase_journal_id.id,
            'invoice_payment_term_id': self.invoice_payment_term_id.id
                if self.invoice_payment_term_id and not self.invoice_payment_term_id.company_id
                else False,
            'intercompany_agreement_id': agreement.id if agreement else False,
            'intercompany_direction': self.intercompany_direction,
            'intercompany_source_ref': self.display_name,
            'intercompany_root_ref': self.intercompany_root_ref or self._sn_self_ref(),
            'intercompany_sync_state': 'synced',
        }

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------
    def unlink(self):
        if self.env.context.get('skip_intercompany_sync'):
            return super().unlink()
        for move in self:
            counterpart = move._sn_counterpart()
            if not counterpart:
                continue
            if counterpart.state == 'draft':
                counterpart.with_context(skip_intercompany_sync=True).sudo().unlink()
                continue
            raise UserError(_(
                "Cannot delete %(source)s: its counterpart %(target)s is "
                "%(state)s. Reset it to draft in the other company first.",
                source=move.display_name,
                target=counterpart.display_name,
                state=counterpart.state,
            ))
        return super().unlink()

    def _sn_counterpart(self):
        self.ensure_one()
        if self.auto_invoice_id:
            return self.auto_invoice_id
        return self.env['account.move'].sudo().search(
            [('auto_invoice_id', '=', self.id)], limit=1)

    def _sn_snapshot_fields(self):
        return ('invoice_date', 'invoice_date_due')

    def _sn_replay_sync(self):
        self.ensure_one()
        agreement, direction, company = self._sn_resolve('account.move')
        if not company:
            raise UserError(_(
                "The counterpart company of %(document)s cannot be found.",
                document=self.display_name))
        counterpart = self._sn_counterpart()
        if counterpart:
            return counterpart
        if agreement and not direction:
            raise UserError(_(
                "The agreement does not cover the invoices of %(company)s.",
                company=self.company_id.display_name))
        if agreement:
            self._sn_bind(agreement, direction)
        self.with_user(self._sn_invoice_user(company, self)) \
            .with_context(default_company_id=company.id) \
            .with_company(company) \
            ._inter_company_create_invoices()
        return self._sn_counterpart()


class AccountMoveLine(models.Model):
    """Copy the invoice lines in the target company, keeping the analytic
    distribution that company is allowed to use."""

    _inherit = 'account.move.line'

    def _inter_company_prepare_invoice_line_data(self):
        self.ensure_one()
        target_company = self.env.company
        agreement = self.move_id.intercompany_agreement_id
        ProductMap = self.env['sn.intercompany.product.map']

        product = self.product_id
        ratio = 1.0
        if product and product.company_id and product.company_id != target_company:
            product, mapping, _mode = ProductMap._sn_resolve_product(
                product, target_company, agreement=agreement)
            if not product:
                self.move_id._sn_issue_unmapped_product(self.product_id, target_company)
            else:
                ratio = mapping.uom_ratio or 1.0

        quantity = self.quantity
        price = self.price_unit
        if self.product_id and self.product_uom_id:
            quantity = self.product_uom_id._compute_quantity(
                quantity, self.product_id.uom_id)
            price = self.product_uom_id._compute_price(
                price, self.product_id.uom_id)
        quantity = quantity * ratio
        if ratio:
            price = price / ratio

        vals = {
            'display_type': self.display_type,
            'sequence': self.sequence,
            'name': self.name,
            'quantity': quantity,
            'discount': self.discount,
            'price_unit': price,
        }
        if product:
            vals.update({
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
            })
        company_b = self.env['res.company']._find_company_from_partner(self.move_id.partner_id.id)
        company_a_partner = self.company_id.partner_id
        company_b_default_distribution = self.env['account.analytic.distribution.model']._get_distribution({
            'product_id': (product or self.product_id).id,
            'product_categ_id': (product or self.product_id).categ_id.id,
            'partner_id': company_a_partner.id,
            'partner_category_id': company_a_partner.category_id.ids,
            'account_prefix': self.account_id.code,
            'company_id': company_b.id,
        })
        analytic_distribution = {}
        if self.analytic_distribution:
            accounts_with_company = self.distribution_analytic_account_ids.filtered('company_id')
            for key, value in self.analytic_distribution.items():
                is_company_account = any(
                    int(account_id) in accounts_with_company.ids
                    for account_id in key.split(','))
                if not is_company_account:
                    analytic_distribution[key] = value
        if company_b_default_distribution or analytic_distribution:
            vals['analytic_distribution'] = dict(
                company_b_default_distribution, **analytic_distribution)
        return vals

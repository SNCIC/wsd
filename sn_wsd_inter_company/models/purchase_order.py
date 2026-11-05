from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

HEADER_SYNC_MAP = {'date_planned': 'commitment_date', 'date_order': 'date_order'}


class PurchaseOrder(models.Model):
    """Purchase orders take part in the trade agreement: approving one
    generates the sales order of the selling company, and later changes are
    pushed to it as long as it stays editable."""

    _name = 'purchase.order'
    _inherit = ['purchase.order', 'sn.intercompany.sync.mixin']

    auto_generated = fields.Boolean(
        string='Auto Generated Purchase Order',
        copy=False,
        help="Set on the purchase orders created by the inter-company rules.")
    auto_sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Source Sales Order',
        readonly=True,
        copy=False,
        index='btree_not_null',
        help="Sales order of the other company this purchase order was "
             "generated from.")

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def button_approve(self, force=False):
        res = super().button_approve(force=force)
        for order in self:
            if order.auto_generated:
                continue
            agreement, direction, company = order._sn_resolve('sale.order')
            if not company:
                continue
            if agreement and not direction:
                continue
            if agreement:
                order._sn_bind(agreement, direction)
                user = order._sn_sync_user(company)
                order.with_user(user) \
                    .with_context(default_company_id=company.id) \
                    .with_company(company) \
                    .inter_company_create_sale_order(company)
                continue
            if not company.sudo().intercompany_generate_sales_orders:
                continue
            user = company.sudo().intercompany_user_id
            if not user:
                raise UserError(_(
                    "Set the user used to create the inter-company documents of "
                    "%(company)s before approving an order that targets it.",
                    company=company.display_name,
                ))
            order.with_user(user) \
                .with_context(default_company_id=company.id) \
                .with_company(company) \
                .inter_company_create_sale_order(company)
        return res

    def inter_company_create_sale_order(self, company):
        """Create the sales order of ``company`` matching this purchase order."""
        self.ensure_one()
        user = self._sn_sync_user(company)
        if not self.env['sale.order'].with_user(user).has_access('create'):
            raise UserError(_(
                "The inter-company user of %(company)s cannot create sales "
                "orders. Grant it the sales rights or pick another user.",
                company=company.display_name,
            ))
        agreement = self.intercompany_agreement_id
        company_partner = self.sudo().company_id.partner_id.with_company(company)
        pricelist = company_partner.property_product_pricelist
        if pricelist and self.currency_id != pricelist.currency_id:
            raise UserError(_(
                "The sales order cannot be generated from %(origin)s because the "
                "price list of %(partner)s is in %(pricelist_currency)s while the "
                "purchase order is in %(order_currency)s.",
                origin=self.name,
                partner=company_partner.display_name,
                pricelist_currency=pricelist.currency_id.name,
                order_currency=self.currency_id.name,
            ))
        so_vals = self.sudo()._prepare_sale_order_data(
            self.name, company_partner, company, self.dest_address_id)
        for line in self.order_line.sudo():
            so_vals['order_line'].append(Command.create(
                self._prepare_sale_order_line_data(line, company),
            ))
        sale_order = self.env['sale.order'] \
            .with_user(user) \
            .with_context(default_company_id=company.id) \
            .with_company(company) \
            .create(so_vals)
        sale_order.message_post(body=_(
            "Automatically generated from %(origin)s of company %(company)s.",
            origin=self.name,
            company=self.company_id.name,
        ))
        self._sn_link_lines(sale_order)
        if not self.partner_ref:
            self.sudo().partner_ref = sale_order.name
        self._sn_log('create', target=sale_order,
                     snapshot=self._sn_take_snapshot(sale_order))
        if (agreement and agreement.auto_state == 'posted') \
                or (not agreement and self._sn_auto_state() == 'posted'):
            sale_order.with_user(user).action_confirm()
        return sale_order

    def _sn_link_lines(self, counterpart):
        """Store the line link on both sides, so later changes find their row."""
        self.ensure_one()
        for target_line in counterpart.order_line:
            if not target_line.auto_purchase_order_line_id:
                continue
            target_line.auto_purchase_order_line_id.sudo() \
                .with_context(skip_intercompany_sync=True).write({
                    'auto_sale_order_line_id': target_line.id,
                })

    def _prepare_sale_order_data(self, name, partner, company, direct_delivery_address):
        """Values of the sales order created in ``company``, header only."""
        self.ensure_one()
        agreement = self.intercompany_agreement_id
        partner_addr = partner.sudo().address_get(['invoice', 'delivery', 'contact'])
        warehouse = (agreement._warehouse_for(company) if agreement else False) \
            or company.intercompany_warehouse_id \
            or self.env['stock.warehouse'].sudo().search(
                [('company_id', '=', company.id)], limit=1)
        if not warehouse or warehouse.company_id != company:
            raise UserError(_(
                "Configure a warehouse for %(company)s to deliver the orders it "
                "gets from the other companies.",
                company=company.display_name,
            ))
        shipping_partner_id = self.picking_type_id.warehouse_id.partner_id.id \
            or (direct_delivery_address.id if direct_delivery_address else False) \
            or partner_addr['delivery']
        return {
            'name': self.env['res.company']._intercompany_document_name(
                'sale.order', company, partner),
            'company_id': company.id,
            'client_order_ref': name,
            'partner_id': partner.id,
            'pricelist_id': partner.property_product_pricelist.id,
            'partner_invoice_id': partner_addr['invoice'],
            'partner_shipping_id': shipping_partner_id,
            'date_order': self.date_order,
            'fiscal_position_id': self.env['account.fiscal.position']
                .with_company(company)
                ._get_fiscal_position(partner).id,
            'payment_term_id': partner.property_payment_term_id.id,
            'user_id': False,
            'auto_generated': True,
            'auto_purchase_order_id': self.id,
            'commitment_date': self.date_planned,
            'warehouse_id': warehouse.id,
            'intercompany_agreement_id': agreement.id if agreement else False,
            'intercompany_direction': self.intercompany_direction,
            'intercompany_source_ref': self.display_name,
            'intercompany_root_ref': self.intercompany_root_ref or self._sn_self_ref(),
            'intercompany_sync_state': 'synced',
            'order_line': [],
        }

    @api.model
    def _prepare_sale_order_line_data(self, line, company):
        """Values of a sales order line created in ``company``."""
        order = line.order_id
        agreement = order.intercompany_agreement_id
        product = line.product_id
        mapped_product = agreement._map_product(product, order.intercompany_direction) \
            if agreement else product
        if agreement and product and not mapped_product and product.company_id:
            product = self.env['product.product']
        elif mapped_product:
            product = mapped_product
        price = line.price_unit or 0.0
        quantity = line.product_qty
        if line.product_id:
            quantity = line.product_uom_id._compute_quantity(
                quantity, line.product_id.uom_id)
            price = line.product_uom_id._compute_price(
                price, line.product_id.uom_id)
        if agreement and agreement.price_policy == 'pricelist' and product:
            pricelist = order.company_id.partner_id.with_company(company) \
                .property_product_pricelist
            if pricelist:
                price = pricelist._get_product_price(
                    product.with_company(company), quantity)
        elif agreement:
            price = agreement._price_for(product, price, company)
        vals = {
            'name': product.name if not product and line.name else line.name,
            'product_uom_qty': quantity,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'price_unit': price,
            'discount': line.discount or 0.0,
            'company_id': company.id,
            'display_type': line.display_type,
            'sequence': line.sequence,
            'auto_purchase_order_line_id': line.id,
        }
        sale_delay = product.with_company(company).sale_delay
        if sale_delay:
            vals['customer_lead'] = sale_delay
        return vals

    # ------------------------------------------------------------------
    # Update, cancel and delete
    # ------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_intercompany_sync'):
            return res
        if set(vals) & set(HEADER_SYNC_MAP) or 'order_line' in vals:
            for order in self:
                order._sn_push_changes(vals)
        return res

    def button_cancel(self):
        if self.env.context.get('skip_intercompany_sync'):
            return super().button_cancel()
        res = super().button_cancel()
        for order in self:
            counterpart = order._sn_counterpart()
            if not counterpart:
                continue
            message = _(
                "%(source)s of company %(company)s was cancelled; review "
                "%(target)s.",
                source=order.display_name,
                company=order.company_id.name,
                target=counterpart.display_name,
            )
            if order._sn_link_level() == 'create_update_cancel' \
                    and counterpart.state == 'draft':
                counterpart.with_context(skip_intercompany_sync=True).sudo().action_cancel()
            counterpart._sn_mark_state('source_cancelled', message)
            order._sn_log('cancel', target=counterpart, detail=message)
        return res

    def unlink(self):
        if self.env.context.get('skip_intercompany_sync'):
            return super().unlink()
        for order in self:
            counterpart = order._sn_counterpart()
            if not counterpart:
                continue
            if counterpart.state in ('draft', 'cancel'):
                counterpart.with_context(skip_intercompany_sync=True).sudo().unlink()
                continue
            raise UserError(_(
                "Cannot delete %(source)s: its counterpart %(target)s is "
                "%(state)s. Cancel it in the other company first.",
                source=order.display_name,
                target=counterpart.display_name,
                state=counterpart.state,
            ))
        return super().unlink()

    def _sn_seller_company(self, counterpart):
        """The vendor sells, not the company issuing the purchase order."""
        return counterpart

    def _sn_counterpart(self):
        self.ensure_one()
        counterpart = self.auto_sale_order_id
        if not counterpart:
            counterpart = self.env['sale.order'].sudo().search(
                [('auto_purchase_order_id', '=', self.id)], limit=1)
        return counterpart

    def _sn_snapshot_fields(self):
        return ('commitment_date', 'date_order')

    def _sn_push_changes(self, vals, force=False):
        """Push the modifications of this purchase order to its sales order.

        ``force`` is used when a user decided to replay the synchronization
        from the issue queue: the conflict was arbitrated, the source wins.
        """
        self.ensure_one()
        counterpart = self._sn_counterpart()
        if not counterpart:
            return
        if self._sn_link_level() == 'create_only':
            self._sn_log('update', 'skipped', target=counterpart,
                         detail=_("The agreement only generates documents."))
            return
        if counterpart.state not in ('draft', 'sent', 'sale'):
            counterpart._sn_mark_state(
                'source_updated',
                _("%(source)s was modified but %(target)s is %(state)s and "
                  "cannot follow automatically.",
                  source=self.display_name,
                  target=counterpart.display_name,
                  state=counterpart.state),
            )
            self._sn_log('update', 'skipped', target=counterpart,
                         detail=_("The counterpart document is not editable."))
            return
        target_header_fields = [
            target_field for source_field, target_field in HEADER_SYNC_MAP.items()
            if source_field in vals
        ]
        if not force and target_header_fields \
                and self._sn_detect_conflict(counterpart, target_header_fields):
            policy = self.intercompany_agreement_id.conflict_policy or 'manual'
            if policy == 'manual':
                counterpart._sn_mark_state(
                    'diverged',
                    _("%(target)s was modified by the other company; the "
                      "changes of %(source)s were not applied.",
                      source=self.display_name, target=counterpart.display_name),
                )
                self._sn_issue(
                    'conflict',
                    _("Both companies modified %(source)s and %(target)s.",
                      source=self.display_name, target=counterpart.display_name),
                    target=counterpart,
                )
                self._sn_log('update', 'skipped', target=counterpart,
                             detail=_("Conflicting changes, manual resolution."))
                return
            if policy == 'latest_wins' and counterpart.write_date \
                    and self.write_date and counterpart.write_date >= self.write_date:
                self._sn_log('update', 'skipped', target=counterpart,
                             detail=_("The counterpart document is more recent."))
                return
        target_vals = {}
        for source_field, target_field in HEADER_SYNC_MAP.items():
            if source_field in vals:
                target_vals[target_field] = vals[source_field]
        line_commands = self._sn_prepare_line_commands(counterpart)
        if line_commands:
            target_vals['order_line'] = line_commands
        if not target_vals:
            return
        self._sn_lock_records([self, counterpart])
        counterpart.sudo().with_context(skip_intercompany_sync=True).write(target_vals)
        counterpart.sudo().with_context(skip_intercompany_sync=True).write({
            'intercompany_sync_state': 'synced',
            'intercompany_version': counterpart.intercompany_version + 1,
        })
        counterpart.message_post(body=_(
            "Updated from %(source)s.", source=self.display_name))
        self._sn_log('update', target=counterpart, diff=target_vals,
                     snapshot=self._sn_take_snapshot(counterpart))

    def _sn_prepare_line_commands(self, counterpart):
        """Commands keeping the lines of the sales order in line with ours."""
        self.ensure_one()
        commands = []
        targets = {
            line.auto_purchase_order_line_id.id: line
            for line in counterpart.order_line
            if line.auto_purchase_order_line_id
        }
        for line in self.order_line:
            if line.display_type:
                continue
            target = targets.pop(line.id, None)
            if not target:
                values = self._prepare_sale_order_line_data(line, counterpart.company_id)
                commands.append(Command.create(values))
                continue
            changes = self._sn_line_changes(line, target)
            if changes:
                commands.append(Command.update(target.id, changes))
        for target in targets.values():
            if target.qty_delivered or target.qty_invoiced:
                continue
            commands.append(Command.delete(target.id))
        return commands

    def _sn_line_changes(self, line, target):
        order = line.order_id
        agreement = order.intercompany_agreement_id
        product = line.product_id
        if agreement:
            product = agreement._map_product(product, order.intercompany_direction) or product
        quantity = line.product_qty
        price = line.price_unit
        if line.product_id:
            quantity = line.product_uom_id._compute_quantity(
                quantity, line.product_id.uom_id)
            price = line.product_uom_id._compute_price(
                price, line.product_id.uom_id)
        if agreement:
            price = agreement._price_for(product, price, target.company_id)
        changes = {}
        if product and target.product_id != product:
            changes['product_id'] = product.id
        if target.qty_delivered:
            quantity = max(quantity, target.qty_delivered)
        if abs(target.product_uom_qty - quantity) > 0.0001:
            changes['product_uom_qty'] = quantity
        if abs(target.price_unit - price) > 0.0001:
            changes['price_unit'] = price
        if abs((target.discount or 0.0) - (line.discount or 0.0)) > 0.0001:
            changes['discount'] = line.discount or 0.0
        if target.name != line.name:
            changes['name'] = line.name
        return changes

    def _sn_replay_sync(self):
        self.ensure_one()
        agreement, direction, company = self._sn_resolve('sale.order')
        if not company:
            raise UserError(_(
                "The counterpart company of %(document)s cannot be found.",
                document=self.display_name))
        counterpart = self._sn_counterpart()
        if counterpart:
            self._sn_push_changes({
                **{field_name: self[field_name] for field_name in HEADER_SYNC_MAP},
                'order_line': True,
            }, force=True)
            return counterpart
        if agreement and not direction:
            raise UserError(_(
                "The agreement does not allow %(company)s to sell to "
                "%(target)s.", company=self.company_id.display_name,
                target=company.display_name))
        if agreement:
            self._sn_bind(agreement, direction)
        self.inter_company_create_sale_order(company)
        return self._sn_counterpart()

    def _get_destination_location(self):
        """Deliver to the inter-company transit location when the purchase
        order targets an address of another company."""
        location = super()._get_destination_location()
        if not self.dest_address_id:
            return location
        sale_order = self._get_sale_orders()[:1]
        if not sale_order:
            return location
        partner_company = self.env['res.company']._find_company_from_partner(
            sale_order.partner_id.id)
        if partner_company \
                and partner_company != self.company_id \
                and self.dest_address_id != sale_order.partner_id:
            return sale_order.partner_id.property_stock_customer
        return location

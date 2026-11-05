from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

HEADER_SYNC_MAP = {'commitment_date': 'date_planned', 'date_order': 'date_order'}


class SaleOrder(models.Model):
    """Sale orders take part in the trade agreement: confirming one generates
    the purchase order of the buying company, and later changes are pushed to
    it as long as it stays editable."""

    _name = 'sale.order'
    _inherit = ['sale.order', 'sn.intercompany.sync.mixin']

    auto_generated = fields.Boolean(
        string='Auto Generated Sales Order',
        copy=False,
        help="Set on the sales orders created by the inter-company rules.")
    auto_purchase_order_id = fields.Many2one(
        comodel_name='purchase.order',
        string='Source Purchase Order',
        readonly=True,
        copy=False,
        index='btree_not_null',
        help="Purchase order of the other company this sales order was "
             "generated from.")

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def _action_confirm(self):
        res = super()._action_confirm()
        for order in self:
            if not order.company_id or order.auto_generated:
                continue
            agreement, direction, company = order._sn_resolve('purchase.order')
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
                    .inter_company_create_purchase_order(company)
                continue
            if not company.sudo().intercompany_generate_purchase_orders:
                continue
            user = company.sudo().intercompany_user_id
            if not user:
                raise UserError(_(
                    "Set the user used to create the inter-company documents of "
                    "%(company)s before confirming an order that targets it.",
                    company=company.display_name,
                ))
            order.with_user(user) \
                .with_context(default_company_id=company.id) \
                .with_company(company) \
                .inter_company_create_purchase_order(company)
        return res

    def inter_company_create_purchase_order(self, company):
        """Create the purchase order of ``company`` matching this sale order."""
        self.ensure_one()
        user = self._sn_sync_user(company)
        if not self.env['purchase.order'].with_user(user).has_access('create'):
            raise UserError(_(
                "The inter-company user of %(company)s cannot create purchase "
                "orders. Grant it the purchase rights or pick another user.",
                company=company.display_name,
            ))
        agreement = self.intercompany_agreement_id
        company_partner = self.sudo().company_id.partner_id.with_company(company)
        po_vals = self.sudo()._prepare_purchase_order_data(company, company_partner)
        for line in self.order_line.sudo():
            po_vals['order_line'].append(Command.create(
                self._prepare_purchase_order_line_data(line, self.date_order, company),
            ))
        purchase_order = self.env['purchase.order'] \
            .with_user(user) \
            .with_context(default_company_id=company.id) \
            .with_company(company) \
            .create(po_vals)
        purchase_order.message_post(body=_(
            "Automatically generated from %(origin)s of company %(company)s.",
            origin=self.name,
            company=self.company_id.name,
        ))
        self._sn_link_lines(purchase_order)
        if not self.client_order_ref:
            self.sudo().client_order_ref = purchase_order.name
        self._sn_log('create', target=purchase_order,
                     snapshot=self._sn_take_snapshot(purchase_order))
        if (agreement and agreement.auto_state == 'posted') \
                or (not agreement and self._sn_auto_state() == 'posted'):
            purchase_order.with_user(user).button_confirm()
        return purchase_order

    def _sn_link_lines(self, counterpart):
        """Store the line link on both sides, so later changes find their row."""
        self.ensure_one()
        for target_line in counterpart.order_line:
            if not target_line.auto_sale_order_line_id:
                continue
            target_line.auto_sale_order_line_id.sudo() \
                .with_context(skip_intercompany_sync=True).write({
                    'auto_purchase_order_line_id': target_line.id,
                })

    def _prepare_purchase_order_data(self, company, company_partner):
        """Values of the purchase order created in ``company``, header only."""
        self.ensure_one()
        agreement = self.intercompany_agreement_id
        warehouse = (agreement._warehouse_for(company) if agreement else False) \
            or company.intercompany_warehouse_id \
            or self.env['stock.warehouse'].sudo().search(
                [('company_id', '=', company.id)], limit=1)
        if not warehouse:
            raise UserError(_(
                "Configure a warehouse for %(company)s to receive the orders it "
                "gets from the other companies.",
                company=company.display_name,
            ))
        picking_type = company.intercompany_receipt_type_id or self.env['stock.picking.type'].sudo().search([
            ('code', '=', 'incoming'),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        if not picking_type:
            picking_type = self.env['purchase.order'].with_company(company)._default_picking_type()
        return {
            'name': self.env['res.company']._intercompany_document_name(
                'purchase.order', company, company_partner),
            'origin': self.name,
            'partner_id': company_partner.id,
            'date_order': self.date_order,
            'company_id': company.id,
            'fiscal_position_id': self.env['account.fiscal.position']
                .with_company(company)
                ._get_fiscal_position(company_partner).id,
            'payment_term_id': company_partner.property_supplier_payment_term_id.id,
            'auto_generated': True,
            'auto_sale_order_id': self.id,
            'partner_ref': self.name,
            'currency_id': self.currency_id.id,
            'picking_type_id': picking_type.id,
            'intercompany_agreement_id': agreement.id if agreement else False,
            'intercompany_direction': self.intercompany_direction,
            'intercompany_source_ref': self.display_name,
            'intercompany_root_ref': self.intercompany_root_ref or self._sn_self_ref(),
            'intercompany_sync_state': 'synced',
            'order_line': [],
        }

    @api.model
    def _prepare_purchase_order_line_data(self, so_line, date_order, company):
        """Values of a purchase order line created in ``company``."""
        order = so_line.order_id
        agreement = order.intercompany_agreement_id
        product = so_line.product_id
        mapped_product = agreement._map_product(product, order.intercompany_direction) \
            if agreement else product
        if agreement and product and not mapped_product and product.company_id:
            # The product cannot exist in the target company: copy a text line.
            product = self.env['product.product']
        elif mapped_product:
            product = mapped_product
        price = so_line.price_unit or 0.0
        quantity = so_line.product_uom_qty
        if so_line.product_id:
            quantity = so_line.product_uom_id._compute_quantity(
                quantity, so_line.product_id.uom_id)
            price = so_line.product_uom_id._compute_price(
                price, so_line.product_id.uom_id)
        if agreement and agreement.price_policy == 'pricelist' and product:
            seller = product.with_company(company)._select_seller(
                partner_id=order.company_id.partner_id,
                quantity=quantity,
                uom_id=product.uom_id,
            )
            if seller:
                price = seller.price
        elif agreement:
            price = agreement._price_for(product, price, company)
        return {
            'name': product.name if not product and so_line.name else so_line.name,
            'product_qty': quantity,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'price_unit': price,
            'discount': so_line.discount or 0.0,
            'company_id': company.id,
            'date_planned': so_line.order_id.commitment_date
                or so_line.order_id.expected_date
                or date_order,
            'display_type': so_line.display_type,
            'sequence': so_line.sequence,
            'auto_sale_order_line_id': so_line.id,
        }

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

    def action_cancel(self):
        if self.env.context.get('skip_intercompany_sync'):
            return super().action_cancel()
        res = super().action_cancel()
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
                counterpart.with_context(skip_intercompany_sync=True).sudo().button_cancel()
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

    def _sn_counterpart(self):
        self.ensure_one()
        counterpart = self.auto_purchase_order_id
        if not counterpart:
            counterpart = self.env['purchase.order'].sudo().search(
                [('auto_sale_order_id', '=', self.id)], limit=1)
        return counterpart

    def _sn_snapshot_fields(self):
        return ('date_planned', 'date_order')

    def _sn_push_changes(self, vals, force=False):
        """Push the modifications of this sale order to its purchase order.

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
        if counterpart.state != 'draft':
            counterpart._sn_mark_state(
                'source_updated',
                _("%(source)s was modified but %(target)s is %(state)s and "
                  "cannot follow automatically.",
                  source=self.display_name,
                  target=counterpart.display_name,
                  state=counterpart.state),
            )
            self._sn_log('update', 'skipped', target=counterpart,
                         detail=_("The counterpart document is not draft."))
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
        """Commands keeping the lines of the purchase order in line with ours."""
        self.ensure_one()
        commands = []
        targets = {
            line.auto_sale_order_line_id.id: line
            for line in counterpart.order_line
            if line.auto_sale_order_line_id
        }
        for line in self.order_line:
            if line.display_type:
                continue
            target = targets.pop(line.id, None)
            if not target:
                values = self._prepare_purchase_order_line_data(
                    line, self.date_order, counterpart.company_id)
                commands.append(Command.create(values))
                continue
            changes = self._sn_line_changes(line, target)
            if changes:
                commands.append(Command.update(target.id, changes))
        for target in targets.values():
            if target.qty_received or target.qty_invoiced:
                continue
            commands.append(Command.delete(target.id))
        return commands

    def _sn_line_changes(self, line, target):
        order = line.order_id
        agreement = order.intercompany_agreement_id
        product = line.product_id
        if agreement:
            product = agreement._map_product(product, order.intercompany_direction) or product
        quantity = line.product_uom_qty
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
        if target.qty_received:
            quantity = max(quantity, target.qty_received)
        if abs(target.product_qty - quantity) > 0.0001:
            changes['product_qty'] = quantity
        if abs(target.price_unit - price) > 0.0001:
            changes['price_unit'] = price
        if abs((target.discount or 0.0) - (line.discount or 0.0)) > 0.0001:
            changes['discount'] = line.discount or 0.0
        if target.name != line.name:
            changes['name'] = line.name
        return changes

    def _sn_replay_sync(self):
        self.ensure_one()
        agreement, direction, company = self._sn_resolve('purchase.order')
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
        self.inter_company_create_purchase_order(company)
        return self._sn_counterpart()

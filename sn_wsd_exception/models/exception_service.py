from odoo import _, api, fields, models
from odoo.exceptions import UserError

OPEN_STATES = ('pending', 'processing', 'suspended', 'pending_confirm')


class SnWsdExceptionService(models.Model):
    """Terminal-facing entry points for MES exception tickets.

    Shop-floor terminals call these methods through the jsonrpc controller.
    All messages are plain English sources translated through the standard
    i18n mechanism (zh_CN.po).
    """
    _name = 'sn.wsd.exception.service'
    _description = 'SN WSD Exception Terminal Service'

    @api.model
    def pareto_data(self, dimension, date_from=False, date_to=False):
        """Rows for the in-app Pareto dashboard (client action)."""
        report = self.env['report.sn_wsd_exception.report_exception_pareto']
        rows, total = report._get_pareto_rows(dimension, date_from, date_to)
        return {'rows': rows, 'total': total}

    @api.model
    def terminal_context(self, workcenter_id):
        """One payload for the shop-floor terminal: the production line behind
        the current work center, the root categories and the open exceptions
        of that line (feedback loop + duplicate-report guard)."""
        # terminals may call without a lang in the context: always render
        # display names in the calling user's language
        self = self.with_context(lang=self.env.user.lang)
        workcenter = self.env['mrp.workcenter'].browse(int(workcenter_id))
        if not workcenter.exists():
            raise UserError(_('Work center not found.'))
        line = workcenter.x_production_line_id
        categories = self.env['sn.wsd.exception.category'].search([
            ('parent_id', '=', False),
            ('active', '=', True),
            ('company_id', 'in', [workcenter.company_id.id, False]),
        ], order='sequence, id')
        return {
            'line_id': line.id or False,
            'line_name': line.display_name or '',
            'categories': [{
                'id': category.id,
                'name': category.display_name,
                'code': category.code or '',
            } for category in categories],
            'open_exceptions': self.open_list(line_id=line.id) if line else [],
            # the reporter confirms their own tickets from the PDA: only
            # the current user's pending confirmations of this line
            'my_pending_confirms': self._my_pending_confirms(line),
        }

    @api.model
    def _my_pending_confirms(self, line):
        if not line:
            return []
        tickets = self.env['sn.wsd.exception.ticket'].search([
            ('create_uid', '=', self.env.user.id),
            ('state', '=', 'pending_confirm'),
            ('production_line_id', '=', line.id),
        ], order='reported_at desc, id desc')
        return [{
            'ticket_id': ticket.id,
            'category': ticket.category_id.display_name,
            'responsible': ticket.responsible_user_id.name or '',
            # the reporter recognizes their ticket by their own words, not
            # by the sequence number
            'description': ticket.description or '',
            'reported_at': fields.Datetime.context_timestamp(
                ticket, ticket.reported_at).strftime('%m-%d %H:%M')
            if ticket.reported_at else '',
        } for ticket in tickets]

    @api.model
    def report(self, line_id, category_id, note, image_base64=None,
               reported_by_id=None, mes_order_id=None, repeat_of_id=None):
        line = self.env['sn.mrp.production.line'].browse(int(line_id))
        if not line.exists():
            raise UserError(_('Production line not found.'))
        category = self.env['sn.wsd.exception.category'].browse(int(category_id))
        if not category.exists() or category.parent_id:
            raise UserError(_('Exception category not found (a root category is required).'))
        vals = {
            'production_line_id': line.id,
            'category_id': category.id,
            'description': note or '',
            'reported_by_id': int(reported_by_id) if reported_by_id else False,
        }
        if mes_order_id:
            order = self.env['sn.wsd.mes.order'].browse(int(mes_order_id))
            if not order.exists():
                raise UserError(_('MES order not found.'))
            vals['mes_order_id'] = order.id
        if repeat_of_id:
            previous = self.env['sn.wsd.exception.ticket'].browse(int(repeat_of_id))
            if not previous.exists() or previous.state != 'done':
                raise UserError(_('The linked previous exception must be closed.'))
            vals['repeat_of_id'] = previous.id
        ticket = self.env['sn.wsd.exception.ticket'].create(vals)
        if image_base64:
            attachment = self.env['ir.attachment'].create({
                'name': f'{ticket.name}-photo',
                'datas': image_base64,
                'res_model': ticket._name,
                'res_id': ticket.id,
            })
            ticket.attachment_ids = [(4, attachment.id)]
        return {
            'ticket_id': ticket.id,
            'name': ticket.name,
            'state': ticket.state,
            'message': _('Exception %(name)s reported.', name=ticket.name),
        }

    @api.model
    def open_list(self, line_id=None, workshop_id=None):
        self = self.with_context(lang=self.env.user.lang)
        domain = [('state', 'in', list(OPEN_STATES))]
        if line_id:
            domain.append(('production_line_id', '=', int(line_id)))
        if workshop_id:
            domain.append(('workshop_id', '=', int(workshop_id)))
        tickets = self.env['sn.wsd.exception.ticket'].search(domain, order='reported_at desc, id desc')
        return [{
            'ticket_id': ticket.id,
            'name': ticket.name,
            'category': ticket.category_id.display_name,
            'subcategory': ticket.subcategory_id.display_name or '',
            'level': ticket.level,
            'state': ticket.state,
            'responsible': ticket.responsible_user_id.name or '',
            'reported_at': fields.Datetime.to_string(ticket.reported_at),
        } for ticket in tickets]

    @api.model
    def claim(self, ticket_id):
        ticket = self.env['sn.wsd.exception.ticket'].browse(int(ticket_id))
        if not ticket.exists():
            raise UserError(_('Exception ticket not found.'))
        ticket.action_claim()
        return {
            'ticket_id': ticket.id,
            'state': ticket.state,
            'message': _('Exception %(name)s claimed.', name=ticket.name),
        }

    @api.model
    def confirm(self, ticket_id):
        """The reporter closes their own ticket from the PDA. The initiator
        path runs sudo'd (plain users hold no write access to tickets);
        anyone else falls back to their own access rights, which is the
        handler-group path the PC side already uses."""
        ticket = self.env['sn.wsd.exception.ticket'].browse(int(ticket_id))
        if not ticket.exists():
            raise UserError(_('Exception ticket not found.'))
        if ticket.create_uid == self.env.user:
            ticket = ticket.sudo()
        ticket.action_confirm()
        return {
            'ticket_id': ticket.id,
            'state': ticket.state,
            'message': _('Exception %(name)s closed.', name=ticket.name),
        }

    @api.model
    def reject(self, ticket_id, note):
        """Reporter's rejection back to processing; the note is mandatory
        (enforced again by action_reject)."""
        ticket = self.env['sn.wsd.exception.ticket'].browse(int(ticket_id))
        if not ticket.exists():
            raise UserError(_('Exception ticket not found.'))
        if ticket.create_uid == self.env.user:
            ticket = ticket.sudo()
        ticket.action_reject(note)
        return {
            'ticket_id': ticket.id,
            'state': ticket.state,
            'message': _('Exception %(name)s rejected; back to processing.',
                         name=ticket.name),
        }

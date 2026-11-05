from odoo import _, api, fields, models
from odoo.exceptions import UserError

SYNC_STATE_SELECTION = [
    ('synced', 'Synchronized'),
    ('source_updated', 'Source Updated'),
    ('source_cancelled', 'Source Cancelled'),
    ('source_deleted', 'Source Deleted'),
    ('diverged', 'Diverged'),
    ('sync_failed', 'Synchronization Failed'),
]

DIRECTION_SELECTION = [
    ('a_to_b', 'Company A to Company B'),
    ('b_to_a', 'Company B to Company A'),
]


class SnIntercompanySyncMixin(models.AbstractModel):
    """Behaviour shared by the documents taking part in a trade agreement.

    The mixin resolves which agreement and which direction a document belongs
    to, records the link on the document itself, keeps the audit trail and the
    pending issues, and provides the row locking used before two documents of
    two companies are written in the same transaction.
    """

    _name = 'sn.intercompany.sync.mixin'
    _description = 'Inter-Company Synchronization Mixin'

    intercompany_agreement_id = fields.Many2one(
        'sn.intercompany.agreement',
        string='Inter-Company Agreement',
        copy=False,
        readonly=True,
        index='btree_not_null',
    )
    intercompany_direction = fields.Selection(
        DIRECTION_SELECTION,
        string='Trade Direction',
        copy=False,
        readonly=True,
    )
    intercompany_sync_state = fields.Selection(
        SYNC_STATE_SELECTION,
        string='Synchronization',
        default='synced',
        copy=False,
        readonly=True,
        help="Last known state of the link with the document of the other "
             "company.")
    intercompany_source_ref = fields.Char(
        string='Generated From',
        copy=False,
        readonly=True,
        help="Name of the document this one was generated from.")
    intercompany_root_ref = fields.Char(
        string='Trade Chain',
        copy=False,
        readonly=True,
        index='btree_not_null',
        help="First document of the trade chain, used to never generate a "
             "document twice for the same chain.")
    intercompany_version = fields.Integer(
        string='Synchronization Version',
        default=0,
        copy=False,
        readonly=True,
    )
    intercompany_skip_reason = fields.Char(
        string='Not Synchronized Because',
        copy=False,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def _sn_resolve(self, target_model):
        """Agreement, direction and counterpart company of the document.

        The agreement is empty when the two companies only rely on the
        company level switches; the direction is False when the agreement does
        not cover the case, so callers can silently skip.
        """
        self.ensure_one()
        counterpart = self.env['res.company'].sudo()._find_company_from_partner(
            self.partner_id.id)
        if not counterpart or counterpart == self.company_id:
            return self.env['sn.intercompany.agreement'], False, self.env['res.company']
        agreement = self.env['sn.intercompany.agreement']._find_running(
            self.company_id, counterpart)
        if not agreement:
            return agreement, False, counterpart
        direction = agreement._direction_from(self._sn_seller_company(counterpart))
        if not direction \
                or not agreement._is_direction_enabled(direction) \
                or not agreement._valid_today() \
                or not agreement._covers(target_model):
            return agreement, False, counterpart
        return agreement, direction, counterpart

    def _sn_seller_company(self, counterpart):
        """Company selling in this document.

        A sale order, a customer invoice or a delivery is issued by the
        selling company itself; a purchase order is issued by the buying
        company, so the vendor is the seller and drives the direction.
        """
        return self.company_id

    def _sn_link_level(self):
        self.ensure_one()
        if self.intercompany_agreement_id:
            return self.intercompany_agreement_id.link_level
        return 'create_only'

    def _sn_auto_state(self):
        """State the generated document must end in."""
        self.ensure_one()
        if self.intercompany_agreement_id:
            return self.intercompany_agreement_id.auto_state
        company = self.company_id.sudo()
        return 'posted' if company.intercompany_document_state == 'posted' else 'draft'

    def _sn_sync_user(self, company):
        self.ensure_one()
        if self.intercompany_agreement_id and self.intercompany_agreement_id.sync_user_id:
            return self.intercompany_agreement_id.sync_user_id
        user = company.sudo().intercompany_user_id
        if not user:
            raise UserError(_(
                "Set the user used to create the inter-company documents of "
                "%(company)s.", company=company.display_name))
        return user

    def _sn_bind(self, agreement, direction, root_ref=False):
        """Remember on the document which agreement and direction it follows."""
        self.ensure_one()
        self.sudo().with_context(skip_intercompany_sync=True).write({
            'intercompany_agreement_id': agreement.id if agreement else False,
            'intercompany_direction': direction or False,
            'intercompany_source_ref': self.intercompany_source_ref or self.display_name,
            'intercompany_root_ref': root_ref or self.intercompany_root_ref
                or self._sn_self_ref(),
        })

    def _sn_self_ref(self):
        self.ensure_one()
        return '%s,%s' % (self._name, self.id)

    # ------------------------------------------------------------------
    # Marking, logging and issues
    # ------------------------------------------------------------------
    def _sn_mark_state(self, state, message=False):
        self.ensure_one()
        self.sudo().with_context(skip_intercompany_sync=True).write({
            'intercompany_sync_state': state,
            'intercompany_version': (self.intercompany_version or 0) + 1,
        })
        if message:
            self.sudo().message_post(body=message)
        return True

    def _sn_log(self, action, result='success', target=None, detail=False,
                diff=False, snapshot=False, duration_ms=0):
        self.ensure_one()
        agreement = self.intercompany_agreement_id
        return self.env['sn.intercompany.sync.log'].sudo().create({
            'agreement_id': agreement.id if agreement else False,
            'direction': self.intercompany_direction,
            'action': action,
            'result': result,
            'source_model': self._name,
            'source_id': self.id,
            'source_ref': self.display_name,
            'target_model': target._name if target else False,
            'target_id': target.id if target else False,
            'target_ref': target.display_name if target else False,
            'root_ref': self.intercompany_root_ref or self._sn_self_ref(),
            'detail': detail or False,
            'diff': diff or False,
            'snapshot': snapshot or False,
            'duration_ms': duration_ms,
        })

    def _sn_issue(self, issue_type, message, target=None):
        self.ensure_one()
        agreement = self.intercompany_agreement_id
        return self.env['sn.intercompany.sync.issue'].sudo().create({
            'issue_type': issue_type,
            'agreement_id': agreement.id if agreement else False,
            'direction': self.intercompany_direction,
            'source_model': self._name,
            'source_id': self.id,
            'source_ref': self.display_name,
            'target_model': target._name if target else False,
            'target_id': target.id if target else False,
            'target_ref': target.display_name if target else False,
            'message': message,
        })

    # ------------------------------------------------------------------
    # Locking and snapshots
    # ------------------------------------------------------------------
    @api.model
    def _sn_lock_records(self, records):
        """Lock the rows of both sides in a deterministic order.

        Two companies may modify the two documents of the same chain at the
        same time, in both directions: ordering the locks on the model and the
        id prevents the two transactions from waiting for each other.
        """
        entries = set()
        for record in records:
            if record and record.id:
                entries.add((record._name, record.id))
        entries = sorted(entries)
        for model_name, record_id in entries:
            table = self.env[model_name]._table
            self.env.cr.execute(
                'SELECT id FROM "%s" WHERE id = %%s FOR UPDATE' % table,
                (record_id,),
            )

    def _sn_snapshot_fields(self):
        """Header fields compared when detecting a change of the other side."""
        return ()

    def _sn_take_snapshot(self, target):
        """Snapshot of the target document right after it was written."""
        self.ensure_one()
        snapshot = {
            field_name: str(target[field_name])
            for field_name in self._sn_snapshot_fields()
            if field_name in target._fields
        }
        return snapshot or False

    def _sn_last_snapshot(self):
        self.ensure_one()
        log = self.env['sn.intercompany.sync.log'].sudo().search([
            ('target_model', '=', self._name),
            ('target_id', '=', self.id),
            ('result', '=', 'success'),
            ('snapshot', '!=', False),
        ], limit=1, order='id desc')
        return log.snapshot if log else {}

    def _sn_detect_conflict(self, target, field_names=None):
        """Whether the other company modified the fields about to be written.

        Only the fields of the current change are compared: a difference on a
        field nobody touches now is a divergence to report, not a conflict
        blocking an unrelated update.
        """
        self.ensure_one()
        snapshot = target._sn_last_snapshot()
        if not snapshot:
            return False
        for field_name in (field_names or self._sn_snapshot_fields()):
            if field_name not in snapshot or field_name not in target._fields:
                continue
            if str(target[field_name]) != snapshot[field_name]:
                return True
        return False

    def _sn_quantities_match(self, source):
        """Whether the quantities of both documents still match, ignoring the
        executed part of the target document."""
        self.ensure_one()
        own = sum(self.order_line.mapped('product_qty')) \
            if self._name == 'purchase.order' \
            else sum(self.order_line.mapped('product_uom_qty'))
        other = sum(source.order_line.mapped('product_uom_qty')) \
            if self._name == 'purchase.order' \
            else sum(source.order_line.mapped('product_qty'))
        return abs(own - other) < 0.0001

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------
    def _sn_replay_sync(self):
        self.ensure_one()
        raise UserError(_(
            "%(document)s cannot replay its inter-company synchronization.",
            document=self.display_name))

    def _sn_replay_create(self, target_company, creator_method):
        """Create the missing counterpart again, used by the issue wizard."""
        self.ensure_one()
        if not target_company:
            raise UserError(_(
                "The counterpart company of %(document)s cannot be found.",
                document=self.display_name))
        user = self._sn_sync_user(target_company)
        return getattr(
            self.with_user(user)
                .with_context(default_company_id=target_company.id)
                .with_company(target_company),
            creator_method,
        )(target_company)

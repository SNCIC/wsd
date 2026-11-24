import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Kinds of entries in a push field list (see the F / C / K / T / N helpers)
KIND_FIELD = 'field'
KIND_CONFIG = 'config'
KIND_CONST = 'const'
KIND_CREATED = 'created'
KIND_CHILDREN = 'children'

# Operation kinds decided by the engine; the literal sent in the header
# comes from the interface table
OPERATE_ADD = 'add'
OPERATE_UPDATE = 'update'

# Status the platform returns when an ADD hits a document it already has
STATUS_DUPLICATE = '20006'


def F(key, path, add=False, update=False):
    """Payload key fed by a field of the record. ``path`` may be dotted
    (``category_id.code``). ``add`` / ``update``: required on ADD /
    on UPDATE (the UPDATE-required keys locate the document)."""
    return (key, KIND_FIELD, path, add, update)


def C(key, attribute, add=False, update=False):
    """Payload key fed by an attribute of the integration config."""
    return (key, KIND_CONFIG, attribute, add, update)


def K(key, value, add=False, update=False):
    """Payload key with a constant value."""
    return (key, KIND_CONST, value, add, update)


def T(key, add=False, update=False):
    """Payload key fed by the creation time of the record (or line)."""
    return (key, KIND_CREATED, None, add, update)


def N(key, lines_field, lines_spec):
    """Payload key holding a list fed by a one2many; ``lines_spec`` is
    the field list of the lines (the line model declares the same list
    as its ``EIP_LINES``)."""
    return (key, KIND_CHILDREN, (lines_field, lines_spec), False, False)


def _is_empty(value):
    return value is None or value is False or value == ''


class EipPushMixin(models.AbstractModel):
    """Shared behaviour of every document pushed to the EIP platform.

    Each model declares its interface code and its field list
    (``EIP_FIELDS``); that single list drives everything: building the
    payload, the required-field gate, the locate keys of an UPDATE and
    the diff against the last pushed values. The operation type is
    decided here: ADD until a push succeeded, UPDATE afterwards.
    """

    _name = 'sn.wsd.eip.push.mixin'
    _description = 'EIP Push Mixin'

    EIP_INTERFACE = None
    EIP_SEQUENCE = None
    EIP_FIELDS = ()

    push_state = fields.Selection(
        [('draft', 'Draft'), ('to_push', 'Queued'), ('pushing', 'Pushing'),
         ('pushed', 'Pushed'), ('failed', 'Failed')],
        string='Push Status', required=True, default='draft', index=True,
        copy=False)
    eip_synced = fields.Boolean(
        string='Pushed Before', default=False, copy=False,
        help='A push already succeeded: the next one is an UPDATE and '
             'the keys locating the document can no longer change.')
    eip_snapshot = fields.Text(
        string='Last Pushed Values', readonly=True, copy=False,
        help='Complete values at the time of the last successful push; '
             'the UPDATE payload is the difference against it.')
    eip_push_count = fields.Integer(
        string='Successful Pushes', default=0, copy=False)
    eip_first_push_at = fields.Datetime(string='First Pushed On', copy=False)
    eip_last_push_at = fields.Datetime(string='Last Pushed On', copy=False)
    eip_last_log_id = fields.Many2one(
        'sn.wsd.eip.push.log', string='Last Push Log', copy=False,
        ondelete='set null')
    eip_last_error = fields.Text(string='Last Push Error', copy=False)
    eip_log_count = fields.Integer(string='Push Logs', compute='_compute_eip_log_count')
    eip_missing = fields.Text(
        string='Missing Required Fields', compute='_compute_eip_missing',
        help='Required fields still empty for the next push.')

    # ------------------------------------------------------------------
    # where the values come from
    # ------------------------------------------------------------------

    def _eip_push_config(self):
        self.ensure_one()
        return self.env['sn.wsd.eip.config']._eip_config_for(self.company_id)

    def _eip_push_interface(self):
        return self.env['sn.wsd.eip.interface']._eip_interface(
            self.EIP_INTERFACE)

    def _eip_document_ref(self):
        """Human-readable key shown on the push logs (the number)."""
        self.ensure_one()
        return ''

    @api.model
    def _eip_new_number(self):
        """Next number of the document sequence: a company-specific
        sequence wins over the shared one."""
        return self.env['ir.sequence'].with_company(
            self.env.company).next_by_code(self.EIP_SEQUENCE) or False

    @api.model
    def _eip_format(self, record, path):
        """Value of ``path`` on ``record`` in its payload form; an
        empty value is the empty string."""
        head, _, tail = path.partition('.')
        value = record[head]
        if not value:
            return ''
        if tail:
            return self._eip_format(value, tail)
        field = record._fields[head]
        transport = self.env['sn.wsd.eip.transport']
        if field.type == 'date':
            return transport._eip_format_date(value)
        if field.type == 'datetime':
            return transport._eip_format_datetime(value)
        if field.type in ('integer', 'float'):
            return value
        return str(value)

    def _eip_scalar(self, kind, arg, config):
        """Payload value of one non-list entry for ``self``."""
        if kind == KIND_FIELD:
            return self._eip_format(self, arg)
        if kind == KIND_CONFIG:
            return getattr(config, arg, '') if config else ''
        if kind == KIND_CONST:
            return arg
        # KIND_CREATED
        return self.env['sn.wsd.eip.transport']._eip_format_datetime(
            self.create_date)

    def _eip_values(self, config, spec=None):
        """Complete current values of one record as a payload-shaped
        dict (children as lists of dicts)."""
        self.ensure_one()
        values = {}
        for key, kind, arg, _add, _update in (spec or self.EIP_FIELDS):
            if kind == KIND_CHILDREN:
                lines_field, lines_spec = arg
                values[key] = [
                    line._eip_values(config, lines_spec)
                    for line in self[lines_field]]
            else:
                values[key] = self._eip_scalar(kind, arg, config)
        return values

    def _eip_label(self, kind, arg, key):
        if kind == KIND_FIELD:
            field = self._fields[arg.partition('.')[0]]
            return field._description_string(self.env)
        if kind == KIND_CONFIG:
            field = self.env['sn.wsd.eip.config']._fields[arg]
            return field._description_string(self.env)
        if kind == KIND_CREATED:
            return _('Source Data Created Time')
        return {'dataSource': _('Data Source')}.get(key, key)

    def _eip_missing(self, operatetype, config=None, spec=None, prefix=''):
        """Labels of the fields that ``operatetype`` requires and that
        are empty, lines included. Never raises: usable in computes."""
        self.ensure_one()
        if config is None:
            config = self.env['sn.wsd.eip.config'].search([
                ('company_id', '=', self.company_id.id),
                ('active', '=', True)], limit=1)
        missing = []
        for key, kind, arg, add, update in (spec or self.EIP_FIELDS):
            if kind == KIND_CHILDREN:
                lines_field, lines_spec = arg
                list_label = self._fields[
                    lines_field]._description_string(self.env)
                for index, line in enumerate(self[lines_field], 1):
                    missing += line._eip_missing(
                        operatetype, config, lines_spec,
                        prefix='%s %s: ' % (list_label, index))
                continue
            if not (add if operatetype == OPERATE_ADD else update):
                continue
            if _is_empty(self._eip_scalar(kind, arg, config)):
                missing.append(prefix + self._eip_label(kind, arg, key))
        return missing

    # ------------------------------------------------------------------
    # payload
    # ------------------------------------------------------------------

    def _eip_operatetype(self):
        self.ensure_one()
        return OPERATE_UPDATE if self.eip_synced else OPERATE_ADD

    def _eip_build_body(self, operatetype, config, baseline=None):
        """Payload to send.

        ADD (and UPDATE in "full" mode) carries every current value. An
        UPDATE in "diff" mode follows the spec's update rules: the keys
        are all there; a locate key (UPDATE-required) carries its real
        value, an unchanged field the empty string, a changed field its
        new value and a cleared field the string "null". Child lists
        always carry every current line.

        ``baseline``: the values the platform is known to hold; the
        default is the snapshot of the last successful push.
        """
        self.ensure_one()
        current = self._eip_values(config)
        if operatetype == OPERATE_ADD or config.update_mode == 'full':
            return current
        if baseline is None:
            baseline = json.loads(self.eip_snapshot) if self.eip_snapshot else {}
        body = {}
        for key, kind, _arg, _add, update in self.EIP_FIELDS:
            new = current[key]
            if kind == KIND_CHILDREN or update:
                body[key] = new
                continue
            old = baseline.get(key, '')
            if _is_empty(new) and _is_empty(old):
                body[key] = ''
            elif new == old:
                body[key] = ''
            elif _is_empty(new):
                body[key] = 'null'
            else:
                body[key] = new
        return body

    # ------------------------------------------------------------------
    # push
    # ------------------------------------------------------------------

    def _eip_log_extra(self):
        self.ensure_one()
        return {
            'model_name': self._name,
            'res_id': self.id,
            'document_ref': self._eip_document_ref(),
        }

    def _eip_send_as(self, operatetype, config, interface, baseline=None):
        """Send one request with the given operation kind and return the
        call result, extended with the operation kind and the values it
        carried."""
        transport = self.env['sn.wsd.eip.transport']
        body = self._eip_build_body(operatetype, config, baseline)
        literal = (interface.operatetype_add if operatetype == OPERATE_ADD
                   else interface.operatetype_update)
        log = transport._eip_open_log(
            config, interface, literal, body, self._eip_log_extra())
        result = transport._eip_send(log, body)
        result['operatetype'] = operatetype
        result['values'] = self._eip_values(config)
        return result

    def _eip_push_one(self):
        """Push this one document now (button and queue worker).

        Required fields are checked first: a gap is reported without
        any request. An absent config or a disabled interface raises
        before any request; transport and platform failures are
        reported in the returned result.
        """
        self.ensure_one()
        config = self._eip_push_config()
        interface = self._eip_push_interface()
        operatetype = self._eip_operatetype()
        missing = self._eip_missing(operatetype, config=config)
        if missing:
            error = _('Missing required fields: %s', ', '.join(missing))
            self.write({'push_state': 'failed', 'eip_last_error': error})
            return {'success': False, 'sent': False, 'retryable': False,
                    'error': error, 'status': '', 'log_id': False,
                    'operatetype': operatetype}
        self.write({'push_state': 'pushing'})
        result = self._eip_send_as(operatetype, config, interface)
        if operatetype == OPERATE_ADD and result['status'] == STATUS_DUPLICATE:
            # the platform already has it (e.g. an earlier request
            # succeeded but its answer never got recorded): update it
            # against an empty baseline, so filled fields carry values
            result = self._eip_send_as(
                OPERATE_UPDATE, config, interface, baseline={})
        self._eip_apply_push_result(result, config)
        return result

    def _eip_apply_push_result(self, result, config):
        """Write the outcome of a request on the document."""
        self.ensure_one()
        if result['success']:
            self.write({
                'push_state': 'pushed',
                'eip_synced': True,
                'eip_snapshot': json.dumps(
                    result['values'], ensure_ascii=False),
                'eip_push_count': self.eip_push_count + 1,
                'eip_first_push_at': self.eip_first_push_at
                or fields.Datetime.now(),
                'eip_last_push_at': fields.Datetime.now(),
                'eip_last_log_id': result['log_id'] or self.eip_last_log_id.id,
                'eip_last_error': False,
            })
            self._eip_on_push_success(result)
        else:
            self.write({
                'push_state': 'failed',
                'eip_last_error': result['error'],
                'eip_last_log_id': result['log_id'] or self.eip_last_log_id.id,
            })

    def _eip_on_push_success(self, result):
        """Hook after a successful push (e.g. write back IDs the
        platform returned). The engine fields are already written."""

    # ------------------------------------------------------------------
    # locate keys are frozen once the platform knows the document
    # ------------------------------------------------------------------

    def _eip_locate_fields(self):
        """Main-model fields an UPDATE locates the document by."""
        return {
            arg.partition('.')[0]
            for _key, kind, arg, _add, update in self.EIP_FIELDS
            if update and kind == KIND_FIELD}

    def write(self, vals):
        locate = self._eip_locate_fields()
        touched = locate & set(vals)
        if touched:
            for record in self:
                if not record.eip_synced:
                    continue
                changed = []
                for name in touched:
                    old = record[name]
                    new = vals[name]
                    # many2one values arrive as records on one side and
                    # ids on the other: compare ids, and treat blanks alike
                    if isinstance(old, models.BaseModel):
                        old = old.id
                    if isinstance(new, models.BaseModel):
                        new = new.id
                    if (old or None) != (new or None):
                        changed.append(name)
                if changed:
                    raise UserError(_(
                        'Cannot change %s: the document was already '
                        'pushed to EIP and these keys locate it there.',
                        ', '.join(
                            record._fields[name]._description_string(
                                record.env)
                            for name in sorted(changed))))
        return super().write(vals)

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------

    @api.model
    def _eip_missing_depends(self):
        """Every field the missing-fields compute reads, lines included,
        so the value follows edits in the form."""
        depends = ['eip_synced', 'create_date']
        for _key, kind, arg, _add, _update in self.EIP_FIELDS:
            if kind == KIND_FIELD:
                depends.append(arg)
            elif kind == KIND_CHILDREN:
                lines_field, lines_spec = arg
                depends.append(lines_field)
                for _k, k, a, _ad, _u in lines_spec:
                    if k == KIND_FIELD:
                        depends.append('%s.%s' % (lines_field, a))
                    elif k == KIND_CREATED:
                        depends.append('%s.create_date' % lines_field)
        return depends

    @api.depends(lambda self: tuple(self._eip_missing_depends()))
    def _compute_eip_missing(self):
        for record in self:
            missing = record._eip_missing(record._eip_operatetype())
            record.eip_missing = ', '.join(missing) if missing else False

    def _compute_eip_log_count(self):
        groups = self.env['sn.wsd.eip.push.log'].sudo()._read_group(
            [('model_name', '=', self._name), ('res_id', 'in', self.ids)],
            ['res_id'], ['__count'])
        counts = {res_id: count for res_id, count in groups}
        for record in self:
            record.eip_log_count = counts.get(record.id, 0)

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError


class SnLabelReader(models.AbstractModel):
    """Model-agnostic field reader for label rendering.

    ``field_path`` dot notation walks many2one hops and must end on a
    whitelisted scalar field type, so any business model can feed the
    label engine without depending on it (design decision: generic
    reader, zero business-module coupling).
    """

    _name = 'sn.label.reader'
    _description = 'Label Field Reader'

    TERMINAL_FIELD_TYPES = (
        'char', 'text', 'integer', 'float', 'date', 'datetime', 'selection',
        'many2one',
    )

    def check_records(self, records):
        """Gate every render entry point on record-level read access."""
        records.check_access('read')

    def validate_field_path(self, model_name, field_path):
        if not field_path or not isinstance(field_path, str):
            raise ValidationError(_('The label field path cannot be empty.'))
        try:
            model = self.env[model_name]
        except KeyError:
            raise UserError(_('Unknown model %s in label field path.', model_name))
        hops = [hop.strip() for hop in field_path.split('.')]
        if any(not hop for hop in hops):
            raise ValidationError(
                _('The label field path %s contains an empty segment.', field_path))
        for index, hop in enumerate(hops):
            field = model._fields.get(hop)
            if field is None:
                raise ValidationError(
                    _('Unknown field %s in label field path %s.', hop, field_path))
            is_last = index == len(hops) - 1
            if is_last:
                if field.type not in self.TERMINAL_FIELD_TYPES:
                    raise ValidationError(
                        _('Field %s (type %s) cannot be printed on a label: %s.',
                          hop, field.type, field_path))
            elif field.type != 'many2one':
                raise ValidationError(
                    _('Only many2one hops are allowed in label field path %s '
                      '(field %s is a %s).', field_path, hop, field.type))
            else:
                model = self.env[field.comodel_name]
        return True

    def read_value(self, record, field_path):
        self.validate_field_path(record._name, field_path)
        hops = field_path.split('.')
        container = record
        for hop in hops[:-1]:
            container = container[hop]
        value = container[hops[-1]]
        # format with the record that owns the terminal field, not the root:
        # the root model may not even have that field name
        return self._format_value(container, hops[-1], value)

    def _format_value(self, record, field_name, value):
        field = record._fields[field_name]
        if field.type == 'many2one':
            return value.display_name or ''
        if value in (None, False, ''):
            return ''
        if field.type == 'float':
            quantity = f'{float(value):.6f}'.rstrip('0').rstrip('.')
            return quantity or '0'
        if field.type == 'selection':
            selection = record.fields_get([field_name])[field_name]['selection']
            labels = dict(selection) if selection else {}
            return str(labels.get(value, value))
        return str(value)

    @api.model
    def field_path_options(self, model_name):
        """Selectable field paths for the designer dropdown: direct
        whitelisted fields plus one many2one hop, labeled for humans."""
        options = []

        def collect(model, prefix, label_prefix):
            for name, description in sorted(
                    model.fields_get().items(),
                    key=lambda item: item[1].get('string') or item[0]):
                if name == 'id':
                    continue
                field_type = description.get('type')
                label = f"{label_prefix}{description.get('string') or name}"
                if field_type == 'many2one':
                    # usable directly (display_name) and as a one-hop source
                    options.append((f"{prefix}{name}", label))
                    if not prefix:
                        comodel = self.env.get(description.get('relation'))
                        if comodel is not None:
                            collect(comodel, f"{name}.", f"{label} / ")
                elif field_type in self.TERMINAL_FIELD_TYPES:
                    options.append((f"{prefix}{name}", label))

        model = self.env.get(model_name)
        # an empty recordset is falsy but valid: only skip unknown models
        if model is not None:
            collect(model, '', '')
        return options

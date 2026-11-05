from odoo import api, models


class SnSupplierCodeSeed(models.AbstractModel):
    """Seeds the supplier coding rule — group code + three-digit serial, with
    one engine counter per group — and seeds those counters from the
    references already on file, so the first generated code continues the
    numbering the account uses instead of colliding with it.

    Both seeders are idempotent: an existing rule for the model wins, and an
    existing counter row wins over a recomputed one."""

    _name = 'sn.supplier.code.seed'
    _description = 'Supplier Code Rule Seeder'

    FIELD_PATH = 'supplier_categ_id.code'
    LEGACY_FIELD_PATH = 'supplier_categ_id.prefix'

    @api.model
    def _seed_supplier_code_rule(self):
        Rule = self.env['sn.code.rule']
        model_id = self.env['ir.model']._get_id('res.partner')
        if not model_id:
            return
        existing = Rule.search([
            ('model_id', '=', model_id),
            ('picking_type_id', '=', False)], limit=1)
        if existing:
            self._refresh_supplier_code_rule(existing)
            return
        Rule.create({
            'name': 'Supplier Code',
            'model_id': model_id,
            'target_field': 'ref',
            'separator': '.',
            'segment_ids': [
                (0, 0, {
                    'sequence': 10,
                    'segment_type': 'field',
                    'field_path': self.FIELD_PATH,
                    'empty_policy': 'error',
                }),
                (0, 0, {
                    'sequence': 20,
                    'segment_type': 'seq',
                    'padding': 3,
                    'number_next': 1,
                    'period': 'none',
                    'seq_impl': 'engine',
                    'group_field_paths': self.FIELD_PATH,
                }),
            ],
        })

    @api.model
    def _refresh_supplier_code_rule(self, rule):
        """Repoint a rule seeded by an earlier version at the group code: a
        sub-group numbers its suppliers with its own full number (10.002.xxx)
        and keeps its own serial, so the segment reads the group code. Only
        the legacy path is rewritten, hand-made edits are left alone."""
        for segment in rule.segment_ids:
            if segment.field_path == self.LEGACY_FIELD_PATH:
                segment.field_path = self.FIELD_PATH
            if (segment.group_field_paths or '').strip() == self.LEGACY_FIELD_PATH:
                segment.group_field_paths = self.FIELD_PATH

    @api.model
    def _seed_supplier_counters(self):
        """Seed one counter row per coded group from the numeric tails of the
        references already on file. Idempotent, and independent of the groups
        having been assigned to the existing partners yet: a coded group gets
        its start value as soon as its code is filled in."""
        rule = self._supplier_code_rule()
        segment = self._supplier_seq_segment(rule)
        if not segment:
            return
        groups = self.env['sn.wsd.supplier.group'].sudo().search([])
        for group in groups:
            self._seed_supplier_counter(rule, self._group_probe(group))

    @api.model
    def _group_probe(self, group):
        """Unsaved contact standing for a group: both the counter key and the
        references on file are read from the group itself, so the counters can
        be seeded before the group is assigned to any contact."""
        return self.env['res.partner'].new({'supplier_categ_id': group.id})

    @api.model
    def _supplier_code_rule(self):
        model_id = self.env['ir.model']._get_id('res.partner')
        if not model_id:
            return self.env['sn.code.rule']
        return self.env['sn.code.rule'].search([
            ('model_id', '=', model_id),
            ('target_field', '=', 'ref'),
        ], limit=1)

    @api.model
    def _supplier_seq_segment(self, rule):
        """The single sequence segment of the rule, or an empty recordset when
        the rule is missing or carries more than one (nothing to seed then)."""
        if not rule:
            return self.env['sn.code.rule.segment']
        segments = rule.segment_ids.filtered(
            lambda item: item.segment_type == 'seq')
        return segments if len(segments) == 1 else self.env['sn.code.rule.segment']

    @api.model
    def _seed_supplier_counter(self, rule, partner):
        """Give the group of ``partner`` the start value that follows the
        references it already carries (the rule's start value when the group
        has none yet). The row is written here, with the seeding rights, so
        that day-to-day users only ever hit the engine's row update."""
        segment = self._supplier_seq_segment(rule)
        if not segment or not partner.supplier_categ_id:
            return
        key = segment._sequence_key(partner)
        Counter = self.env['sn.code.counter'].sudo()
        if Counter.search_count([
                ('segment_id', '=', segment.id), ('key', '=', key)]):
            return
        max_tail = self.group_max_tail(rule, partner)
        if not max_tail:
            max_tail = segment.number_next - 1
        try:
            with self.env.cr.savepoint():
                Counter.create({
                    'segment_id': segment.id,
                    'key': key,
                    'value': max_tail,
                })
        except Exception:
            # a concurrent transaction seeded the same key first: keep its row
            pass

    @api.model
    def group_max_tail(self, rule, partner):
        """Largest serial already used inside the group of ``partner``: the
        references are read as ``<group code><separator><serial>``, so a group
        continues its own numbering (the fees sub-group from its own 10.002.xxx
        references, the fees group itself from its 10.xxx ones), and entries
        that do not start with a plain number are skipped."""
        code = partner.supplier_categ_id.code or ''
        if not code:
            return 0
        separator = rule.separator or ''
        prefix = '%s%s' % (code, separator)
        pattern = self._like_literal(prefix) + '%'
        references = self.env['res.partner'].sudo().search([
            ('ref', '=like', pattern),
        ]).mapped('ref')
        max_tail = 0
        for reference in references:
            reference = (reference or '').strip()
            if not reference.startswith(prefix):
                continue
            tail = reference[len(prefix):]
            if separator:
                tail = tail.split(separator)[0]
            if tail.isdigit():
                max_tail = max(max_tail, int(tail))
        return max_tail

    @api.model
    def _like_literal(self, value):
        """Escape the LIKE wildcards of a literal prefix: the group code is
        free text, so an underscore in it must not match any character."""
        value = value.replace('\\', '\\\\')
        value = value.replace('%', '\\%')
        return value.replace('_', '\\_')

from odoo import api, models


class SnSerialIdentityCodeSeed(models.AbstractModel):
    """Seeds the default coding rule for product SN reservation (drawing
    number + 5-digit serial, engine counter grouped per product, no time
    reset — mirroring the legacy sequence format exactly) and backfills
    each product's counter from the numeric tails of its existing
    identities, so the first rule-generated number continues the old
    sequence without overlaps or gaps. Idempotent: an existing rule for
    the model (active or not) wins."""

    _name = 'sn.serial.identity.code.seed'
    _description = 'Product SN Coding Rule Seeder'

    @api.model
    def _seed_serial_sn_rule(self):
        Rule = self.env['sn.code.rule']
        model_id = self.env['ir.model']._get_id('sn.wsd.serial.identity')
        if not model_id or Rule.search_count([
                ('model_id', '=', model_id), ('picking_type_id', '=', False)]):
            return
        rule = self.env['sn.code.rule'].create({
            'name': 'Product SN Coding',
            'model_id': model_id,
            'target_field': 'name',
            'separator': '',
            'segment_ids': [
                (0, 0, {
                    'segment_type': 'field',
                    'field_path':
                        'origin_production_id.product_id.default_code',
                    'empty_policy': 'blank',
                }),
                (0, 0, {
                    'segment_type': 'seq',
                    'padding': 5,
                    'period': 'none',
                    'seq_impl': 'engine',
                    'group_field_paths':
                        'origin_production_id.product_id.default_code',
                }),
            ],
        })
        self._backfill_identity_counters(rule)

    @api.model
    def _backfill_identity_counters(self, rule):
        """Seed each production's engine counter from the numeric tails of
        its existing identities; names that don't parse are skipped."""
        seq_segment = rule.segment_ids.filtered(
            lambda segment: segment.segment_type == 'seq')
        if not seq_segment:
            return
        Counter = self.env['sn.code.counter'].sudo()
        Identity = self.env['sn.wsd.serial.identity'].sudo()
        # aggregate per drawing number (several productions may share one
        # product): one counter row per prefix, max tail across them all
        tails_by_prefix = {}
        for production in self.env['mrp.production'].sudo().search([]):
            prefix = production.product_id.default_code or ''
            identities = Identity.search([
                ('origin_production_id', '=', production.id)])
            for identity in identities:
                tail = identity.name[len(prefix):] if prefix else identity.name
                if tail and tail.isdigit():
                    tails_by_prefix[prefix] = max(
                        tails_by_prefix.get(prefix, 0), int(tail))
        for prefix, max_tail in tails_by_prefix.items():
            if max_tail:
                Counter.create({
                    'segment_id': seq_segment.id,
                    'key': prefix,
                    'value': max_tail,
                })

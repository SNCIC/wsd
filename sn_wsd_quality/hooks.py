LOT_RANGE_CODES = [
    (2, 8, 'A'), (9, 15, 'B'), (16, 25, 'C'), (26, 50, 'D'),
    (51, 90, 'E'), (91, 150, 'F'), (151, 280, 'G'), (281, 500, 'H'),
    (501, 1200, 'J'), (1201, 3200, 'K'), (3201, 10000, 'L'),
    (10001, 35000, 'M'), (35001, 150000, 'N'), (150001, 500000, 'P'),
    (500001, 999999999, 'Q'),
]
SAMPLE_SIZES = {
    'A': 2, 'B': 3, 'C': 5, 'D': 8, 'E': 13, 'F': 20, 'G': 32,
    'H': 50, 'J': 80, 'K': 125, 'L': 200, 'M': 315, 'N': 500,
    'P': 800, 'Q': 1250,
}
AQL_VALUES = (0.65, 1.0, 1.5, 2.5, 4.0)


def _accept_reject(sample_size, aql_value):
    if aql_value == 0.65:
        return 0, 1
    if aql_value == 1.0:
        return (1, 2) if sample_size >= 20 else (0, 1)
    if aql_value == 1.5:
        return (1, 2) if sample_size >= 20 else (0, 1)
    if aql_value == 2.5:
        return (2, 3) if sample_size >= 20 else (1, 2)
    return (3, 4) if sample_size >= 20 else (1, 2)


def post_init_hook(env):
    standard_model = env['sn.wsd.quality.sampling.standard']
    standard = standard_model.search([('code', '=', 'GB2828-G2')], limit=1)
    if not standard:
        standard = standard_model.create({
            'name': 'GB/T 2828.1 General II Baseline',
            'code': 'GB2828-G2',
            'note': 'Baseline AQL matrix for IQC. Quality engineering must approve values before production use.',
        })
    range_model = env['sn.wsd.quality.sampling.lot.range']
    for lot_min, lot_max, code in LOT_RANGE_CODES:
        if not range_model.search_count([
            ('standard_id', '=', standard.id),
            ('inspection_level', '=', 'g2'),
            ('lot_qty_min', '=', lot_min),
            ('lot_qty_max', '=', lot_max),
        ]):
            range_model.create({
                'standard_id': standard.id,
                'inspection_level': 'g2',
                'lot_qty_min': lot_min,
                'lot_qty_max': lot_max,
                'sample_size_code': code,
            })
    plan_model = env['sn.wsd.quality.sampling.plan']
    for mode in ('normal', 'tightened', 'reduced'):
        for aql_value in AQL_VALUES:
            for code, sample_size in SAMPLE_SIZES.items():
                if plan_model.search_count([
                    ('standard_id', '=', standard.id),
                    ('switching_mode', '=', mode),
                    ('sample_size_code', '=', code),
                    ('aql_value', '=', aql_value),
                ]):
                    continue
                accept_qty, reject_qty = _accept_reject(sample_size, aql_value)
                if mode == 'tightened':
                    accept_qty = max(0, accept_qty - 1)
                    reject_qty = max(accept_qty + 1, reject_qty - 1)
                elif mode == 'reduced':
                    accept_qty += 1
                    reject_qty += 1
                plan_model.create({
                    'standard_id': standard.id,
                    'switching_mode': mode,
                    'sample_size_code': code,
                    'sample_size': sample_size,
                    'aql_value': aql_value,
                    'accept_qty': accept_qty,
                    'reject_qty': reject_qty,
                })

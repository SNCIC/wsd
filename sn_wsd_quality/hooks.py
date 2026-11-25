def post_init_hook(env):
    """Seed the baseline standard with the GB/T 2828.1 master table.

    The matrix is generated from the standard's own rules (see
    ``QualitySamplingStandard._generate_gb2828_matrix``) instead of a
    transcribed subset, so every inspection level, switching mode and AQL
    column a scheme can ask for is covered from the first install.
    """
    standard_model = env['sn.wsd.quality.sampling.standard']
    standard = standard_model.search([('code', '=', 'GB2828-G2')], limit=1)
    if not standard:
        standard = standard_model.create({
            'name': 'GB/T 2828.1 Baseline',
            'code': 'GB2828-G2',
            'note': 'Baseline AQL matrix for IQC. Quality engineering must approve values before production use.',
        })
    standard._generate_gb2828_matrix(overwrite=False)

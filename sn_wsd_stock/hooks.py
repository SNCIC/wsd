def post_init_hook(env):
    """Preset the types of the other receipts and other deliveries."""
    env['sn.wsd.stock.other.operation.type']._ensure_default_types()

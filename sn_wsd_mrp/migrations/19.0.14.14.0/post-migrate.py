from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Materialise the line-side replenishment rules of every workshop store.

    The rules are derived from the workshop configuration (component location
    -> warehouse stock -> production), so the workshops configured before this
    version need one pass to create them. Without the rules the component
    demand of a workshop manufacturing order starts at a location the native
    stock -> production MTO rule never reaches, and every run silently skips
    the child manufacturing orders of the sub-level BOM.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    # sn_wsd_stock extends stock.rule with a required weekend policy. The post
    # migration runs before that inheritance is registered, so the ORM does not
    # send the column and its NOT NULL constraint would reject every rule
    # created here. A column default keeps those inserts valid; the ORM keeps
    # writing the value explicitly once the field is registered at runtime.
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'stock_rule'
           AND column_name = 'weekend_policy'
    """)
    if cr.fetchone() and 'weekend_policy' not in env['stock.rule']._fields:
        cr.execute("""
            ALTER TABLE stock_rule
            ALTER COLUMN weekend_policy SET DEFAULT 'none'
        """)
    workshops = env['sn.mrp.workshop'].search([('component_location_id', '!=', False)])
    workshops._ensure_line_side_replenishment()

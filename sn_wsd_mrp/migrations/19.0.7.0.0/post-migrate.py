import logging

from psycopg2 import sql as psycopg2_sql

from odoo.tools import sql


_logger = logging.getLogger(__name__)


def _tables_with_column(cr, column_name):
    cr.execute(
        """
        SELECT table_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND column_name = %s
        """,
        (column_name,),
    )
    return [row[0] for row in cr.fetchall()]


def _drop_column(cr, table_name, column_name):
    if sql.table_exists(cr, table_name) and sql.column_exists(cr, table_name, column_name):
        cr.execute(
            psycopg2_sql.SQL('ALTER TABLE {} DROP COLUMN {} CASCADE').format(
                psycopg2_sql.Identifier(table_name),
                psycopg2_sql.Identifier(column_name),
            )
        )


def _unique_mes_order_from_production(cr, table_name):
    if not sql.column_exists(cr, table_name, 'production_id') or not sql.column_exists(cr, table_name, 'mes_order_id'):
        return
    cr.execute(
        f"""
        WITH unique_orders AS (
            SELECT production_id, MIN(id) AS mes_order_id
              FROM sn_wsd_mes_order
             GROUP BY production_id
            HAVING COUNT(*) = 1
        )
        UPDATE {table_name} target
           SET mes_order_id = unique_orders.mes_order_id
          FROM unique_orders
         WHERE target.production_id = unique_orders.production_id
           AND target.mes_order_id IS NULL
        """
    )


def _unique_mes_order_from_batch(cr, table_name):
    if not sql.column_exists(cr, table_name, 'manufacturing_batch_id') or not sql.column_exists(cr, table_name, 'mes_order_id'):
        return
    if not sql.table_exists(cr, 'sn_wsd_manufacturing_batch'):
        return
    cr.execute(
        f"""
        WITH unique_orders AS (
            SELECT production.x_manufacturing_batch_id AS batch_id,
                   MIN(mes.id) AS mes_order_id
              FROM mrp_production production
              JOIN sn_wsd_mes_order mes
                ON mes.production_id = production.id
             WHERE production.x_manufacturing_batch_id IS NOT NULL
             GROUP BY production.x_manufacturing_batch_id
            HAVING COUNT(DISTINCT mes.id) = 1
        )
        UPDATE {table_name} target
           SET mes_order_id = unique_orders.mes_order_id
          FROM unique_orders
         WHERE target.manufacturing_batch_id = unique_orders.batch_id
           AND target.mes_order_id IS NULL
        """
    )


def _drop_model_metadata(cr):
    old_models = (
        'sn.wsd.manufacturing.batch',
        'sn.wsd.manufacturing.batch.operation',
    )
    cr.execute(
        """
        SELECT id
          FROM ir_model
         WHERE model = ANY(%s)
        """,
        (list(old_models),),
    )
    model_ids = [row[0] for row in cr.fetchall()]
    cr.execute(
        """
        SELECT res_id
          FROM ir_model_data
         WHERE model = 'ir.actions.act_window'
           AND (
               name LIKE '%%manufacturing_batch%%'
               OR res_id IN (
                   SELECT id
                     FROM ir_act_window
                    WHERE res_model = ANY(%s)
               )
           )
        """
        ,
        (list(old_models),),
    )
    action_ids = [row[0] for row in cr.fetchall()]
    cr.execute(
        """
        SELECT id
          FROM ir_act_window
         WHERE res_model = ANY(%s)
        """
        ,
        (list(old_models),),
    )
    action_ids = sorted(set(action_ids) | {row[0] for row in cr.fetchall()})
    if action_ids:
        cr.execute(
            'DELETE FROM ir_ui_menu WHERE action = ANY(%s)',
            ([f'ir.actions.act_window,{action_id}' for action_id in action_ids],),
        )
        cr.execute('DELETE FROM ir_actions WHERE id = ANY(%s)', (action_ids,))
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE name LIKE '%%manufacturing_batch%%'
        """
    )
    cr.execute(
        """
        DELETE FROM ir_ui_view
         WHERE model = ANY(%s)
        """
        ,
        (list(old_models),),
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = ANY(%s)
        """
        ,
        (list(old_models),),
    )
    cr.execute(
        """
        DELETE FROM ir_model_access
         WHERE model_id = ANY(%s)
        """
        ,
        (model_ids,),
    )
    cr.execute(
        """
        DELETE FROM ir_model_fields
         WHERE model_id = ANY(%s)
        """
        ,
        (model_ids,),
    )
    cr.execute(
        """
        DELETE FROM ir_model_constraint
         WHERE model = ANY(%s)
        """
        ,
        (model_ids,),
    )
    cr.execute(
        """
        DELETE FROM ir_model
         WHERE id = ANY(%s)
        """
        ,
        (model_ids,),
    )


def _drop_old_sequences(cr):
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = 'ir.sequence'
           AND (
               name LIKE '%%manufacturing_batch%%'
               OR res_id IN (
                   SELECT id
                     FROM ir_sequence
                    WHERE code = 'sn.wsd.manufacturing.batch'
               )
           )
        """
    )
    cr.execute(
        """
        DELETE FROM ir_sequence
         WHERE code = 'sn.wsd.manufacturing.batch'
        """
    )


def migrate(cr, version):
    if not version:
        return

    for table_name in _tables_with_column(cr, 'manufacturing_batch_id'):
        _unique_mes_order_from_production(cr, table_name)
        _unique_mes_order_from_batch(cr, table_name)

    if sql.table_exists(cr, 'mrp_production'):
        for column_name in ('x_manufacturing_batch_id', 'x_batch_role'):
            _drop_column(cr, 'mrp_production', column_name)
    _drop_column(cr, 'mrp_workorder', 'x_manufacturing_batch_id')
    _drop_column(cr, 'stock_package', 'x_wsd_manufacturing_batch_id')

    for table_name in _tables_with_column(cr, 'manufacturing_batch_id'):
        _drop_column(cr, table_name, 'manufacturing_batch_id')

    _drop_model_metadata(cr)
    _drop_old_sequences(cr)
    cr.execute('DROP TABLE IF EXISTS sn_wsd_manufacturing_batch_operation CASCADE')
    cr.execute('DROP TABLE IF EXISTS sn_wsd_manufacturing_batch CASCADE')
    _logger.info('sn_wsd_mrp 19.0.7.0.0: retired manufacturing batch data model and columns')

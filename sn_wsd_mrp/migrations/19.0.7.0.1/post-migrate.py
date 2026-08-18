from psycopg2 import sql as psycopg2_sql

from odoo.tools import sql


def _drop_column(cr, table_name, column_name):
    if sql.table_exists(cr, table_name) and sql.column_exists(cr, table_name, column_name):
        cr.execute(
            psycopg2_sql.SQL('ALTER TABLE {} DROP COLUMN {} CASCADE').format(
                psycopg2_sql.Identifier(table_name),
                psycopg2_sql.Identifier(column_name),
            )
        )


def migrate(cr, version):
    if not version:
        return

    _drop_column(cr, 'mrp_workorder', 'x_manufacturing_batch_id')
    _drop_column(cr, 'stock_package', 'x_wsd_manufacturing_batch_id')

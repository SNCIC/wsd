from odoo.tools import sql


OLD_MODELS = (
    'sn.wsd.manufacturing.batch',
    'sn.wsd.manufacturing.batch.operation',
    'sn.wsd.wip.batch.report',
)


def _delete_views(cr):
    cr.execute(
        """
        SELECT id
          FROM ir_ui_view
         WHERE model = ANY(%s)
            OR name LIKE '%%manufacturing_batch%%'
            OR name LIKE '%%wip.batch.report%%'
            OR arch_db::text ILIKE '%%manufacturing_batch_id%%'
            OR arch_db::text ILIKE '%%x_manufacturing_batch_id%%'
            OR arch_db::text ILIKE '%%sn.wsd.manufacturing.batch%%'
        """,
        (list(OLD_MODELS),),
    )
    view_ids = {row[0] for row in cr.fetchall()}
    if not view_ids:
        return

    # Include inherited views whose parent is one of the obsolete views.
    changed = True
    while changed:
        cr.execute(
            """
            SELECT id
              FROM ir_ui_view
             WHERE inherit_id = ANY(%s)
            """,
            (list(view_ids),),
        )
        inherited_ids = {row[0] for row in cr.fetchall()}
        new_ids = inherited_ids - view_ids
        changed = bool(new_ids)
        view_ids.update(new_ids)

    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = 'ir.ui.view'
           AND res_id = ANY(%s)
        """,
        (list(view_ids),),
    )
    cr.execute(
        """
        DELETE FROM ir_ui_view
         WHERE id = ANY(%s)
        """,
        (list(view_ids),),
    )


def _delete_obsolete_actions(cr):
    cr.execute(
        """
        SELECT id
          FROM ir_act_window
         WHERE res_model = ANY(%s)
        """,
        (list(OLD_MODELS),),
    )
    action_ids = {row[0] for row in cr.fetchall()}
    if not action_ids:
        return

    cr.execute(
        """
        DELETE FROM ir_ui_menu
         WHERE action = ANY(%s)
        """,
        ([f'ir.actions.act_window,{action_id}' for action_id in action_ids],),
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = 'ir.actions.act_window'
           AND res_id = ANY(%s)
        """,
        (list(action_ids),),
    )
    cr.execute(
        """
        DELETE FROM ir_actions
         WHERE id = ANY(%s)
        """,
        (list(action_ids),),
    )


def migrate(cr, version):
    if not version:
        return

    _delete_views(cr)
    _delete_obsolete_actions(cr)

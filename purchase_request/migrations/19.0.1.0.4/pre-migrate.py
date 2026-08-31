"""Remove the obsolete purchase request settings view before loading modules."""


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        DELETE FROM ir_ui_view
        WHERE id IN (
            SELECT res_id
            FROM ir_model_data
            WHERE module = 'purchase_request'
              AND name = 'res_config_settings_view_form_purchase_request'
              AND model = 'ir.ui.view'
        )
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'purchase_request'
          AND name = 'res_config_settings_view_form_purchase_request'
          AND model = 'ir.ui.view'
        """
    )

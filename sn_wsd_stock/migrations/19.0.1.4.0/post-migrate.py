from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Apply the redesigned incoming material label to existing databases.

    The seed data is intentionally noupdate so designers retain control of
    templates. This migration updates only the coordinates that are part of
    this release's built-in layout; subsequent designer changes are preserved.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    template = env.ref('sn_wsd_stock.label_template_incoming_material', raise_if_not_found=False)
    if not template:
        return

    values = {
        'label_element_incoming_line_row_1': {'y': 128},
        'label_element_incoming_line_row_2_left': {'y': 236},
        'label_element_incoming_line_row_3_left': {'y': 344},
        'label_element_incoming_line_row_4': {'y': 452},
        'label_element_incoming_line_col_1': {'height': 432},
        'label_element_incoming_line_col_2': {'height': 432},
        'label_element_incoming_line_col_3': {'height': 216},
        'label_element_incoming_line_qr_top': {'y': 236},
        'label_element_incoming_line_qr_left': {'y': 236, 'height': 216},
        'label_element_incoming_title_material_name': {'y': 128, 'height': 108},
        'label_element_incoming_title_quantity': {'y': 128, 'height': 108},
        'label_element_incoming_title_specification': {'y': 236, 'height': 108},
        'label_element_incoming_title_supplier': {'y': 344, 'height': 108},
        'label_element_incoming_value_material_code': {'height': 108},
        'label_element_incoming_value_supplier_batch': {'height': 108},
        'label_element_incoming_value_material_name': {'y': 128, 'height': 108},
        'label_element_incoming_value_quantity': {'y': 128, 'height': 108},
        'label_element_incoming_value_specification': {'y': 236, 'height': 108},
        'label_element_incoming_value_supplier_name': {'y': 344, 'height': 108},
        'label_element_incoming_qr_sn': {
            'x': 453, 'y': 245, 'width': 205, 'height': 205,
        },
    }
    for xmlid, element_values in values.items():
        element = env.ref(f'sn_wsd_stock.{xmlid}', raise_if_not_found=False)
        if element and element.template_id == template:
            element.write(element_values)

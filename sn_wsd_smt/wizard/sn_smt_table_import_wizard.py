from odoo import fields, models, _
from odoo.exceptions import ValidationError


REQUIRED_IMPORT_COLUMNS = ('ITEM_CODE', 'DEVICE_SEQ', 'TABLE_NO', 'LOADPOINT')
VALID_YN_VALUES = {'Y', 'N'}
VALID_TRACK_TYPES = {'single', 'dual'}


class SnSmtTableImportWizard(models.TransientModel):
    _name = 'sn.smt.table.import.wizard'
    _description = 'SMT Material Table Import Wizard'
    _inherit = 'sn.smt.table.import.mixin'

    table_id = fields.Many2one(
        'sn.smt.material.table',
        string='Material Table',
        required=True,
        check_company=True,
    )
    import_file = fields.Binary(string='CSV File', required=True)
    import_filename = fields.Char(string='Filename')
    clear_existing = fields.Boolean(string='Clear Existing Details', default=False)

    def action_import(self):
        self.ensure_one()
        rows = self._parse_import_file(self.import_file)
        if not rows:
            raise ValidationError(_('The import file is empty.'))

        self._validate_import_columns(rows)
        detail_vals_list = self._prepare_detail_vals_list(rows)
        self._validate_duplicate_positions(detail_vals_list)

        if self.clear_existing:
            self.table_id.detail_ids.unlink()
        else:
            self._validate_existing_positions(detail_vals_list)

        self.env['sn.smt.material.table.detail'].create(detail_vals_list)
        return {'type': 'ir.actions.act_window_close'}

    def _validate_import_columns(self, rows):
        fieldnames = set(rows[0].keys())
        missing_columns = [column for column in REQUIRED_IMPORT_COLUMNS if column not in fieldnames]
        if missing_columns:
            raise ValidationError(
                _('The import file is missing required columns: %s.') % ', '.join(missing_columns)
            )

    def _prepare_detail_vals_list(self, rows):
        detail_vals_list = []
        for row_number, row in enumerate(rows, start=2):
            if not any((value or '').strip() for value in row.values() if isinstance(value, str)):
                continue
            values = {
                'mt_id': self.table_id.id,
                'item_code': self._get_required_value(row, 'ITEM_CODE', row_number),
                'device_seq': self._get_integer_value(row, 'DEVICE_SEQ', row_number, required=True),
                'table_no': self._get_required_value(row, 'TABLE_NO', row_number),
                'loadpoint': self._get_required_value(row, 'LOADPOINT', row_number),
                'chanel_sn': self._get_value(row, 'CHANEL_SN'),
                'point_qty': self._get_integer_value(row, 'POINT_QTY', row_number),
                'feeder_spec': self._get_value(row, 'FEEDER_SPEC'),
                'is_tray': self._get_yn_value(row, 'IS_TRAY', row_number),
                'is_skip': self._get_yn_value(row, 'IS_SKIP', row_number),
                'track_type': self._get_track_type_value(row, row_number),
                'direction': self._get_value(row, 'DIRECTION'),
                'point_location': self._get_value(row, 'POINT_LOCATION'),
            }
            detail_vals_list.append(values)

        if not detail_vals_list:
            raise ValidationError(_('The import file does not contain any data rows.'))
        return detail_vals_list

    def _get_value(self, row, column):
        return (row.get(column) or '').strip()

    def _get_required_value(self, row, column, row_number):
        value = self._get_value(row, column)
        if not value:
            raise ValidationError(_('Row %(row)s: %(column)s is required.') % {
                'row': row_number,
                'column': column,
            })
        return value

    def _get_integer_value(self, row, column, row_number, required=False):
        value = self._get_value(row, column)
        if not value:
            if required:
                raise ValidationError(_('Row %(row)s: %(column)s is required.') % {
                    'row': row_number,
                    'column': column,
                })
            return 0
        try:
            integer_value = int(value)
        except ValueError as error:
            raise ValidationError(_('Row %(row)s: %(column)s must be an integer.') % {
                'row': row_number,
                'column': column,
            }) from error
        if integer_value < 0:
            raise ValidationError(_('Row %(row)s: %(column)s must not be negative.') % {
                'row': row_number,
                'column': column,
            })
        return integer_value

    def _get_yn_value(self, row, column, row_number):
        value = self._get_value(row, column).upper() or 'N'
        if value not in VALID_YN_VALUES:
            raise ValidationError(_('Row %(row)s: %(column)s must be Y or N.') % {
                'row': row_number,
                'column': column,
            })
        return value

    def _get_track_type_value(self, row, row_number):
        value = self._get_value(row, 'TRACK_TYPE') or self.table_id.track_type or 'single'
        if value not in VALID_TRACK_TYPES:
            raise ValidationError(_('Row %(row)s: TRACK_TYPE must be single or dual.') % {'row': row_number})
        return value

    def _validate_duplicate_positions(self, detail_vals_list):
        position_rows = {}
        for row_number, values in enumerate(detail_vals_list, start=2):
            position_key = self._get_position_key(values)
            if position_key in position_rows:
                raise ValidationError(
                    _('Rows %(first_row)s and %(second_row)s contain the same material position.') % {
                        'first_row': position_rows[position_key],
                        'second_row': row_number,
                    }
                )
            position_rows[position_key] = row_number

    def _validate_existing_positions(self, detail_vals_list):
        existing_keys = {
            self._get_position_key({
                'device_seq': detail.device_seq,
                'table_no': detail.table_no,
                'loadpoint': detail.loadpoint,
                'chanel_sn': detail.chanel_sn,
            })
            for detail in self.table_id.detail_ids
        }
        for row_number, values in enumerate(detail_vals_list, start=2):
            if self._get_position_key(values) in existing_keys:
                raise ValidationError(
                    _('Row %(row)s duplicates an existing material position. Select Clear Existing Details to replace all details.')
                    % {'row': row_number}
                )

    def _get_position_key(self, values):
        return (
            values['device_seq'],
            values['table_no'],
            values['loadpoint'],
            values['chanel_sn'],
        )

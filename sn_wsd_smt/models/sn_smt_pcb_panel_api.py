from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


MSG_PANEL_SAVE_SUCCESS = '\u4fdd\u5b58\u6210\u529f'
MSG_PRODUCT_SN_NOT_FOUND = '\u7b2c%s\u6761\u8bb0\u5f55\uff1a\u4ea7\u54c1SN[%s]\u4e0d\u5b58\u5728'


class SnSmtPcbPanelApi(models.AbstractModel):
    """
    SMT PCB panel API service.

    Provides JSON-2 endpoints for external MES integrations:
    - F-001 panel creation: create a panel and linked board SN records.
    - F-002 panel query: query panel board SN values by product SN.
    """
    _name = 'sn.smt.pcb.panel.api'
    _description = 'SMT PCB Panel API Service'

    @api.model
    def _service_ok(self, data=None, message='Success'):
        """Return a successful response."""
        response = {
            'code': 200,
            'message': message,
        }
        if data is not None:
            response['data'] = data
        return response

    @api.model
    def _service_error(self, code, message=''):
        """Return an error response."""
        return {
            'code': code,
            'message': message,
        }

    @api.model
    def _resolve_production(self, product_no):
        """
        Resolve the active SMT manufacturing order from a manufacturing batch number.

        :param product_no: Public order number field. The value is the manufacturing batch reference.
        :return: mrp.production record or False.
        """
        if not product_no:
            return False
        batch = self.env['sn.wsd.manufacturing.batch'].search([
            ('name', '=', product_no.strip()),
            ('company_id', 'in', self.env.companies.ids),
        ], limit=1)
        if not batch:
            return self.env['mrp.production']
        productions = batch.production_ids.filtered(
            lambda production: production.state not in ('done', 'cancel') and production.x_has_smt_operations
        )
        online = productions.filtered(lambda production: production.x_online_state == 'online')
        if online:
            productions = online
        in_progress = productions.filtered(lambda production: production.state in ('progress', 'to_close'))
        if in_progress:
            productions = in_progress
        return productions.sorted(lambda production: (production.backorder_sequence, production.date_start or fields.Datetime.now(), production.id))[:1]

    @api.model
    def _normalize_binding_sn_values(self, bindings):
        serial_numbers = []
        for binding in bindings:
            pro_sn = binding.get('proSn', '')
            pro_sn = pro_sn.strip() if isinstance(pro_sn, str) else str(pro_sn or '').strip()
            if pro_sn:
                serial_numbers.append(pro_sn)
        return serial_numbers

    @api.model
    def _validate_board_binding_scope(self, production, bindings):
        if not production:
            return {}
        serial_numbers = self._normalize_binding_sn_values(bindings)
        duplicate_serials = sorted({serial for serial in serial_numbers if serial_numbers.count(serial) > 1})
        if duplicate_serials:
            raise ValidationError(_('Duplicate board SN values in bindings: %s') % ', '.join(duplicate_serials))
        existing_boards = self.env['sn.smt.pcb.board'].search([
            ('panel_id.manufacturing_batch_id', '=', production.x_manufacturing_batch_id.id),
            ('pro_sn', 'in', serial_numbers),
            '|',
            ('state', '=', False),
            ('state', 'not in', ['voided', 'replaced']),
        ]) if production.x_manufacturing_batch_id else self.env['sn.smt.pcb.board'].search([
            ('panel_id.production_id', '=', production.id),
            ('pro_sn', 'in', serial_numbers),
            '|',
            ('state', '=', False),
            ('state', 'not in', ['voided', 'replaced']),
        ])
        if existing_boards:
            raise ValidationError(_('Board SN values are already bound to this manufacturing batch: %s') % ', '.join(sorted(existing_boards.mapped('pro_sn'))))

        if not self.env.registry.get('sn.wsd.laser.print.record.line'):
            raise ValidationError(_('SMT panel binding requires laser-generated board SN records.'))
        laser_domain = [
            ('record_id.sn_scope', '=', 'smt_pcb_board'),
            ('serial_no', 'in', serial_numbers),
        ]
        if production.x_manufacturing_batch_id:
            laser_domain.append(('production_id.x_manufacturing_batch_id', '=', production.x_manufacturing_batch_id.id))
        else:
            laser_domain.append(('production_id', '=', production.id))
        laser_lines = self.env['sn.wsd.laser.print.record.line'].search(laser_domain)
        laser_lines._ensure_internal_serials()
        laser_line_by_sn = {line.serial_no: line for line in laser_lines}
        for index, binding in enumerate(bindings, start=1):
            pro_sn = binding.get('proSn', '')
            pro_sn = pro_sn.strip() if isinstance(pro_sn, str) else str(pro_sn or '').strip()
            if pro_sn and pro_sn not in laser_line_by_sn:
                raise ValidationError(MSG_PRODUCT_SN_NOT_FOUND % (index, pro_sn))
        serial_by_name = {
            line.serial_no: line.internal_serial_id
            for line in laser_lines
            if line.internal_serial_id
        }
        for index, binding in enumerate(bindings, start=1):
            pro_sn = binding.get('proSn', '')
            pro_sn = pro_sn.strip() if isinstance(pro_sn, str) else str(pro_sn or '').strip()
            if pro_sn and pro_sn not in serial_by_name:
                raise ValidationError(MSG_PRODUCT_SN_NOT_FOUND % (index, pro_sn))
        already_bound_lines = laser_lines.filtered('pcb_board_id')
        if already_bound_lines:
            raise ValidationError(_('Board SN values are already linked to PCB boards: %s') % ', '.join(sorted(already_bound_lines.mapped('serial_no'))))
        return {
            'serial_by_name': serial_by_name,
            'laser_line_by_sn': laser_line_by_sn,
        }

    @api.model
    def api_panel_add(self, params):
        """
        F-001 panel creation.

        Operation:
        - Create a panel record.
        - Input fields: manufacturing batch number, panel quantity, PCB item code, and board SN list.
        - Link rule: group board records by panel quantity.
        """
        try:
            # Validate parameters.
            if not isinstance(params, dict):
                return self._service_error(400, _('Request parameters must be a JSON object.'))

            product_no = params.get('productNo', '')
            if isinstance(product_no, str):
                product_no = product_no.strip()
            else:
                product_no = str(product_no or '').strip()

            quantity = params.get('quantity')
            pcb_item_sn = params.get('pcbItemSn', '')
            if isinstance(pcb_item_sn, str):
                pcb_item_sn = pcb_item_sn.strip() or False
            else:
                pcb_item_sn = False

            bindings = params.get('bindings', [])

            if not product_no:
                return self._service_error(400, _('Order number (productNo) cannot be empty.'))
            if quantity is None:
                return self._service_error(400, _('Panel quantity (quantity) cannot be empty.'))
            try:
                quantity = int(quantity)
                if quantity < 1:
                    return self._service_error(400, _('Panel quantity (quantity) must be greater than 0.'))
            except (ValueError, TypeError):
                return self._service_error(400, _('Panel quantity (quantity) must be a number.'))

            if not bindings:
                return self._service_error(400, _('Board list (bindings) cannot be empty.'))

            if not isinstance(bindings, list):
                return self._service_error(400, _('bindings must be an array.'))

            # Validate bindings format.
            for idx, binding in enumerate(bindings, 1):
                if not isinstance(binding, dict):
                    return self._service_error(400, _('Binding %s has invalid format and must be an object.') % idx)
                pro_sn = binding.get('proSn', '')
                board_no = binding.get('boardNo')
                if not pro_sn:
                    return self._service_error(400, _('Binding %s is missing proSn.') % idx)
                if board_no is None:
                    return self._service_error(400, _('Binding %s is missing boardNo.') % idx)
                try:
                    int(board_no)
                except (TypeError, ValueError):
                    return self._service_error(400, _('Binding %s has invalid boardNo.') % idx)

            # productNo keeps the external field name, but its value is the manufacturing batch number.
            production = self._resolve_production(product_no)
            if not production:
                return self._service_error(400, _('Manufacturing batch has no active SMT manufacturing order.'))
            if production:
                production._check_smt_pcb_board_capacity(len(bindings))
            binding_scope = self._validate_board_binding_scope(production, bindings)

            # Create the panel record.
            panel_model = self.env['sn.smt.pcb.panel']
            create_vals = {
                'product_no': product_no,
                'quantity': quantity,
                'pcb_item_sn': pcb_item_sn,
                'state': 'confirmed',
            }
            if production:
                create_vals['production_id'] = production.id
                create_vals['company_id'] = production.company_id.id

            panel = panel_model.create(create_vals)

            # Create board records.
            for binding in bindings:
                board_vals = {
                    'panel_id': panel.id,
                    'board_no': int(binding.get('boardNo', 1)),
                    'pro_sn': binding.get('proSn', ''),
                }
                if isinstance(board_vals['pro_sn'], str):
                    board_vals['pro_sn'] = board_vals['pro_sn'].strip()

                board = self.env['sn.smt.pcb.board'].create(board_vals)

                if board.pro_sn:
                    laser_line = binding_scope.get('laser_line_by_sn', {}).get(board.pro_sn)
                    if laser_line:
                        laser_line.pcb_board_id = board

            return self._service_ok(message=MSG_PANEL_SAVE_SUCCESS)

        except ValidationError as e:
            return self._service_error(400, str(e))
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._service_error(400, _('System error: %s') % str(e))

    @api.model
    def api_panel_query(self, params):
        """
        F-002 panel query.

        Operation:
        - Query the panel by one board internal serial number.
        - Query result: all board internal serial numbers in the same panel.
        """
        try:
            if not isinstance(params, dict):
                return self._service_error(400, _('Request parameters must be a JSON object.'))

            pro_sn = params.get('proSn', '')
            if isinstance(pro_sn, str):
                pro_sn = pro_sn.strip()
            else:
                pro_sn = str(pro_sn or '').strip()

            if not pro_sn:
                return self._service_error(400, _('Field proSn cannot be empty.'))

            board = self.env['sn.smt.pcb.board'].search([
                ('pro_sn', '=', pro_sn),
                ('company_id', 'in', self.env.companies.ids),
                '|',
                ('state', '=', False),
                ('state', 'not in', ['voided', 'replaced']),
            ], limit=1)
            panel = board.panel_id
            if not panel:
                return self._service_error(400, _('Product SN [%s] does not exist.') % pro_sn)

            panel_boards = panel.board_ids.filtered(
                lambda item: item.state not in ('voided', 'replaced')
            ).sorted('board_no')
            product_sn_list = panel_boards.mapped('pro_sn')

            return self._service_ok(
                product_sn_list,
                _('Query successful.')
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._service_error(400, _('System error: %s') % str(e))

    @api.model
    def api_panel_detail(self, panel_id):
        """
        Query details by panel ID.

        :param panel_id: Panel record ID.
        """
        try:
            if not panel_id:
                return self._service_error(400, _('panel_id cannot be empty.'))

            try:
                panel_id = int(panel_id)
            except (ValueError, TypeError):
                return self._service_error(400, _('panel_id must be a number.'))

            panel = self.env['sn.smt.pcb.panel'].browse(panel_id).exists()
            if not panel:
                return self._service_error(404, _('Panel record does not exist (ID: %s).') % panel_id)

            return self._service_ok(
                panel.to_api_response(),
                _('Query successful.')
            )

        except Exception as e:
            return self._service_error(400, _('System error: %s') % str(e))

    @api.model
    def api_panel_delete(self, panel_id):
        """
        Delete a panel record.

        :param panel_id: Panel record ID.
        """
        try:
            if not panel_id:
                return self._service_error(400, _('panel_id cannot be empty.'))

            try:
                panel_id = int(panel_id)
            except (ValueError, TypeError):
                return self._service_error(400, _('panel_id must be a number.'))

            panel = self.env['sn.smt.pcb.panel'].browse(panel_id).exists()
            if not panel:
                return self._service_error(404, _('Panel record does not exist (ID: %s).') % panel_id)

            # Check whether a linked production record exists.
            if panel.production_id and panel.state == 'done':
                return self._service_error(
                    400,
                    _('Completed panel records cannot be deleted.')
                )

            panel.unlink()
            return self._service_ok(message=_('Deleted successfully.'))

        except Exception as e:
            return self._service_error(400, _('System error: %s') % str(e))

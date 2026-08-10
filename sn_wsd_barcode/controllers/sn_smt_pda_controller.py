from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request


class SnSmtPdaController(http.Controller):

    @http.route('/sn_wsd_barcode/smt/get_production_context', type='jsonrpc', auth='user')
    def get_production_context(self, workcenter_id, production_line_id=False):
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not workcenter:
            raise UserError(_('Work center not found.'))
        production = request.env['mrp.production']._get_current_online_production(
            workcenter=workcenter
        )
        if not production:
            raise UserError(_('No online manufacturing order was found for the selected work center.'))
        if production_line_id:
            line = request.env['sn.mrp.production.line'].browse(production_line_id).exists()
            if line and production.x_smt_production_line_id != line:
                raise UserError(
                    _('The selected production line does not match the current online manufacturing order.')
                )
        return {
            'production_id': production.id,
            'production_name': production.display_name,
            'product_default_code': production.product_id.default_code,
            'product_side': production.x_smt_product_side,
            'smt_material_table_id': production.x_smt_material_table_id.id,
            'smt_material_table_name': production.x_smt_material_table_id.display_name,
            'production_line_id': production.x_smt_production_line_id.id,
            'production_line_name': production.x_smt_production_line_id.display_name,
        }

    @http.route('/sn_wsd_barcode/smt/get_material_table_status', type='jsonrpc', auth='user')
    def get_material_table_status(self, production_id):
        production = request.env['mrp.production'].browse(production_id).exists()
        if not production:
            raise UserError(_('Manufacturing order not found.'))
        helper = request.env['sn.smt.tp.wizard']
        active_lines = helper._get_active_online_materials(production)
        snapshot = helper._get_completion_snapshot(production)
        rows = []
        for line in production.x_smt_online_material_ids.sorted(
            lambda item: (item.device_seq, item.table_no, item.loadpoint, item.id)
        ):
            rows.append({
                'device_seq': line.device_seq,
                'table_no': line.table_no,
                'loadpoint': line.loadpoint,
                'channel': line.chanel_sn,
                'item_code': line.item_code,
                'required_qty': line.point_qty,
                'loaded_material_lot_name': line.loaded_material_lot_id.name,
                'loaded_material_available_qty': line.loaded_material_lot_id.x_smt_available_qty,
                'loaded_product_name': line.loaded_product_id.display_name,
                'loaded_feeder_name': line.loaded_feeder_id.name,
                'load_status': line.is_load,
                'replace_count': line.replace_count,
                'is_skip': line.is_skip,
            })
        return {
            'production_id': production.id,
            'production_name': production.display_name,
            'material_table_name': production.x_smt_material_table_id.display_name,
            'summary': {
                'required_qty': snapshot['required_qty'],
                'loaded_qty': snapshot['loaded_qty'],
                'unloaded_qty': snapshot['unloaded_qty'],
                'table_complete_count': len(snapshot['table_complete_keys']),
                'machine_complete_count': len(snapshot['machine_complete_keys']),
                'line_complete': snapshot['line_complete'],
                'active_rows': len(active_lines),
            },
            'rows': rows,
        }

    @http.route('/sn_wsd_barcode/smt/do_online_load', type='jsonrpc', auth='user')
    def do_online_load(
        self,
        production_id,
        workcenter_id,
        device_table_input,
        loadpoint_input,
        material_sn_input,
        feeder_sn_input=False,
    ):
        production = request.env['mrp.production'].browse(production_id).exists()
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not production or not workcenter:
            raise UserError(_('Manufacturing order or work center not found.'))
        wizard = request.env['sn.smt.tp.wizard'].with_context(
            default_production_id=production.id,
            default_workcenter_id=workcenter.id,
        ).create({
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'device_table_input': device_table_input or '',
            'loadpoint_input': loadpoint_input or '',
            'feeder_input': feeder_sn_input or '',
            'material_sn_input': material_sn_input or '',
        })
        wizard.action_validate()
        wizard.action_save()
        return {
            'ok': True,
            'message': wizard.message or _('Online loading saved successfully.'),
            'production_id': production.id,
            'online_material_id': wizard.online_material_id.id,
            'material_lot_id': wizard.material_lot_id.id,
            'feeder_id': wizard.feeder_id.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_offline_prepare', type='jsonrpc', auth='user')
    def do_offline_prepare(
        self,
        production_id,
        workcenter_id,
        device_table_input,
        loadpoint_input,
        material_sn_input,
        cart_sn_input=False,
        feeder_sn_input=False,
    ):
        production = request.env['mrp.production'].browse(production_id).exists()
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not production or not workcenter:
            raise UserError(_('Manufacturing order or work center not found.'))
        wizard = request.env['sn.smt.bl.wizard'].with_context(
            default_production_id=production.id,
            default_workcenter_id=workcenter.id,
        ).create({
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'device_table_input': device_table_input or '',
            'loadpoint_input': loadpoint_input or '',
            'cart_input': cart_sn_input or '',
            'feeder_input': feeder_sn_input or '',
            'material_sn_input': material_sn_input or '',
        })
        wizard.action_validate()
        wizard.action_save()
        return {
            'ok': True,
            'message': wizard.message or _('Offline preparation saved successfully.'),
            'production_id': production.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_cart_load', type='jsonrpc', auth='user')
    def do_cart_load(self, production_id, workcenter_id, device_table_input, cart_sn_input):
        production = request.env['mrp.production'].browse(production_id).exists()
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not production or not workcenter:
            raise UserError(_('Manufacturing order or work center not found.'))
        wizard = request.env['sn.smt.lcsl.wizard'].with_context(
            default_production_id=production.id,
            default_workcenter_id=workcenter.id,
        ).create({
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'device_table_input': device_table_input or '',
            'cart_input': cart_sn_input or '',
        })
        wizard.action_load()
        return {
            'ok': True,
            'message': wizard.message or _('Cart loading saved successfully.'),
            'production_id': production.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_changeover', type='jsonrpc', auth='user')
    def do_changeover(self, production_id, target_production_id, workcenter_id):
        production = request.env['mrp.production'].browse(production_id).exists()
        target_production = request.env['mrp.production'].browse(target_production_id).exists()
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not production or not target_production or not workcenter:
            raise UserError(_('Manufacturing order or work center not found.'))
        wizard = request.env['sn.smt.zc.wizard'].with_context(
            default_production_id=production.id,
            default_target_production_id=target_production.id,
            default_workcenter_id=workcenter.id,
        ).create({
            'production_id': production.id,
            'target_production_id': target_production.id,
            'workcenter_id': workcenter.id,
        })
        wizard.action_changeover()
        return {
            'ok': True,
            'message': wizard.message or _('Changeover completed.'),
            'production_id': target_production.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_continue', type='jsonrpc', auth='user')
    def do_continue(
        self,
        production_id,
        workcenter_id,
        device_table_input,
        loadpoint_input,
        old_material_sn_input,
        new_material_sn_input,
        new_feeder_sn_input=False,
        change_type='continue',
    ):
        production = request.env['mrp.production'].browse(production_id).exists()
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not production or not workcenter:
            raise UserError(_('Manufacturing order or work center not found.'))
        wizard = request.env['sn.smt.change.wizard'].with_context(
            default_production_id=production.id,
            default_workcenter_id=workcenter.id,
        ).create({
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'change_type': change_type or 'continue',
            'device_table_input': device_table_input or '',
            'loadpoint_input': loadpoint_input or '',
            'material_sn_input': old_material_sn_input or '',
            'new_material_sn_input': new_material_sn_input or '',
            'feeder_input': new_feeder_sn_input or '',
        })
        if old_material_sn_input and not device_table_input:
            wizard.action_change_by_material_sn()
        else:
            wizard.action_change()
        return {
            'ok': True,
            'message': wizard.message or _('Material change or continuation completed.'),
            'production_id': production.id,
        }

    @http.route('/sn_wsd_barcode/smt/do_unload', type='jsonrpc', auth='user')
    def do_unload(
        self,
        production_id,
        workcenter_id,
        unload_scope,
        device_table_input=False,
        loadpoint_input=False,
        cart_input=False,
        material_sn_input=False,
    ):
        production = request.env['mrp.production'].browse(production_id).exists()
        workcenter = request.env['mrp.workcenter'].browse(workcenter_id).exists()
        if not production or not workcenter:
            raise UserError(_('Manufacturing order or work center not found.'))
        wizard = request.env['sn.smt.xl.wizard'].with_context(
            default_production_id=production.id,
            default_workcenter_id=workcenter.id,
        ).create({
            'production_id': production.id,
            'workcenter_id': workcenter.id,
            'unload_scope': unload_scope or 'station',
            'device_table_input': device_table_input or '',
            'loadpoint_input': loadpoint_input or '',
            'cart_input': cart_input or '',
            'material_sn_input': material_sn_input or '',
        })
        if unload_scope == 'material':
            wizard.action_unload_by_material_sn()
        else:
            wizard.action_unload()
        return {
            'ok': True,
            'message': wizard.message or _('Unload completed.'),
            'production_id': production.id,
        }

    @http.route('/sn_wsd_barcode/smt/process_smt_scan', type='jsonrpc', auth='user')
    def process_smt_scan(self, station_id, barcode, operation):
        import re

        workcenter = request.env['mrp.workcenter'].browse(station_id).exists()
        if not workcenter:
            return {'ok': False, 'message': _('Work center not found.')}

        production = request.env['mrp.production']._get_current_online_production(
            workcenter=workcenter
        )
        if not production:
            return {
                'ok': False,
                'message': _(
                    'No online manufacturing order was found for the selected workshop and production line.'
                ),
            }

        def extract(key):
            pattern = rf'(?:^|\|){re.escape(key)}=([^|]+)'
            match = re.search(pattern, barcode or '', re.IGNORECASE)
            return match.group(1).strip() if match else ''

        if operation == 'feeder_unload':
            device_table_input = extract('DEV')
            loadpoint_input = extract('LP')
            material_sn_input = extract('MAT')
            feeder_sn_input = extract('FD')
            if not device_table_input or not loadpoint_input:
                return {
                    'ok': False,
                    'message': _('Load format: DEV=N.T|LP=xxx|MAT=xxx|FD=xxx'),
                    'barcode': barcode,
                }
            if not material_sn_input:
                return {
                    'ok': False,
                    'message': _('Load barcode is missing the MAT field.'),
                    'barcode': barcode,
                }
            wizard = request.env['sn.smt.tp.wizard'].with_context(
                default_production_id=production.id,
                default_workcenter_id=workcenter.id,
            ).create({
                'production_id': production.id,
                'workcenter_id': workcenter.id,
                'device_table_input': device_table_input,
                'loadpoint_input': loadpoint_input,
                'feeder_input': feeder_sn_input,
                'material_sn_input': material_sn_input,
            })
            try:
                wizard.action_validate()
                wizard.action_save()
                return {
                    'ok': True,
                    'message': _('SMT load completed: %(device)s %(loadpoint)s %(material)s') % {
                        'device': device_table_input,
                        'loadpoint': loadpoint_input,
                        'material': material_sn_input,
                    },
                    'operation': 'online_load',
                    'production_id': production.id,
                    'production_name': production.display_name,
                }
            except UserError as error:
                return {'ok': False, 'message': str(error)}

        if operation == 'offline_prepare':
            device_table_input = extract('DEV')
            loadpoint_input = extract('LP')
            material_sn_input = extract('MAT')
            feeder_sn_input = extract('FD')
            cart_sn_input = extract('CART')
            if not device_table_input or not loadpoint_input or not material_sn_input:
                return {
                    'ok': False,
                    'message': _('Offline prepare format: DEV=N.T|LP=xxx|MAT=xxx|FD=xxx|CART=xxx'),
                    'barcode': barcode,
                }
            wizard = request.env['sn.smt.bl.wizard'].with_context(
                default_production_id=production.id,
                default_workcenter_id=workcenter.id,
            ).create({
                'production_id': production.id,
                'workcenter_id': workcenter.id,
                'device_table_input': device_table_input,
                'loadpoint_input': loadpoint_input,
                'cart_input': cart_sn_input,
                'feeder_input': feeder_sn_input,
                'material_sn_input': material_sn_input,
            })
            try:
                wizard.action_validate()
                wizard.action_save()
                return {
                    'ok': True,
                    'message': _('SMT offline preparation completed: %(device)s %(loadpoint)s %(material)s') % {
                        'device': device_table_input,
                        'loadpoint': loadpoint_input,
                        'material': material_sn_input,
                    },
                    'operation': 'offline_prepare',
                    'production_id': production.id,
                    'production_name': production.display_name,
                }
            except UserError as error:
                return {'ok': False, 'message': str(error)}

        if operation == 'cart_load':
            device_table_input = extract('DEV')
            cart_sn_input = extract('CART')
            if not device_table_input or not cart_sn_input:
                return {
                    'ok': False,
                    'message': _('Cart load format: DEV=N.T|CART=xxx'),
                    'barcode': barcode,
                }
            wizard = request.env['sn.smt.lcsl.wizard'].with_context(
                default_production_id=production.id,
                default_workcenter_id=workcenter.id,
            ).create({
                'production_id': production.id,
                'workcenter_id': workcenter.id,
                'device_table_input': device_table_input,
                'cart_input': cart_sn_input,
            })
            try:
                wizard.action_load()
                return {
                    'ok': True,
                    'message': _('SMT cart load completed: %(device)s %(cart)s') % {
                        'device': device_table_input,
                        'cart': cart_sn_input,
                    },
                    'operation': 'cart_load',
                    'production_id': production.id,
                    'production_name': production.display_name,
                }
            except UserError as error:
                return {'ok': False, 'message': str(error)}

        if operation == 'table_unload':
            material_sn_input = extract('MAT')
            if not material_sn_input:
                return {
                    'ok': False,
                    'message': _('Unload format: MAT=xxx'),
                    'barcode': barcode,
                }
            wizard = request.env['sn.smt.xl.wizard'].with_context(
                default_production_id=production.id,
                default_workcenter_id=workcenter.id,
            ).create({
                'production_id': production.id,
                'workcenter_id': workcenter.id,
                'unload_scope': 'material',
                'material_sn_input': material_sn_input,
            })
            try:
                wizard.action_unload_by_material_sn()
                return {
                    'ok': True,
                    'message': _('SMT unload completed: %(material)s') % {
                        'material': material_sn_input,
                    },
                    'operation': 'unload',
                    'production_id': production.id,
                    'production_name': production.display_name,
                }
            except UserError as error:
                return {'ok': False, 'message': str(error)}

        if operation == 'material_refill':
            old_material_sn = extract('OLD_MAT')
            new_material_sn = extract('NEW_MAT')
            if not old_material_sn or not new_material_sn:
                return {
                    'ok': False,
                    'message': _('Refill format: OLD_MAT=old material SN|NEW_MAT=new material SN'),
                    'barcode': barcode,
                }
            if old_material_sn == new_material_sn:
                return {
                    'ok': False,
                    'message': _('Old and new material SN cannot be the same.'),
                    'barcode': barcode,
                }
            wizard = request.env['sn.smt.change.wizard'].with_context(
                default_production_id=production.id,
                default_workcenter_id=workcenter.id,
            ).create({
                'production_id': production.id,
                'workcenter_id': workcenter.id,
                'change_type': 'change',
                'material_sn_input': old_material_sn,
                'new_material_sn_input': new_material_sn,
                'feeder_input': '',
                'device_table_input': '0.DUMMY',
                'loadpoint_input': 'DUMMY',
            })
            try:
                wizard.action_change_by_material_sn()
                return {
                    'ok': True,
                    'message': _('SMT refill completed: %(old)s -> %(new)s') % {
                        'old': old_material_sn,
                        'new': new_material_sn,
                    },
                    'operation': 'change',
                    'production_id': production.id,
                    'production_name': production.display_name,
                }
            except UserError as error:
                return {'ok': False, 'message': str(error)}

        return {
            'ok': False,
            'message': _('Unknown SMT operation: %(operation)s', operation=operation),
        }

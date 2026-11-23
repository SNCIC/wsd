"""Weak-link bring-in: onchange handlers filling mirror columns from
the optional business anchors. Bring-in writes INITIAL values only -
existing user input is never overwritten, and later business changes
never rewrite generated rows (snapshot semantics)."""
from odoo import api, models


def _fill_if_empty(record, values):
    for field_name, value in values.items():
        if value and not record[field_name]:
            record[field_name] = value


class NqiRdProductBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.rd.product.info'

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for record in self:
            product = record.product_id
            if product:
                _fill_if_empty(record, {
                    'product_code': product.default_code,
                    'product_type': product.default_code,
                    'product_name': product.name,
                })


class NqiRdProductDetailBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.rd.product.detail'

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for record in self:
            product = record.product_id
            if product:
                _fill_if_empty(record, {
                    'product_code': product.default_code,
                    'product_name': product.name,
                })


class NqiRdComponentListBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.rd.component.list'

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for record in self:
            product = record.product_id
            if product:
                _fill_if_empty(record, {'product_code': product.default_code})


class NqiPrPurchasePlanBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.pr.purchase.plan'

    @api.onchange('purchase_id')
    def _onchange_purchase_id(self):
        for record in self:
            purchase = record.purchase_id
            if purchase:
                _fill_if_empty(record, {'purchase_code': purchase.name})


class NqiPrArriveBatchBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.pr.arrive.batch'

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        for record in self:
            picking = record.picking_id
            if picking:
                _fill_if_empty(record, {
                    'arrived_batch_no': picking.name,
                    'purchase_code': picking.origin,
                })


class NqiPrTestResultBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.pr.test.result'

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        for record in self:
            picking = record.picking_id
            if picking:
                _fill_if_empty(record, {
                    'arrived_batch_no': picking.name,
                    'purchase_code': picking.origin,
                })


class NqiEtDeviceBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.et.device'

    @api.onchange('equipment_id')
    def _onchange_equipment_id(self):
        for record in self:
            equipment = record.equipment_id
            if equipment:
                _fill_if_empty(record, {
                    'device_code': equipment.code,
                    'device_name': equipment.name,
                })


class NqiEtPersonBringIn(models.Model):
    _inherit = 'sn.wsd.nqi.et.person'

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for record in self:
            employee = record.employee_id
            if employee:
                _fill_if_empty(record, {
                    'person_code': employee.barcode or employee.name,
                })

"""Shared test scaffolding for the MES picking online gate
(mes-picking-lifecycle R1: issue material before going online)."""


def give_pick(env, order):
    """挂一张占位领料单，满足"上线前必须领过料"的门禁。

    仅用于非领料主题的既有测试：占位单无 move、不验证；需要干净
    picking_ids 断言的用例在上线后自行取消它。作业类型优先用 MES 领料
    类型，否则退回仓库自己的内部调拨类型（绝不能按 code='internal'
    盲搜——质量控制类型同为 internal，会误中）。
    """
    warehouse = order.production_id.picking_type_id.warehouse_id
    ptype = warehouse.picking_type_issue_id or warehouse.int_type_id
    return env['stock.picking'].create({
        'picking_type_id': ptype.id,
        'location_id': ptype.default_location_src_id.id,
        'location_dest_id': ptype.default_location_dest_id.id,
        'x_mes_order_id': order.id,
    })

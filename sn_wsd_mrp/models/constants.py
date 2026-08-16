PROCESS_SECTION_SELECTION = [
    ('smt', 'SMT'),
    ('dip', 'DIP'),
    ('board_test', 'Board Test'),
    ('assembly', 'Assembly'),
    ('testing', 'Testing'),
    ('inspection', 'Inspection'),
    ('packaging', 'Packaging'),
]

STATION_TYPE_SELECTION = [
    ('assembly', 'Assembly'),
    ('programming', 'Programming'),
    ('calibration', 'Calibration'),
    ('inspection', 'Inspection'),
    ('aging', 'Aging'),
    ('final_test', 'Final Test'),
    ('packaging', 'Packaging'),
    ('repair', 'Repair'),
]

# 板面/生产面别：key 存库永不改，英文标签由 zh_CN.po 翻译。
# 工艺路线（sn.wsd.process.route.x_production_side）与制令单
# （sn.wsd.mes.order.x_side）共用同一套 key。
SIDE_SELECTION = [
    ('single', 'Single'),
    ('top', 'Top (T)'),
    ('bottom', 'Bottom (B)'),
]

SIDE_LABELS = dict(SIDE_SELECTION)

# 产品板面类型：单面只需一条 single 路线；双面需要 T/B 各一条。
BOARD_SIDE_SELECTION = [
    ('single', 'Single Side'),
    ('double', 'Double Side'),
]


def board_side_required_sides(board_side):
    """按产品板面类型返回需要维护的面别 key 集合；未声明板面返回 None。"""
    if board_side == 'single':
        return {'single'}
    if board_side == 'double':
        return {'top', 'bottom'}
    return None

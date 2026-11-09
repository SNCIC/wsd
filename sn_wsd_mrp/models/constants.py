# 板面/生产面别：key 存库永不改，英文标签由 zh_CN.po 翻译。
# 工艺路线（sn.wsd.process.route.x_production_side）与制令单
# （sn.wsd.mes.order.x_side）共用同一套 key。
import re

# 标准 SN 格式（2026-11-09 用户口径）：12 位数字、首位 1 或 2
# （如 126110003668 / 226110003668，只有首位 1/2 是硬要求，其余位不锁定）。
# 过站内核 enter_station 硬拦（终端/PDA/设备API/批量过站同源）；
# 设备通道扫铭牌先解析到整机 SN，铭牌码本身不进内核。
STANDARD_SN_RE = re.compile(r'^[12]\d{11}$')

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

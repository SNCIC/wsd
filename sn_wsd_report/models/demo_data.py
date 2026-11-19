"""占位演示数据（DEMO DATA）— 集中管理

两个看板（MES 看板大屏 / 仓库库存看板）在数据库中没有任何业务数据时
自动启用本文件中的示例数据，界面右上角会出现「演示数据」徽标。
一旦系统中存在真实业务数据（MES 工单 / 库存单据），看板自动切换回
真实数据，无需任何配置或手工切换。

彻底移除演示逻辑：
    1. 删除本文件；
    2. 删除 mes_analysis_report.py / warehouse_dashboard.py 中对
       `get_mes_demo_data` / `get_warehouse_demo_data` 的引用（各一处 if 判断）。

数据口径（两个看板保持一致）：
    - 工厂背景：电子制造（SMT + 组装 + 测试 + 老化 + 包装）
    - 在产机型：智能温控器 WSD-T100 / T100S、工控网关 WSD-G200、环境采集器 WSD-E300
    - 人员：张伟 / 李娜 / 王强（既是产线操作员，也是仓库领料经办人）
    - 仓库看板的领料物料与 MES 工单 BOM 对应（PCB / MCU / 外壳 / 彩盒 等）
"""

import datetime

_MES_OPERATORS = ['张伟', '李娜', '王强']


def _today_str():
    return datetime.date.today().strftime('%Y-%m-%d')


def _now_str():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _at(hour, minute=0):
    return datetime.datetime.now().replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ).strftime('%Y-%m-%d %H:%M')


def _hm(hour, minute=0):
    return datetime.datetime.now().replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ).strftime('%H:%M')


# =====================================================================
# MES 看板大屏 — 占位数据
# =====================================================================

def get_mes_demo_data():
    """返回与 sn.wsd.mes.dashboard.service.get_big_screen_data 相同结构的数据。"""
    production_progress = [
        {
            'production_name': 'MO-2608-0001 智能温控器T100',
            'product_qty': 500.0,
            'qty_output_total': 500.0,
            'qty_pass': 500.0,
            'qty_fail': 0.0,
            'qty_scrap': 0.0,
            'progress_rate': 100.0,
            'pass_rate': 100.0,
            'progress_status': 'normal',
        },
        {
            'production_name': 'MO-2608-0002 工控网关G200',
            'product_qty': 300.0,
            'qty_output_total': 285.0,
            'qty_pass': 282.0,
            'qty_fail': 2.0,
            'qty_scrap': 1.0,
            'progress_rate': 95.0,
            'pass_rate': 98.9,
            'progress_status': 'warning',
        },
        {
            'production_name': 'MO-2608-0003 智能温控器T100S',
            'product_qty': 200.0,
            'qty_output_total': 122.0,
            'qty_pass': 120.0,
            'qty_fail': 1.0,
            'qty_scrap': 1.0,
            'progress_rate': 61.0,
            'pass_rate': 98.4,
            'progress_status': 'warning',
        },
        {
            'production_name': 'MO-2608-0004 环境采集器E300',
            'product_qty': 400.0,
            'qty_output_total': 380.0,
            'qty_pass': 378.0,
            'qty_fail': 1.0,
            'qty_scrap': 1.0,
            'progress_rate': 95.0,
            'pass_rate': 99.5,
            'progress_status': 'warning',
        },
    ]

    station_congestion = [
        {
            'station_code': 'SMT-10 贴片', 'qty_in': 180.0, 'qty_out': 176.0,
            'qty_ng': 2.0, 'qty_scrap': 2.0, 'backlog_qty': 4.0,
            'pass_rate': 97.7, 'efficiency_rate': 97.7, 'avg_cycle_time_sec': 42.0,
            'alert_level': 'normal',
        },
        {
            'station_code': 'AOI-02 检测', 'qty_in': 176.0, 'qty_out': 174.0,
            'qty_ng': 2.0, 'qty_scrap': 0.0, 'backlog_qty': 2.0,
            'pass_rate': 98.9, 'efficiency_rate': 98.9, 'avg_cycle_time_sec': 18.0,
            'alert_level': 'normal',
        },
        {
            'station_code': 'ASSY-01 组装', 'qty_in': 174.0, 'qty_out': 168.0,
            'qty_ng': 4.0, 'qty_scrap': 2.0, 'backlog_qty': 6.0,
            'pass_rate': 96.4, 'efficiency_rate': 96.4, 'avg_cycle_time_sec': 65.0,
            'alert_level': 'warning',
        },
        {
            'station_code': 'FCT-01 测试', 'qty_in': 168.0, 'qty_out': 160.0,
            'qty_ng': 6.0, 'qty_scrap': 2.0, 'backlog_qty': 8.0,
            'pass_rate': 95.0, 'efficiency_rate': 95.0, 'avg_cycle_time_sec': 95.0,
            'alert_level': 'warning',
        },
        {
            'station_code': 'AGING-01 老化', 'qty_in': 160.0, 'qty_out': 148.0,
            'qty_ng': 8.0, 'qty_scrap': 4.0, 'backlog_qty': 12.0,
            'pass_rate': 91.9, 'efficiency_rate': 91.9, 'avg_cycle_time_sec': 0.0,
            'alert_level': 'danger',
        },
        {
            'station_code': 'PACK-01 包装', 'qty_in': 148.0, 'qty_out': 146.0,
            'qty_ng': 1.0, 'qty_scrap': 1.0, 'backlog_qty': 2.0,
            'pass_rate': 98.6, 'efficiency_rate': 98.6, 'avg_cycle_time_sec': 30.0,
            'alert_level': 'normal',
        },
    ]

    top_abnormal_stations = [
        {
            'station_code': 'AGING-01 老化', 'qty_ng': 8.0, 'qty_scrap': 4.0,
            'abnormal_qty': 12.0, 'abnormal_rate': 8.11, 'qty_out': 148.0,
        },
        {
            'station_code': 'FCT-01 测试', 'qty_ng': 6.0, 'qty_scrap': 2.0,
            'abnormal_qty': 8.0, 'abnormal_rate': 5.0, 'qty_out': 160.0,
        },
        {
            'station_code': 'ASSY-01 组装', 'qty_ng': 4.0, 'qty_scrap': 2.0,
            'abnormal_qty': 6.0, 'abnormal_rate': 3.57, 'qty_out': 168.0,
        },
        {
            'station_code': 'SMT-10 贴片', 'qty_ng': 2.0, 'qty_scrap': 2.0,
            'abnormal_qty': 4.0, 'abnormal_rate': 2.27, 'qty_out': 176.0,
        },
        {
            'station_code': 'PACK-01 包装', 'qty_ng': 1.0, 'qty_scrap': 1.0,
            'abnormal_qty': 2.0, 'abnormal_rate': 1.37, 'qty_out': 146.0,
        },
        {
            'station_code': 'AOI-02 检测', 'qty_ng': 2.0, 'qty_scrap': 0.0,
            'abnormal_qty': 2.0, 'abnormal_rate': 1.15, 'qty_out': 174.0,
        },
    ]

    operation_daily = [
        {
            'report_date': _today_str(), 'station_code': 'SMT-10 贴片',
            'operation_type': 'day', 'qty_out': 176.0, 'qty_ok': 172.0,
            'qty_ng': 2.0, 'qty_scrap': 2.0, 'pass_rate': 97.7, 'abnormal_qty': 4.0,
        },
        {
            'report_date': _today_str(), 'station_code': 'AOI-02 检测',
            'operation_type': 'day', 'qty_out': 174.0, 'qty_ok': 172.0,
            'qty_ng': 2.0, 'qty_scrap': 0.0, 'pass_rate': 98.9, 'abnormal_qty': 2.0,
        },
        {
            'report_date': _today_str(), 'station_code': 'ASSY-01 组装',
            'operation_type': 'day', 'qty_out': 168.0, 'qty_ok': 162.0,
            'qty_ng': 4.0, 'qty_scrap': 2.0, 'pass_rate': 96.4, 'abnormal_qty': 6.0,
        },
        {
            'report_date': _today_str(), 'station_code': 'FCT-01 测试',
            'operation_type': 'day', 'qty_out': 160.0, 'qty_ok': 152.0,
            'qty_ng': 6.0, 'qty_scrap': 2.0, 'pass_rate': 95.0, 'abnormal_qty': 8.0,
        },
        {
            'report_date': _today_str(), 'station_code': 'AGING-01 老化',
            'operation_type': 'day', 'qty_out': 148.0, 'qty_ok': 136.0,
            'qty_ng': 8.0, 'qty_scrap': 4.0, 'pass_rate': 91.9, 'abnormal_qty': 12.0,
        },
        {
            'report_date': _today_str(), 'station_code': 'PACK-01 包装',
            'operation_type': 'day', 'qty_out': 146.0, 'qty_ok': 144.0,
            'qty_ng': 1.0, 'qty_scrap': 1.0, 'pass_rate': 98.6, 'abnormal_qty': 2.0,
        },
        {
            'report_date': _today_str(), 'station_code': 'OQC-01 终检',
            'operation_type': 'day', 'qty_out': 140.0, 'qty_ok': 138.0,
            'qty_ng': 1.0, 'qty_scrap': 1.0, 'pass_rate': 98.6, 'abnormal_qty': 2.0,
        },
    ]

    test_history = [
        {'test_time': _hm(15, 47), 'serial_no': 'SN2608A0126', 'test_type': 'FCT',
         'result': 'pass', 'station_code': 'FCT-01', 'operator_code': '张伟', 'cycle_time_sec': 92.0, 'status': 'normal'},
        {'test_time': _hm(15, 32), 'serial_no': 'SN2608A0125', 'test_type': 'FCT',
         'result': 'pass', 'station_code': 'FCT-01', 'operator_code': '张伟', 'cycle_time_sec': 88.0, 'status': 'normal'},
        {'test_time': _hm(15, 10), 'serial_no': 'SN2608A0124', 'test_type': '老化',
         'result': 'hold', 'station_code': 'AGING-01', 'operator_code': '王强', 'cycle_time_sec': 0.0, 'status': 'warning'},
        {'test_time': _hm(14, 48), 'serial_no': 'SN2608A0123', 'test_type': 'FCT',
         'result': 'pass', 'station_code': 'FCT-01', 'operator_code': '李娜', 'cycle_time_sec': 95.0, 'status': 'normal'},
        {'test_time': _hm(14, 21), 'serial_no': 'SN2608A0122', 'test_type': 'FCT',
         'result': 'fail', 'station_code': 'FCT-01', 'operator_code': '李娜', 'cycle_time_sec': 103.0, 'status': 'danger'},
        {'test_time': _hm(13, 55), 'serial_no': 'SN2608A0121', 'test_type': 'ICT',
         'result': 'pass', 'station_code': 'SMT-10', 'operator_code': '张伟', 'cycle_time_sec': 35.0, 'status': 'normal'},
        {'test_time': _hm(13, 30), 'serial_no': 'SN2608A0120', 'test_type': 'ICT',
         'result': 'pass', 'station_code': 'SMT-10', 'operator_code': '张伟', 'cycle_time_sec': 33.0, 'status': 'normal'},
        {'test_time': _hm(12, 48), 'serial_no': 'SN2608A0119', 'test_type': '老化',
         'result': 'pass', 'station_code': 'AGING-01', 'operator_code': '王强', 'cycle_time_sec': 0.0, 'status': 'normal'},
        {'test_time': _hm(11, 52), 'serial_no': 'SN2608A0118', 'test_type': 'FCT',
         'result': 'pass', 'station_code': 'FCT-01', 'operator_code': '李娜', 'cycle_time_sec': 90.0, 'status': 'normal'},
        {'test_time': _hm(11, 20), 'serial_no': 'SN2608A0117', 'test_type': 'ICT',
         'result': 'fail', 'station_code': 'SMT-10', 'operator_code': '王强', 'cycle_time_sec': 41.0, 'status': 'danger'},
        {'test_time': _hm(10, 38), 'serial_no': 'SN2608A0116', 'test_type': 'FCT',
         'result': 'pass', 'station_code': 'FCT-01', 'operator_code': '张伟', 'cycle_time_sec': 87.0, 'status': 'normal'},
        {'test_time': _hm(8, 12), 'serial_no': 'SN2608A0115', 'test_type': 'ICT',
         'result': 'pass', 'station_code': 'SMT-10', 'operator_code': '李娜', 'cycle_time_sec': 36.0, 'status': 'normal'},
    ]

    serial_trace = [
        {'event_time': _hm(15, 55), 'serial_no': 'SN2608A0126', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'PACK-01', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0126', 'status': 'normal'},
        {'event_time': _hm(15, 40), 'serial_no': 'SN2608A0125', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'FCT-01', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0125', 'status': 'normal'},
        {'event_time': _hm(15, 12), 'serial_no': 'SN2608A0124', 'event_source': 'travel',
         'event_type': '过站', 'station_code': 'AGING-01', 'result': 'hold', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0124', 'status': 'warning'},
        {'event_time': _hm(14, 55), 'serial_no': 'SN2608A0123', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'FCT-01', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0123', 'status': 'normal'},
        {'event_time': _hm(14, 26), 'serial_no': 'SN2608A0122', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'FCT-01', 'result': 'fail', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0122', 'status': 'danger'},
        {'event_time': _hm(13, 42), 'serial_no': 'SN2608A0121', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'SMT-10', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0121', 'status': 'normal'},
        {'event_time': _hm(13, 18), 'serial_no': 'SN2608A0120', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'SMT-10', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0120', 'status': 'normal'},
        {'event_time': _hm(12, 30), 'serial_no': 'SN2608A0119', 'event_source': 'travel',
         'event_type': '过站', 'station_code': 'AGING-01', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0119', 'status': 'normal'},
        {'event_time': _hm(11, 46), 'serial_no': 'SN2608A0118', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'FCT-01', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0118', 'status': 'normal'},
        {'event_time': _hm(11, 15), 'serial_no': 'SN2608A0117', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'SMT-10', 'result': 'fail', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0117', 'status': 'danger'},
        {'event_time': _hm(10, 33), 'serial_no': 'SN2608A0116', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'FCT-01', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0116', 'status': 'normal'},
        {'event_time': _hm(8, 8), 'serial_no': 'SN2608A0115', 'event_source': 'travel',
         'event_type': '出站', 'station_code': 'SMT-10', 'result': 'pass', 'quantity': 1.0,
         'reference_name': 'TRV-2608-0115', 'status': 'normal'},
    ]

    return {
        'summary': {
            'production_count': 8,
            'open_progress_count': 5,
            'today_output_total': 126,
            'today_pass_total': 118,
            'today_test_count': 132,
            'today_date': _today_str(),
            'refresh_time': _now_str(),
            'station_alert_count': 3,
        },
        'production_progress': production_progress,
        'operation_daily': operation_daily,
        'test_pass_rates': [],
        'aging_losses': [],
        'repair_closures': [],
        'station_efficiency': [],
        'test_history': test_history,
        'serial_trace': serial_trace,
        'top_abnormal_stations': top_abnormal_stations,
        'station_congestion': station_congestion,
    }


# =====================================================================
# 仓库库存看板 — 占位数据
# =====================================================================

def get_warehouse_demo_data():
    """返回与 sn.wsd.warehouse.dashboard.service.get_warehouse_screen_data 相同结构的数据。"""
    issue_lines = [
        {'picking_name': 'WH/OUT/26080001', 'product_name': '贴片电容 0402 100nF',
         'product_code': 'CAP-0402-104', 'spec': '0402 ±10% 50V', 'qty': 50.0, 'uom': '千个',
         'user_name': '王强', 'time': _at(8, 5), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080002', 'product_name': 'MCU主控芯片 STM32F103C8T6',
         'product_code': 'IC-STM32-103', 'spec': 'LQFP48 72MHz', 'qty': 45.0, 'uom': '个',
         'user_name': '李娜', 'time': _at(8, 20), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080003', 'product_name': 'PCB主板 T100',
         'product_code': 'PCB-T100-A', 'spec': '双面 1.6mm 沉金', 'qty': 40.0, 'uom': '块',
         'user_name': '张伟', 'time': _at(8, 45), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080004', 'product_name': '铝合金外壳 T100',
         'product_code': 'CASE-T100', 'spec': '银色 喷砂氧化', 'qty': 38.0, 'uom': '个',
         'user_name': '张伟', 'time': _at(9, 10), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080005', 'product_name': '液晶模块 1.8寸',
         'product_code': 'LCD-18-TW', 'spec': 'TFT 160x128 SPI', 'qty': 30.0, 'uom': '个',
         'user_name': '王强', 'time': _at(9, 40), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080006', 'product_name': '排线 8P-15cm',
         'product_code': 'CAB-8P-15', 'spec': 'AWG28 灰排线', 'qty': 28.0, 'uom': '根',
         'user_name': '李娜', 'time': _at(10, 15), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080007', 'product_name': '蜂鸣器 有源 5V',
         'product_code': 'BUZ-5V-12', 'spec': '12mm 85dB', 'qty': 25.0, 'uom': '个',
         'user_name': '张伟', 'time': _at(11, 5), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080008', 'product_name': '螺丝包 M2x6',
         'product_code': 'SCR-M2-6K', 'spec': '不锈钢 十字沉头', 'qty': 24.0, 'uom': '包',
         'user_name': '王强', 'time': _at(13, 30), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080009', 'product_name': '电源适配器 12V2A',
         'product_code': 'PWR-12V2A', 'spec': 'DC5.5x2.1 认证款', 'qty': 22.0, 'uom': '个',
         'user_name': '李娜', 'time': _at(14, 20), 'state': 'done', 'state_label': '完成'},
        {'picking_name': 'WH/OUT/26080010', 'product_name': '包装彩盒 T100',
         'product_code': 'PKG-T100', 'spec': '350g 白卡 哑膜', 'qty': 18.0, 'uom': '个',
         'user_name': '张伟', 'time': _at(15, 10), 'state': 'done', 'state_label': '完成'},
    ]

    gain_rows = [
        {'product_code': 'SCR-M2-6K', 'product_name': '螺丝包 M2x6',
         'book_qty': 5600.0, 'real_qty': 5608.0, 'diff_qty': 8.0,
         'location_name': 'WH-B2 / 紧固件区', 'uom': '包', 'alert': False},
        {'product_code': 'CAP-0402-104', 'product_name': '贴片电容 0402 100nF',
         'book_qty': 8200.0, 'real_qty': 8205.0, 'diff_qty': 5.0,
         'location_name': 'WH-B1 / SMT料区', 'uom': '千个', 'alert': False},
        {'product_code': 'CAB-8P-15', 'product_name': '排线 8P-15cm',
         'book_qty': 1350.0, 'real_qty': 1355.0, 'diff_qty': 5.0,
         'location_name': 'WH-B2 / 线材区', 'uom': '根', 'alert': False},
        {'product_code': 'BUZ-5V-12', 'product_name': '蜂鸣器 有源 5V',
         'book_qty': 480.0, 'real_qty': 484.5, 'diff_qty': 4.5,
         'location_name': 'WH-B1 / 电子料区', 'uom': '个', 'alert': False},
        {'product_code': 'LCD-18-TW', 'product_name': '液晶模块 1.8寸',
         'book_qty': 620.0, 'real_qty': 624.0, 'diff_qty': 4.0,
         'location_name': 'WH-B1 / 电子料区', 'uom': '个', 'alert': False},
    ]

    loss_rows = [
        {'product_code': 'PCB-T100-A', 'product_name': 'PCB主板 T100',
         'book_qty': 950.0, 'real_qty': 928.0, 'diff_qty': -22.0,
         'location_name': 'WH-B1 / PCB区', 'uom': '块', 'alert': True},
        {'product_code': 'IC-STM32-103', 'product_name': 'MCU主控芯片 STM32F103C8T6',
         'book_qty': 1200.0, 'real_qty': 1185.0, 'diff_qty': -15.0,
         'location_name': 'WH-B1 / IC料区', 'uom': '个', 'alert': True},
        {'product_code': 'PKG-T100', 'product_name': '包装彩盒 T100',
         'book_qty': 2300.0, 'real_qty': 2295.0, 'diff_qty': -5.0,
         'location_name': 'WH-B3 / 包材区', 'uom': '个', 'alert': False},
        {'product_code': 'CASE-T100', 'product_name': '铝合金外壳 T100',
         'book_qty': 780.0, 'real_qty': 776.0, 'diff_qty': -4.0,
         'location_name': 'WH-B2 / 结构件区', 'uom': '个', 'alert': False},
        {'product_code': 'PWR-12V2A', 'product_name': '电源适配器 12V2A',
         'book_qty': 560.0, 'real_qty': 556.0, 'diff_qty': -4.0,
         'location_name': 'WH-B2 / 电源区', 'uom': '个', 'alert': False},
        {'product_code': 'LCD-18-TW', 'product_name': '液晶模块 1.8寸',
         'book_qty': 620.0, 'real_qty': 615.5, 'diff_qty': -4.5,
         'location_name': 'WH-B1 / 电子料区', 'uom': '个', 'alert': False},
    ]

    operation_stats = [
        {'code': 'incoming', 'label': '入库', 'active_count': 2, 'ready_count': 1, 'done_today': 5},
        {'code': 'outgoing', 'label': '出库', 'active_count': 3, 'ready_count': 2, 'done_today': 8},
        {'code': 'internal', 'label': '移库', 'active_count': 2, 'ready_count': 0, 'done_today': 3},
        {'code': 'inventory', 'label': '盘点', 'active_count': 6, 'ready_count': 0, 'done_today': 2},
    ]

    latest_operations = [
        {'name': 'WH/OUT/26080010', 'type_label': '出库', 'state': 'done',
         'state_label': '完成', 'partner_name': '苏州汇川电子', 'user_name': '张伟', 'time': _at(15, 10)},
        {'name': 'WH/INT/26080004', 'type_label': '移库', 'state': 'assigned',
         'state_label': '就绪', 'partner_name': '', 'user_name': '王强', 'time': _at(14, 55)},
        {'name': 'WH/OUT/26080009', 'type_label': '出库', 'state': 'assigned',
         'state_label': '就绪', 'partner_name': '苏州汇川电子', 'user_name': '李娜', 'time': _at(14, 20)},
        {'name': 'WH/IN/26080006', 'type_label': '入库', 'state': 'done',
         'state_label': '完成', 'partner_name': '深圳华秋电子', 'user_name': '王强', 'time': _at(13, 45)},
        {'name': 'WH/OUT/26080008', 'type_label': '出库', 'state': 'confirmed',
         'state_label': '待分配', 'partner_name': '制造 MO-2608-0003', 'user_name': '王强', 'time': _at(13, 30)},
        {'name': 'WH/IN/26080005', 'type_label': '入库', 'state': 'done',
         'state_label': '完成', 'partner_name': '东莞长安联茂电子', 'user_name': '李娜', 'time': _at(11, 50)},
        {'name': 'WH/OUT/26080007', 'type_label': '出库', 'state': 'done',
         'state_label': '完成', 'partner_name': '制造 MO-2608-0001', 'user_name': '张伟', 'time': _at(11, 5)},
        {'name': 'WH/INT/26080003', 'type_label': '移库', 'state': 'done',
         'state_label': '完成', 'partner_name': '', 'user_name': '张伟', 'time': _at(10, 30)},
    ]

    return {
        'summary': {
            'today_issue_qty': 320.0,
            'gain_total': 26.5,
            'loss_total': 54.5,
            'total_stock': 12860.0,
            'active_operation_count': 7,
            'pending_inventory_count': 6,
            'today_date': _today_str(),
            'refresh_time': _now_str(),
        },
        'issue_lines': issue_lines,
        'gain_rows': gain_rows,
        'loss_rows': loss_rows,
        'operation_stats': operation_stats,
        'latest_operations': latest_operations,
        'filter_options': {},
    }



# =====================================================================
# 中南多维度看板 — 占位数据（工单 / 班组 / 设备三维度）
# 数值口径：总产量 1286、人工工时 217h、设备机时 294h、平均 OEE 87.5%
# 三维度产量总和均等于 1286，保证跨维度数据一致
# =====================================================================

_HOURLY_TREND = {
    'labels': [f'{h:02d}:00' for h in [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]],
    'output': [6, 10, 12, 14, 18, 22, 20, 16, 12, 8, 4, 2],
    'pass_rate': [98.0, 99.0, 99.0, 98.5, 98.0, 97.7, 98.0, 97.3, 98.1, 99.0, 100.0, 100.0],
}

_DIMENSION_DEMO = {
    'workorder': {
        'dimension_label': '工单',
        'kpi': [
            {'label': '工单总数', 'value': 8, 'suffix': '', 'digits': 0, 'color': 'cyan'},
            {'label': '总产量', 'value': 1286, 'suffix': ' 件', 'digits': 0, 'color': 'cyan'},
            {'label': '总工时', 'value': 217.0, 'suffix': ' h', 'digits': 0, 'color': 'green'},
            {'label': '平均设备效率', 'value': 87.5, 'suffix': '%', 'digits': 1, 'color': 'purple'},
            {'label': '目标达成率', 'value': 88.0, 'suffix': '%', 'digits': 1, 'color': 'amber'},
            {'label': '异常工单', 'value': 1, 'suffix': '', 'digits': 0, 'color': 'red'},
        ],
        'comparison': {
            'labels': ['MO-0001', 'MO-0002', 'MO-0003', 'MO-0004', 'MO-0005', 'MO-0006'],
            'planned': [500, 300, 200, 400, 600, 450],
            'actual': [500, 285, 122, 379, 0, 0],
        },
        'detail': {
            'columns': ['工单号', '产品', '计划', '实际', '进度', '状态'],
            'rows': [
                {'cells': ['MO-2608-0001', '智能温控器T100', '500', '500', '100%', '完成'], 'level': 'ok'},
                {'cells': ['MO-2608-0002', '工控网关G200', '300', '285', '95%', '进行中'], 'level': 'normal'},
                {'cells': ['MO-2608-0003', '智能温控器T100S', '200', '122', '61%', '进行中'], 'level': 'warning'},
                {'cells': ['MO-2608-0004', '环境采集器E300', '400', '379', '95%', '进行中'], 'level': 'normal'},
                {'cells': ['MO-2608-0005', '智能温控器T100', '600', '0', '0%', '待开工'], 'level': 'idle'},
                {'cells': ['MO-2608-0006', '工控网关G200', '450', '0', '0%', '待开工'], 'level': 'idle'},
                {'cells': ['MO-2608-0007', '环境采集器E300', '280', '0', '0%', '待开工'], 'level': 'idle'},
                {'cells': ['MO-2608-0008', '智能温控器T100S', '180', '0', '0%', '待开工'], 'level': 'idle'},
            ],
        },
        'worktime_dist': {
            'labels': ['MO-0001 T100', 'MO-0002 G200', 'MO-0003 T100S', 'MO-0004 E300'],
            'values': [82.0, 48.0, 22.0, 65.0],
        },
    },
    'team': {
        'dimension_label': '班组',
        'kpi': [
            {'label': '班组数', 'value': 6, 'suffix': '', 'digits': 0, 'color': 'cyan'},
            {'label': '总产量', 'value': 1286, 'suffix': ' 件', 'digits': 0, 'color': 'cyan'},
            {'label': '总工时', 'value': 217.0, 'suffix': ' h', 'digits': 0, 'color': 'green'},
            {'label': '人均效率', 'value': 14.3, 'suffix': ' 件/h', 'digits': 1, 'color': 'green'},
            {'label': '平均设备效率', 'value': 87.5, 'suffix': '%', 'digits': 1, 'color': 'purple'},
            {'label': '目标达成率', 'value': 88.0, 'suffix': '%', 'digits': 1, 'color': 'amber'},
        ],
        'comparison': {
            'labels': ['甲班', '乙班', '丙班', '甲班(夜)', '乙班(夜)', '丙班(夜)'],
            'planned': [480, 450, 210, 90, 80, 45],
            'actual': [460, 430, 200, 80, 76, 40],
        },
        'detail': {
            'columns': ['班组', '班长', '人数', '产量', '工时', '效率'],
            'rows': [
                {'cells': ['甲班（白班）', '张伟', '12', '460', '76 h', '6.1 件/h'], 'level': 'ok'},
                {'cells': ['乙班（白班）', '李娜', '11', '430', '72 h', '6.0 件/h'], 'level': 'normal'},
                {'cells': ['丙班（白班）', '王强', '10', '200', '36 h', '5.6 件/h'], 'level': 'normal'},
                {'cells': ['甲班（夜班）', '赵磊', '6', '80', '14 h', '5.7 件/h'], 'level': 'normal'},
                {'cells': ['乙班（夜班）', '孙悦', '5', '76', '12 h', '6.3 件/h'], 'level': 'normal'},
                {'cells': ['丙班（夜班）', '周林', '4', '40', '7 h', '5.7 件/h'], 'level': 'normal'},
            ],
        },
        'worktime_dist': {
            'labels': ['甲班', '乙班', '丙班', '甲班(夜)', '乙班(夜)', '丙班(夜)'],
            'values': [76.0, 72.0, 36.0, 14.0, 12.0, 7.0],
        },
    },
    'equipment': {
        'dimension_label': '设备',
        'kpi': [
            {'label': '设备总数', 'value': 8, 'suffix': '', 'digits': 0, 'color': 'cyan'},
            {'label': '运行中', 'value': 6, 'suffix': ' 台', 'digits': 0, 'color': 'green'},
            {'label': '总产量', 'value': 1286, 'suffix': ' 件', 'digits': 0, 'color': 'cyan'},
            {'label': '平均稼动率', 'value': 87.5, 'suffix': '%', 'digits': 1, 'color': 'purple'},
            {'label': '总机时', 'value': 294, 'suffix': ' h', 'digits': 0, 'color': 'amber'},
            {'label': '故障/维修', 'value': 2, 'suffix': ' 台', 'digits': 0, 'color': 'red'},
        ],
        'comparison': {
            'labels': ['SMT-01', 'SMT-02', 'AOI-01', 'AGI-01', 'FCT-01', 'PACK-01', 'REF-01', 'DSP-01'],
            'planned': [300, 260, 180, 130, 230, 120, 100, 60],
            'actual': [280, 240, 170, 120, 220, 110, 90, 56],
        },
        'detail': {
            'columns': ['编码', '名称', '状态', '产量', '机时', 'OEE'],
            'rows': [
                {'cells': ['DEV-SMT-01', 'SMT贴片线1', '运行', '280', '72 h', '92.3%'], 'level': 'ok'},
                {'cells': ['DEV-SMT-02', 'SMT贴片线2', '运行', '240', '68 h', '88.7%'], 'level': 'ok'},
                {'cells': ['DEV-AOI-01', 'AOI光学检测', '运行', '170', '42 h', '95.1%'], 'level': 'ok'},
                {'cells': ['DEV-AGI-01', '老化房1', '维修', '120', '18 h', '62.5%'], 'level': 'danger'},
                {'cells': ['DEV-FCT-01', 'FCT功能测试', '运行', '220', '60 h', '86.4%'], 'level': 'ok'},
                {'cells': ['DEV-PACK-01', '包装线1', '待机', '110', '12 h', '78.2%'], 'level': 'idle'},
                {'cells': ['DEV-REF-01', '回流焊1', '运行', '90', '14 h', '90.5%'], 'level': 'ok'},
                {'cells': ['DEV-DSP-01', '点胶机1', '运行', '56', '8 h', '85.0%'], 'level': 'ok'},
            ],
        },
        'worktime_dist': {
            'labels': ['SMT-01', 'SMT-02', 'AOI-01', 'AGI-01', 'FCT-01', 'PACK-01', 'REF-01', 'DSP-01'],
            'values': [72.0, 68.0, 42.0, 18.0, 60.0, 12.0, 14.0, 8.0],
        },
    },
}

_LIVE_ACTIVITIES = [
    {'time': _hm(15, 47), 'type': 'quality', 'level': 'danger',
     'message': 'FCT-01 测试失败 SN2608A0122', 'ref': 'TRV-2608-0122'},
    {'time': _hm(15, 30), 'type': 'equipment', 'level': 'danger',
     'message': 'DEV-AGI-01 老化房温度异常报警', 'ref': 'EQ-ALM-2608-018'},
    {'time': _hm(15, 12), 'type': 'quality', 'level': 'warning',
     'message': 'AGING-01 SN 保持待复检 SN2608A0124', 'ref': 'TRV-2608-0124'},
    {'time': _hm(14, 20), 'type': 'plan', 'level': 'ok',
     'message': 'MO-2608-0002 工控网关G200 计划完成 95%', 'ref': 'MO-2608-0002'},
    {'time': _hm(13, 8), 'type': 'quality', 'level': 'warning',
     'message': 'FCT-01 测试节拍超限 +18s', 'ref': 'TRV-2608-0118'},
    {'time': _hm(11, 15), 'type': 'quality', 'level': 'danger',
     'message': 'SMT-10 ICT 测试失败 SN2608A0117', 'ref': 'TRV-2608-0117'},
    {'time': _hm(10, 42), 'type': 'material', 'level': 'ok',
     'message': 'MCU 芯片 STM32F103C8T6 库存预警 < 100', 'ref': 'IC-STM32-103'},
    {'time': _hm(9, 20), 'type': 'plan', 'level': 'ok',
     'message': '当日生产计划已下达 8 个工单', 'ref': 'PLAN-2608-0001'},
]


def get_ai_demo_data(dimension=None):
    """中南多维度看板占位数据。dimension: workorder / team / equipment。"""
    dim = dimension if dimension in _DIMENSION_DEMO else 'workorder'
    dim_data = _DIMENSION_DEMO[dim]
    return {
        'dimension': dim,
        'dimension_label': dim_data['dimension_label'],
        'summary': {
            'today_output': 1286,
            'oee': 87.5,
            'achieve_rate': 88.0,
            'total_hours': 217.0,
            'machine_hours': 294,
            'alerts': 6,
            'today_date': _today_str(),
            'refresh_time': _now_str(),
        },
        'kpi': dim_data['kpi'],
        'comparison': dim_data['comparison'],
        'detail': dim_data['detail'],
        'worktime_dist': dim_data['worktime_dist'],
        'hourly_trend': _HOURLY_TREND,
        'live_activities': _LIVE_ACTIVITIES,
    }

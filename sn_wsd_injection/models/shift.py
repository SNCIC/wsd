"""班次切分：白班 08:00–20:00，夜班 20:00–次日 08:00（班次日期记为夜班开始当天）。"""
from datetime import datetime, time, timedelta

import pytz

SHIFTS = [('day', '白班'), ('night', '夜班')]
DAY_START = 8
NIGHT_START = 20


def tz_of(env):
    return pytz.timezone(env.user.tz or env.context.get('tz') or 'Asia/Shanghai')


def shift_of(env, utc_dt):
    """UTC naive datetime → (班次日期, 'day'/'night')"""
    tz = tz_of(env)
    local = pytz.utc.localize(utc_dt).astimezone(tz)
    if DAY_START <= local.hour < NIGHT_START:
        return local.date(), 'day'
    if local.hour >= NIGHT_START:
        return local.date(), 'night'
    return local.date() - timedelta(days=1), 'night'


def shift_window(env, day, shift):
    """班次日期 + 班次 → (UTC 开始, UTC 结束)，均为 naive datetime。"""
    tz = tz_of(env)
    start_local = datetime.combine(day, time(DAY_START if shift == 'day' else NIGHT_START))
    start = tz.localize(start_local).astimezone(pytz.utc).replace(tzinfo=None)
    return start, start + timedelta(hours=12)

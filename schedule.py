"""Lịch hoạt động: chỉ theo dõi/tự khóa vào các ngày + khung giờ đã chọn."""
from __future__ import annotations

from datetime import datetime, timedelta

from config import Config, parse_time

DAY_NAMES = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")


def in_window(now: datetime, days, start: str, end: str) -> bool:
    """True nếu `now` nằm trong lịch.

    - days: các ngày trong tuần (0 = Thứ 2 ... 6 = Chủ nhật).
    - start == end hoặc 00:00–24:00: cả ngày.
    - end < start: qua đêm, phần sau nửa đêm tính cho ngày bắt đầu.
    """
    days = set(days)
    s = parse_time(start)
    e = parse_time(end)
    if s is None:
        s = 0
    if e is None:
        e = 24 * 60
    minute = now.hour * 60 + now.minute
    weekday = now.weekday()
    if s == e or (s == 0 and e == 24 * 60):
        return weekday in days
    if s < e:
        return weekday in days and s <= minute < e
    # Qua đêm.
    if minute >= s:
        return weekday in days
    if minute < e:
        return (now - timedelta(days=1)).weekday() in days
    return False


def is_active(cfg: Config, now: datetime | None = None) -> bool:
    if not cfg.schedule_enabled:
        return True
    return in_window(now or datetime.now(), cfg.schedule_days, cfg.schedule_start, cfg.schedule_end)


def describe(cfg: Config) -> str:
    days = ", ".join(DAY_NAMES[d] for d in sorted(cfg.schedule_days)) or "không ngày nào"
    return f"{days}, {cfg.schedule_start}–{cfg.schedule_end}"

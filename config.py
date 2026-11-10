"""Cấu hình người dùng, lưu ở <data>/config.json."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CAMERA_MODES = ("on_demand", "continuous")
IDLE_LOCK_PRESETS = (0, 5, 10, 15, 30, 60)
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


@dataclass
class Config:
    # Camera
    camera_index: int = 0
    camera_mode: str = ""             # "" = tự chọn: laptop -> on_demand, máy bàn -> continuous
    fps: float = 2.0                  # số lần kiểm tra mỗi giây khi cắm điện (chạy pin: 1)
    on_demand_idle_seconds: int = 8   # ngừng thao tác bấy nhiêu giây thì bật camera (3–120)
    periodic_check_minutes: float = 3.0  # chế độ Khi cần: kiểm tra định kỳ người lạ (0 = tắt, tối đa 60)
    continuous_check_seconds: float = 3.0  # đang thao tác: kiểm tra người lạ mỗi 3s

    # Khóa
    lock_seconds: int = 12            # vắng bấy nhiêu giây thì khóa
    warn_seconds: int = 3             # vắng bấy nhiêu giây thì icon vàng
    warn_before_lock: int = 5         # báo trước khi khóa (giây)
    idle_grace: int = 5               # thao tác trong N giây gần nhất = có mặt
    idle_lock_minutes: int = 0        # tự khóa khi không thao tác (0 = tắt)
    idle_lock_warn_seconds: int = 15

    # Nhận diện
    use_owner: bool = True
    use_person: bool = True
    owner_threshold: float = 0.40
    stranger_threshold: float = 0.25
    learn_enabled: bool = True
    learn_thumbnails: bool = False

    # Ảnh người lạ
    strangers_enabled: bool = True
    strangers_retention_days: int = 7

    # Lịch hoạt động
    schedule_enabled: bool = False
    schedule_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # 0 = Thứ 2
    schedule_start: str = "00:00"
    schedule_end: str = "24:00"

    def normalized(self) -> "Config":
        """Bản sao đã kẹp giá trị vào khoảng hợp lệ."""
        c = dataclasses.replace(self, schedule_days=list(self.schedule_days))
        c.camera_index = _clamp_int(c.camera_index, 0, 9, 0)
        if c.camera_mode not in CAMERA_MODES:
            c.camera_mode = ""
        c.fps = _clamp_float(c.fps, 0.2, 10.0, 2.0)
        c.on_demand_idle_seconds = _clamp_int(c.on_demand_idle_seconds, 3, 120, 8)
        c.periodic_check_minutes = _clamp_float(c.periodic_check_minutes, 0.0, 60.0, 3.0)
        c.continuous_check_seconds = _clamp_float(c.continuous_check_seconds, 1.0, 30.0, 3.0)
        c.lock_seconds = _clamp_int(c.lock_seconds, 5, 600, 12)
        c.warn_seconds = _clamp_int(c.warn_seconds, 1, c.lock_seconds, 3)
        c.warn_before_lock = _clamp_int(c.warn_before_lock, 0, c.lock_seconds, 5)
        c.idle_grace = _clamp_int(c.idle_grace, 0, 60, 5)
        c.idle_lock_minutes = _clamp_int(c.idle_lock_minutes, 0, 24 * 60, 0)
        c.idle_lock_warn_seconds = _clamp_int(c.idle_lock_warn_seconds, 0, 120, 15)
        c.owner_threshold = _clamp_float(c.owner_threshold, 0.2, 0.9, 0.40)
        c.stranger_threshold = _clamp_float(c.stranger_threshold, 0.0, c.owner_threshold, 0.25)
        c.strangers_retention_days = _clamp_int(c.strangers_retention_days, 1, 30, 7)
        days = []
        for d in c.schedule_days if isinstance(c.schedule_days, (list, tuple)) else []:
            try:
                d = int(d)
            except (TypeError, ValueError):
                continue
            if 0 <= d <= 6 and d not in days:
                days.append(d)
        c.schedule_days = sorted(days)
        c.schedule_start = _norm_time(c.schedule_start, "00:00")
        c.schedule_end = _norm_time(c.schedule_end, "24:00")
        for name in ("use_owner", "use_person", "learn_enabled", "learn_thumbnails",
                     "strangers_enabled", "schedule_enabled"):
            setattr(c, name, bool(getattr(c, name)))
        return c

    def effective_camera_mode(self, has_battery: bool) -> str:
        if self.camera_mode in CAMERA_MODES:
            return self.camera_mode
        return "on_demand" if has_battery else "continuous"


def _clamp_int(v, lo, hi, default):
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _clamp_float(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def parse_time(s: str) -> int | None:
    """'HH:MM' -> số phút trong ngày (0..1440). None nếu sai định dạng."""
    m = _TIME_RE.match(str(s).strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if mi >= 60 or h > 24 or (h == 24 and mi != 0):
        return None
    return h * 60 + mi


def _norm_time(s, default: str) -> str:
    minutes = parse_time(s) if s is not None else None
    if minutes is None:
        return default
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def load(path: Path) -> Config:
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        log.warning("Không đọc được %s (%s), dùng mặc định", path, e)
    known = {f.name for f in dataclasses.fields(Config)}
    cfg = Config(**{k: v for k, v in data.items() if k in known})
    return cfg.normalized()


def save(cfg: Config, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(cfg.normalized()), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

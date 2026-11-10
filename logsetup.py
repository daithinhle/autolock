"""Log xoay vòng mỗi giờ, chỉ giữ 24 giờ gần nhất. Chỉ tiến trình chính ghi file log."""
from __future__ import annotations

import logging
import logging.handlers
import os
import time
from pathlib import Path

KEEP_SECONDS = 24 * 3600
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def cleanup_old_logs(log_file: Path, keep_seconds: float = KEEP_SECONDS, now: float | None = None) -> int:
    """Xóa các file log đã xoay vòng cũ hơn keep_seconds. Trả về số file đã xóa."""
    now = time.time() if now is None else now
    removed = 0
    directory = log_file.parent
    if not directory.is_dir():
        return 0
    prefix = log_file.name + "."
    for p in directory.iterdir():
        if not p.name.startswith(prefix):
            continue
        try:
            if now - p.stat().st_mtime > keep_seconds:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


class HourlyHandler(logging.handlers.TimedRotatingFileHandler):
    def __init__(self, filename: Path):
        super().__init__(str(filename), when="H", interval=1, backupCount=0,
                         encoding="utf-8", delay=True)
        self._path = Path(filename)

    def doRollover(self):
        super().doRollover()
        cleanup_old_logs(self._path)


def setup_main(log_file: Path, level=logging.INFO, console: bool = False) -> None:
    """Cấu hình log cho tiến trình chính (ghi file)."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cleanup_old_logs(log_file)
    # File log hiện tại cũ hơn 24h (máy tắt lâu) cũng bỏ.
    try:
        if time.time() - log_file.stat().st_mtime > KEEP_SECONDS:
            os.remove(log_file)
    except OSError:
        pass
    root = logging.getLogger()
    root.setLevel(level)
    handler = HourlyHandler(log_file)
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(sh)


def setup_child(level=logging.WARNING) -> None:
    """Cửa sổ đăng ký/cài đặt: không ghi file log (tránh tranh chấp khi xoay vòng)."""
    root = logging.getLogger()
    root.setLevel(level)
    import sys
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(sh)
    else:
        root.addHandler(logging.NullHandler())

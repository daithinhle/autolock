"""Chụp ảnh người lạ: tối đa 3 ảnh mỗi lần xuất hiện, cách nhau >= 10s, giữ N ngày (tối đa 500 ảnh)."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import paths

log = logging.getLogger(__name__)

MAX_PER_EPISODE = 3
MIN_INTERVAL = 10.0
MAX_FILES = 500


class StrangerCapture:
    def __init__(self, directory: Path, enabled: bool = True, retention_days: int = 7):
        self.directory = Path(directory)
        self.enabled = enabled
        self.retention_days = retention_days
        self._episode_count = 0
        self._last_shot = 0.0
        self.new_count = 0          # ảnh mới kể từ lần thông báo gần nhất
        self._private: bool | None = None
        self._warned_not_private = False

    def configure(self, enabled: bool, retention_days: int) -> None:
        self.enabled, self.retention_days = enabled, retention_days

    def end_episode(self) -> None:
        self._episode_count = 0

    def _can_write(self) -> bool:
        if self._private is None:
            self._private = paths.is_private_local(self.directory.parent)
        if not self._private and not self._warned_not_private:
            log.warning("Thư mục dữ liệu không phải ổ cứng cục bộ riêng tư, không lưu ảnh người lạ")
            self._warned_not_private = True
        return self._private

    def maybe_capture(self, frame: np.ndarray, boxes, now: float | None = None) -> Path | None:
        now = time.time() if now is None else now
        if not self.enabled or self._episode_count >= MAX_PER_EPISODE or now - self._last_shot < MIN_INTERVAL:
            return None
        if not self._can_write():
            return None
        img = annotate(frame, boxes, datetime.fromtimestamp(now))
        self.directory.mkdir(parents=True, exist_ok=True)
        name = datetime.fromtimestamp(now).strftime("%Y%m%d_%H%M%S") + ".jpg"
        path = self.directory / name
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return None
        try:
            path.write_bytes(buf.tobytes())
        except OSError as e:
            log.warning("Không lưu được ảnh người lạ: %s", e)
            return None
        self._episode_count += 1
        self._last_shot = now
        self.new_count += 1
        log.info("Đã lưu ảnh người lạ %s", path.name)
        cleanup(self.directory, self.retention_days)
        return path

    def take_new_count(self) -> int:
        n, self.new_count = self.new_count, 0
        return n


def annotate(frame: np.ndarray, boxes, when: datetime) -> np.ndarray:
    img = frame.copy()
    for (x, y, w, h) in boxes:
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), (0, 0, 255), 2)
    text = when.strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(img, text, (8, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (8, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def list_photos(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)


def cleanup(directory: Path, retention_days: int, now: float | None = None, max_files: int = MAX_FILES) -> int:
    now = time.time() if now is None else now
    removed = 0
    photos = list_photos(directory)
    for i, p in enumerate(photos):
        try:
            if i >= max_files or now - p.stat().st_mtime > retention_days * 86400:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed

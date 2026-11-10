"""Webcam qua DirectShow. Mở/đóng theo yêu cầu; ghi nhận thời điểm sẵn sàng (frame đầu tiên đọc được)."""
from __future__ import annotations

import logging
import time

import cv2
import numpy as np

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 640, 480


class Camera:
    def __init__(self, index: int = 0):
        self.index = index
        self.cap: cv2.VideoCapture | None = None
        self.opened_at: float | None = None
        self.ready_at: float | None = None
        self.failures = 0
        self._last_open_fail = 0.0

    @property
    def is_open(self) -> bool:
        return self.cap is not None

    def open(self) -> bool:
        if self.cap is not None:
            return True
        now = time.time()
        if now - self._last_open_fail < 5.0:
            return False  # vừa lỗi, chờ một chút rồi thử lại
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.index, backend)
        if not cap.isOpened():
            cap.release()
            self._last_open_fail = now
            log.warning("Không mở được camera %d", self.index)
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        self.opened_at = time.time()
        self.ready_at = None
        self.failures = 0
        log.info("Bật camera %d", self.index)
        return True

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            log.info("Tắt camera")
        self.cap = None
        self.opened_at = None
        self.ready_at = None

    def grab(self) -> bool:
        """Lấy frame mà không giải mã (giữ bộ đệm mới, rẻ CPU)."""
        if self.cap is None:
            return False
        ok = self.cap.grab()
        self._note(ok)
        return ok

    def read(self) -> np.ndarray | None:
        if self.cap is None:
            return None
        ok, frame = self.cap.read()
        ok = ok and frame is not None and frame.size > 0
        self._note(ok)
        if not ok:
            return None
        # Frame toàn đen (camera đang khởi động / bị che bằng màn trập phần mềm) vẫn là frame hợp lệ.
        return frame

    def _note(self, ok: bool) -> None:
        if ok:
            self.failures = 0
            if self.ready_at is None:
                self.ready_at = time.time()
        else:
            self.failures += 1
            if self.failures >= 20:
                log.warning("Camera lỗi liên tục, mở lại")
                self.close()
                self._last_open_fail = time.time()


def list_cameras(max_index: int = 5) -> list[int]:
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found

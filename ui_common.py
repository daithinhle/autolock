"""Phần dùng chung cho cửa sổ đăng ký / cài đặt (tiến trình con)."""
from __future__ import annotations

import ctypes
import sys
import threading
import time

import cv2
import numpy as np

from camera import Camera

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 13, "bold")


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class CameraFeed:
    """Đọc camera ở luồng nền, giữ frame mới nhất."""

    def __init__(self, index: int):
        self.camera = Camera(index)
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.error: str | None = None
        self.started = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if not self._stop.is_set() and not self._thread.is_alive():
            self._thread.start()

    def _run(self) -> None:
        deadline = time.time() + 10
        while not self.camera.open():
            if self._stop.is_set() or time.time() > deadline:
                self.error = "Không mở được camera. Kiểm tra camera hoặc chọn camera khác trong Cài đặt."
                return
            time.sleep(0.5)
        self.started = True
        while not self._stop.is_set():
            frame = self.camera.read()
            if frame is None:
                if not self.camera.is_open:
                    self.error = "Camera bị ngắt."
                    return
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = frame

    def latest(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        self.camera.close()


def preview_width(root, wanted: int = 560) -> int:
    """Chiều rộng khung video (pixel), thu nhỏ để cả cửa sổ (~video 4:3 + ~260px chữ/nút) vừa màn hình."""
    fit = int((root.winfo_screenheight() * 0.85 - 260) * 4 / 3)
    return max(240, min(wanted, fit))


def video_label(parent, width: int):
    """Label hiển thị video, kích thước tính bằng pixel.

    Label không có ảnh thì width/height tính theo số ký tự/dòng chữ -> phải gắn ảnh trống ngay từ đầu.
    """
    import tkinter as tk
    blank = tk.PhotoImage(width=width, height=width * 3 // 4)
    label = tk.Label(parent, bg="#202020", image=blank, bd=0)
    label._blank = blank  # giữ tham chiếu, tránh bị thu gom
    return label


def to_photo(frame: np.ndarray, max_width: int = 560, mirror: bool = True):
    from PIL import Image, ImageTk
    if mirror:
        frame = cv2.flip(frame, 1)
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)))
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return ImageTk.PhotoImage(Image.fromarray(rgb))

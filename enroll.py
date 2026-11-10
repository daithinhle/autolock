"""Cửa sổ đăng ký khuôn mặt chủ máy: 6 bước x 4 mẫu = 24 vector đặc trưng. Không lưu ảnh."""
from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

import cv2
import numpy as np

import camlock
import config as config_mod
import owner as owner_mod
import paths
import vision
from ui_common import (FONT, FONT_BOLD, FONT_TITLE, CameraFeed, enable_dpi_awareness, preview_width, to_photo,
                       video_label)

SAMPLES_PER_STEP = owner_mod.ENROLL_SAMPLES // 6
SAMPLE_INTERVAL = 0.25
STEP_TIMEOUT = 5.0
YAW_TURN = 0.12
PITCH_TURN = 0.08


@dataclass
class Step:
    title: str
    kind: str   # base, left, right, up, down, front


STEPS = [
    Step("Nhìn thẳng vào camera", "base"),
    Step("Quay đầu sang trái", "left"),
    Step("Quay đầu sang phải", "right"),
    Step("Ngẩng đầu lên", "up"),
    Step("Cúi đầu xuống", "down"),
    Step("Nhìn thẳng vào camera", "front"),
]


class PoseChecker:
    """Kiểm tra tư thế so với tư thế gốc ghi ở bước đầu.

    Trái/phải không phụ thuộc camera có lật ảnh hay không: bước "phải" chỉ cần quay ngược hướng bước "trái".
    """

    def __init__(self):
        self.base: tuple[float, float] | None = None
        self.left_sign: float | None = None
        self._base_samples: list[tuple[float, float]] = []

    def add_base(self, pose) -> None:
        self._base_samples.append(pose)
        arr = np.array(self._base_samples)
        self.base = (float(arr[:, 0].mean()), float(arr[:, 1].mean()))

    def matches(self, kind: str, pose) -> bool:
        if kind == "base":
            return abs(pose[0]) < 0.35
        if self.base is None:
            return True
        dy, dp = pose[0] - self.base[0], pose[1] - self.base[1]
        if kind == "left":
            return abs(dy) >= YAW_TURN
        if kind == "right":
            if abs(dy) < YAW_TURN:
                return False
            return self.left_sign is None or np.sign(dy) != self.left_sign
        if kind == "up":
            return dp <= -PITCH_TURN
        if kind == "down":
            return dp >= PITCH_TURN
        if kind == "front":
            return abs(dy) < YAW_TURN * 0.6 and abs(dp) < PITCH_TURN * 0.75
        return True

    def note(self, kind: str, pose) -> None:
        if kind == "base":
            self.add_base(pose)
        elif kind == "left" and self.base is not None and self.left_sign is None:
            self.left_sign = float(np.sign(pose[0] - self.base[0])) or None


class EnrollWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = config_mod.load(paths.config_path())
        root.title("AutoLock - Đăng ký khuôn mặt chủ máy")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)

        tk.Label(root, text="Đăng ký khuôn mặt chủ máy", font=FONT_TITLE).pack(padx=16, pady=(12, 4))
        tk.Label(root, font=FONT, justify="center",
                 text="Ngồi ở vị trí làm việc quen thuộc, đủ sáng. App chỉ lưu đặc trưng số của khuôn mặt,\n"
                      "không lưu ảnh của bạn. Làm theo 6 bước; bước nào không nhận được tư thế sẽ tự qua sau 5s."
                 ).pack(padx=16)
        self.preview_w = preview_width(root)
        self.video = video_label(root, self.preview_w)
        self.video.pack(padx=16, pady=8)
        self.instruction = tk.Label(root, text="Đang mở camera...", font=("Segoe UI", 14, "bold"))
        self.instruction.pack(padx=16)
        self.progress = tk.Label(root, text="", font=FONT)
        self.progress.pack(padx=16, pady=(2, 6))
        buttons = tk.Frame(root)
        buttons.pack(pady=(0, 12))
        self.start_btn = tk.Button(buttons, text="Bắt đầu quét", font=FONT_BOLD, width=16,
                                   command=self.start_scan, state="disabled")
        self.start_btn.pack(side="left", padx=6)
        tk.Button(buttons, text="Hủy", font=FONT, width=10, command=self.close).pack(side="left", padx=6)

        self.engine = vision.FaceEngine()
        camlock.acquire()
        self.feed = CameraFeed(self.cfg.camera_index)
        # Chờ tiến trình chính nhả camera.
        self.root.after(800, self.feed.start)
        self.scanning = False
        self.done = False
        self.step_index = 0
        self.step_started = 0.0
        self.last_sample = 0.0
        self.samples: list[np.ndarray] = []
        self.step_samples = 0
        self.pose = PoseChecker()
        self._photo = None
        self._after = self.root.after(50, self.loop)

    def start_scan(self) -> None:
        self.scanning = True
        self.samples.clear()
        self.step_index = 0
        self.step_samples = 0
        self.pose = PoseChecker()
        self.step_started = time.time()
        self.start_btn.configure(state="disabled", text="Đang quét...")

    def loop(self) -> None:
        if self.done:
            return
        if self.feed.error:
            self.instruction.configure(text=self.feed.error, fg="#c62828")
            self.start_btn.configure(state="disabled")
            return
        frame = self.feed.latest()
        if frame is not None:
            img = vision.enhance(frame)
            faces = self.engine.detect(img)
            face = max(faces, key=lambda f: f.width) if faces else None
            if not self.scanning:
                self.start_btn.configure(state="normal")
                self.instruction.configure(
                    text="Sẵn sàng. Bấm \"Bắt đầu quét\"." if face else "Chưa thấy khuôn mặt...", fg="black")
            else:
                self.process(img, face)
            shown = img.copy()
            if face is not None:
                x, y, w, h = [int(v) for v in face.box]
                color = (0, 200, 0) if len(faces) == 1 else (0, 160, 255)
                cv2.rectangle(shown, (x, y), (x + w, y + h), color, 2)
            self._photo = to_photo(shown, max_width=self.preview_w)
            self.video.configure(image=self._photo)
        self._after = self.root.after(60, self.loop)

    def process(self, img, face) -> None:
        now = time.time()
        step = STEPS[self.step_index]
        elapsed = now - self.step_started
        remaining = max(0.0, STEP_TIMEOUT - elapsed)
        self.instruction.configure(text=f"Bước {self.step_index + 1}/6: {step.title}", fg="#1565c0")
        self.progress.configure(
            text=f"Mẫu {self.step_samples}/{SAMPLES_PER_STEP} · tổng {len(self.samples)}/{owner_mod.ENROLL_SAMPLES}"
                 + ("" if face is not None else " · không thấy khuôn mặt")
                 + (f" · tự qua sau {remaining:.0f}s" if step.kind != "base" else ""))
        if face is None or now - self.last_sample < SAMPLE_INTERVAL:
            return
        pose = vision.head_pose(face.landmarks)
        timed_out = elapsed >= STEP_TIMEOUT and step.kind != "base"
        if not (self.pose.matches(step.kind, pose) or timed_out):
            return
        feat = self.engine.describe(img, face)
        self.pose.note(step.kind, pose)
        self.samples.append(feat)
        self.step_samples += 1
        self.last_sample = now
        if self.step_samples >= SAMPLES_PER_STEP:
            self.step_index += 1
            self.step_samples = 0
            self.step_started = now
            if self.step_index >= len(STEPS):
                self.finish()

    def finish(self) -> None:
        self.scanning = False
        self.done = True
        lib = owner_mod.OwnerLibrary(np.array(self.samples))
        try:
            lib.save(paths.owner_path())  # đăng ký lại = xóa mẫu tự học
            owner_mod.delete_thumbnails(paths.learned_dir())
        except OSError as e:
            messagebox.showerror("AutoLock", f"Không lưu được: {e}")
            self.close()
            return
        self.instruction.configure(text="Hoàn tất! AutoLock đã nhận diện được bạn.", fg="#2e7d32")
        self.progress.configure(text=f"Đã lưu {len(self.samples)} vector đặc trưng.")
        self.feed.stop()
        camlock.release()
        self.root.after(1800, self.close)

    def close(self) -> None:
        self.done = True
        try:
            self.root.after_cancel(self._after)
        except (tk.TclError, AttributeError):
            pass
        try:
            self.feed.stop()
        finally:
            camlock.release()
            self.root.destroy()


def run() -> int:
    enable_dpi_awareness()
    vision.configure_cv()
    root = tk.Tk()
    EnrollWindow(root)
    root.mainloop()
    return 0

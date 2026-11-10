"""Cửa sổ Cài đặt (tiến trình con). Lưu config.json; tiến trình chính tự nạp lại."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import numpy as np

import camlock
import config as config_mod
import owner as owner_mod
import paths
import strangers
import vision
import winapi
from schedule import DAY_NAMES
from ui_common import FONT, FONT_BOLD, CameraFeed, enable_dpi_awareness, preview_width, to_photo, video_label

MODE_LABELS = {"": "Tự chọn theo loại máy", "on_demand": "Khi cần", "continuous": "Liên tục"}
WRAP = 520  # px: chữ dài tự xuống dòng để cửa sổ không quá rộng
RESCAN_SECONDS = 6.0


def _spawn_self(flag: str) -> None:
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, flag]
    else:
        exe = sys.executable
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        cmd = [pyw if os.path.exists(pyw) else exe,
               os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"), flag]
    subprocess.Popen(cmd, close_fds=True)


class SettingsWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = config_mod.load(paths.config_path())
        root.title("AutoLock - Cài đặt")
        root.resizable(False, False)
        style = ttk.Style(root)
        style.configure(".", font=FONT)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_general(nb)
        self._build_schedule(nb)
        self._build_owner(nb)
        self._build_strangers(nb)

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(bar, text=f"Dữ liệu: {paths.data_dir()}", foreground="#666", wraplength=WRAP - 140
                  ).pack(side="left")
        ttk.Button(bar, text="Đóng", command=root.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Lưu", command=self.save).pack(side="right")

    # ---------- các tab ----------
    def _row(self, parent, r, label, widget):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", padx=8, pady=4)
        widget.grid(row=r, column=1, sticky="w", padx=8, pady=4)

    def _build_general(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="Chung")
        c = self.cfg
        self.v_camera = tk.IntVar(value=c.camera_index)
        self.v_mode = tk.StringVar(value=MODE_LABELS[c.camera_mode])
        self.v_lock = tk.IntVar(value=c.lock_seconds)
        self.v_ondemand = tk.IntVar(value=c.on_demand_idle_seconds)
        self.v_periodic = tk.DoubleVar(value=c.periodic_check_minutes)
        self.v_idle_lock = tk.IntVar(value=c.idle_lock_minutes)
        self.v_person = tk.BooleanVar(value=c.use_person)
        self.v_autostart = tk.BooleanVar(value=winapi.autostart_enabled())
        r = 0
        self._row(f, r, "Camera số", ttk.Spinbox(f, from_=0, to=9, width=6, textvariable=self.v_camera)); r += 1
        self._row(f, r, "Chế độ camera", ttk.Combobox(f, values=list(MODE_LABELS.values()), state="readonly",
                                                      width=22, textvariable=self.v_mode)); r += 1
        self._row(f, r, "Khóa khi vắng (giây)", ttk.Spinbox(f, from_=5, to=600, width=6, textvariable=self.v_lock)); r += 1
        self._row(f, r, "Bật camera sau khi ngừng thao tác (giây)",
                  ttk.Spinbox(f, from_=3, to=120, width=6, textvariable=self.v_ondemand)); r += 1
        self._row(f, r, "Kiểm tra người lạ định kỳ (phút, 0 = tắt)",
                  ttk.Spinbox(f, from_=0, to=60, increment=0.5, width=6, textvariable=self.v_periodic)); r += 1
        self._row(f, r, "Tự khóa khi không thao tác (phút, 0 = tắt)",
                  ttk.Spinbox(f, from_=0, to=1440, width=6, textvariable=self.v_idle_lock)); r += 1
        ttk.Checkbutton(f, text="Phát hiện người khi không thấy mặt (YOLOX)", variable=self.v_person
                        ).grid(row=r, column=0, columnspan=2, sticky="w", padx=8, pady=4); r += 1
        ttk.Checkbutton(f, text="Chạy cùng Windows", variable=self.v_autostart
                        ).grid(row=r, column=0, columnspan=2, sticky="w", padx=8, pady=4)

    def _build_schedule(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="Lịch hoạt động")
        c = self.cfg
        self.v_sched = tk.BooleanVar(value=c.schedule_enabled)
        ttk.Checkbutton(f, text="Chỉ theo dõi và tự khóa theo lịch", variable=self.v_sched
                        ).grid(row=0, column=0, columnspan=7, sticky="w", padx=8, pady=4)
        self.v_days = []
        for i, name in enumerate(DAY_NAMES):
            v = tk.BooleanVar(value=i in c.schedule_days)
            self.v_days.append(v)
            ttk.Checkbutton(f, text=name, variable=v).grid(row=1, column=i, padx=4, pady=4)
        self.v_start = tk.StringVar(value=c.schedule_start)
        self.v_end = tk.StringVar(value=c.schedule_end)
        times = ttk.Frame(f)
        times.grid(row=2, column=0, columnspan=7, sticky="w", padx=8, pady=8)
        ttk.Label(times, text="Từ").pack(side="left")
        ttk.Entry(times, width=7, textvariable=self.v_start).pack(side="left", padx=4)
        ttk.Label(times, text="đến").pack(side="left")
        ttk.Entry(times, width=7, textvariable=self.v_end).pack(side="left", padx=4)
        ttk.Label(f, foreground="#555", justify="left", wraplength=WRAP,
                  text="00:00–24:00 = cả ngày. Giờ kết thúc nhỏ hơn giờ bắt đầu = qua đêm (tính cho ngày bắt đầu). "
                       "Ngoài lịch: camera tắt, không tự khóa, icon xám.").grid(
            row=3, column=0, columnspan=7, sticky="w", padx=8)

    def _build_owner(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="Khuôn mặt chủ máy")
        c = self.cfg
        self.v_learn = tk.BooleanVar(value=c.learn_enabled)
        self.v_thumbs = tk.BooleanVar(value=c.learn_thumbnails)
        self.owner_info = ttk.Label(f, text="")
        self.owner_info.grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(f, text="Tự học góc mặt mới (quay đầu, cúi, đổi ánh sáng)", variable=self.v_learn
                        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Checkbutton(f, text="Lưu ảnh mặt thu nhỏ của mẫu tự học (để xem bằng mắt)",
                        variable=self.v_thumbs).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=4)
        ttk.Button(f, text="Kiểm tra mẫu...", command=self.review_samples).grid(row=3, column=0, padx=8, pady=8, sticky="w")
        ttk.Button(f, text="Xóa mẫu tự học", command=self.clear_learned).grid(row=3, column=1, padx=8, pady=8, sticky="w")
        ttk.Button(f, text="Đăng ký lại khuôn mặt", command=lambda: _spawn_self("--enroll")
                   ).grid(row=3, column=2, padx=8, pady=8, sticky="w")
        self._update_owner_info()

    def _build_strangers(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="Ảnh người lạ")
        c = self.cfg
        self.v_strangers = tk.BooleanVar(value=c.strangers_enabled)
        self.v_retention = tk.IntVar(value=c.strangers_retention_days)
        ttk.Checkbutton(f, text="Chụp ảnh khi chỉ thấy người lạ (tối đa 3 ảnh mỗi lần)", variable=self.v_strangers
                        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self._row(f, 1, "Giữ ảnh (ngày, 1–30)", ttk.Spinbox(f, from_=1, to=30, width=6, textvariable=self.v_retention))
        n = len(strangers.list_photos(paths.strangers_dir()))
        ttk.Label(f, text=f"Hiện có {n} ảnh (tối đa {strangers.MAX_FILES}).").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Button(f, text="Mở thư mục ảnh", command=self.open_strangers).grid(row=3, column=0, sticky="w", padx=8, pady=8)

    # ---------- hành động ----------
    def _load_library(self):
        return owner_mod.OwnerLibrary.load(paths.owner_path())

    def _update_owner_info(self):
        lib = self._load_library()
        if lib is None:
            self.owner_info.configure(text="Chưa đăng ký khuôn mặt.")
        else:
            self.owner_info.configure(text=f"{len(lib.enrolled)} mẫu đăng ký + {len(lib.learned)} mẫu tự học "
                                           f"(tối đa {owner_mod.LEARN_MAX}).")

    def clear_learned(self):
        lib = self._load_library()
        if lib is None or not len(lib.learned):
            messagebox.showinfo("AutoLock", "Không có mẫu tự học.", parent=self.root)
            return
        if not messagebox.askyesno("AutoLock", f"Xóa {len(lib.learned)} mẫu tự học?", parent=self.root):
            return
        lib.clear_learned()
        lib.save()
        owner_mod.delete_thumbnails(paths.learned_dir())
        self._update_owner_info()

    def review_samples(self):
        lib = self._load_library()
        if lib is None:
            messagebox.showinfo("AutoLock", "Chưa đăng ký khuôn mặt.", parent=self.root)
            return
        ReviewDialog(self.root, self.cfg, on_change=self._update_owner_info)

    def open_strangers(self):
        d = paths.strangers_dir()
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    def save(self):
        try:
            start, end = self.v_start.get().strip(), self.v_end.get().strip()
            if config_mod.parse_time(start) is None or config_mod.parse_time(end) is None:
                raise ValueError("Giờ phải có dạng HH:MM (00:00–24:00).")
            mode = next(k for k, v in MODE_LABELS.items() if v == self.v_mode.get())
            c = config_mod.load(paths.config_path())  # giữ các khóa không có trên giao diện
            c.camera_index = int(self.v_camera.get())
            c.camera_mode = mode
            c.lock_seconds = int(self.v_lock.get())
            c.on_demand_idle_seconds = int(self.v_ondemand.get())
            c.periodic_check_minutes = float(self.v_periodic.get())
            c.idle_lock_minutes = int(self.v_idle_lock.get())
            c.use_person = bool(self.v_person.get())
            c.schedule_enabled = bool(self.v_sched.get())
            c.schedule_days = [i for i, v in enumerate(self.v_days) if v.get()]
            c.schedule_start, c.schedule_end = start, end
            c.learn_enabled = bool(self.v_learn.get())
            c.learn_thumbnails = bool(self.v_thumbs.get())
            c.strangers_enabled = bool(self.v_strangers.get())
            c.strangers_retention_days = int(self.v_retention.get())
        except (tk.TclError, ValueError, StopIteration) as e:
            messagebox.showerror("AutoLock", f"Giá trị không hợp lệ: {e}", parent=self.root)
            return
        if c.schedule_enabled and not c.schedule_days:
            messagebox.showerror("AutoLock", "Chọn ít nhất một ngày cho lịch hoạt động.", parent=self.root)
            return
        config_mod.save(c, paths.config_path())
        if not c.learn_thumbnails:
            owner_mod.delete_thumbnails(paths.learned_dir())
        if self.v_autostart.get() != winapi.autostart_enabled():
            winapi.set_autostart(bool(self.v_autostart.get()))
        self.cfg = c.normalized()
        messagebox.showinfo("AutoLock", "Đã lưu cài đặt.", parent=self.root)


def score_color(score: float) -> str:
    if score >= 0.45:
        return "#2e7d32"
    if score >= owner_mod.ANCHOR_MIN + 0.05:
        return "#b28704"
    return "#c62828"


class ReviewDialog:
    """Xem từng mẫu tự học kèm % giống bộ gốc; tích để xóa; quét lại & tự lọc."""

    THUMB = 56

    def __init__(self, parent, cfg, on_change=None):
        self.cfg = cfg
        self.on_change = on_change
        self.top = tk.Toplevel(parent)
        self.top.title("Kiểm tra mẫu tự học")
        self.top.geometry("520x560")
        self.top.transient(parent)
        self.summary = ttk.Label(self.top, text="")
        self.summary.pack(fill="x", padx=10, pady=(10, 4))
        outer = ttk.Frame(self.top)
        outer.pack(fill="both", expand=True, padx=10)
        canvas = tk.Canvas(outer, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        bar = ttk.Frame(self.top)
        bar.pack(fill="x", padx=10, pady=10)
        ttk.Button(bar, text="Xóa mẫu đã chọn", command=self.delete_selected).pack(side="left")
        ttk.Button(bar, text="Quét lại & tự lọc", command=self.rescan).pack(side="left", padx=6)
        ttk.Button(bar, text="Đóng", command=self.top.destroy).pack(side="right")
        self._photos = []
        self.populate()

    def populate(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self._photos.clear()
        self.lib = owner_mod.OwnerLibrary.load(paths.owner_path())
        self.checks: dict[str, tk.BooleanVar] = {}
        if self.lib is None:
            self.summary.configure(text="Chưa đăng ký khuôn mặt.")
            return
        scores = self.lib.learned_base_scores()
        self.summary.configure(text=f"{len(self.lib.learned)} mẫu tự học. % = độ giống với bộ đăng ký gốc "
                                    f"(xanh ≥ 45%, vàng ≥ {int((owner_mod.ANCHOR_MIN + 0.05) * 100)}%, đỏ thấp hơn).")
        from PIL import Image, ImageTk
        order = np.argsort(scores)  # mẫu đáng ngờ nhất lên đầu
        for row, i in enumerate(order):
            sid = self.lib.learned_ids[i]
            score = float(scores[i])
            thumb = owner_mod.thumbnail_path(paths.learned_dir(), sid)
            img = vision.imread(thumb) if thumb.exists() else None
            if img is not None:
                import cv2
                rgb = cv2.cvtColor(cv2.resize(img, (self.THUMB, self.THUMB)), cv2.COLOR_BGR2RGB)
                photo = ImageTk.PhotoImage(Image.fromarray(rgb))
                self._photos.append(photo)
                tk.Label(self.inner, image=photo).grid(row=row, column=0, padx=4, pady=2)
            else:
                tk.Label(self.inner, text="(không ảnh)", width=10, fg="#888").grid(row=row, column=0, padx=4, pady=2)
            when = datetime.fromtimestamp(float(self.lib.learned_ts[i])).strftime("%d/%m %H:%M")
            tk.Label(self.inner, text=f"Mẫu {when}", font=FONT).grid(row=row, column=1, sticky="w", padx=4)
            tk.Label(self.inner, text=f"{score * 100:.0f}%", font=FONT_BOLD, fg=score_color(score)
                     ).grid(row=row, column=2, padx=8)
            v = tk.BooleanVar(value=False)
            self.checks[sid] = v
            ttk.Checkbutton(self.inner, text="xóa", variable=v).grid(row=row, column=3, padx=4)

    def _remove(self, ids) -> int:
        lib = owner_mod.OwnerLibrary.load(paths.owner_path())
        if lib is None:
            return 0
        n = lib.remove_learned(ids)
        if n:
            lib.save()
            owner_mod.delete_thumbnails(paths.learned_dir(), ids)
        return n

    def delete_selected(self):
        ids = [sid for sid, v in self.checks.items() if v.get()]
        if not ids:
            return
        n = self._remove(ids)
        self.populate()
        if self.on_change:
            self.on_change()
        messagebox.showinfo("AutoLock", f"Đã xóa {n} mẫu.", parent=self.top)

    def rescan(self):
        if self.lib is None:
            return
        RescanDialog(self.top, self.cfg, self.lib, on_done=self._after_rescan)

    def _after_rescan(self, fresh: list):
        if len(fresh) < 3:
            messagebox.showwarning("AutoLock", "Không nhận ra bạn đủ rõ. Ngồi trước camera, đủ sáng rồi thử lại.",
                                   parent=self.top)
            return
        lib = owner_mod.OwnerLibrary.load(paths.owner_path())
        if lib is None or not len(lib.learned):
            messagebox.showinfo("AutoLock", "Không có mẫu tự học để lọc.", parent=self.top)
            return
        bad = filter_learned(lib, np.array(fresh))
        n = self._remove(bad) if bad else 0
        self.populate()
        if self.on_change:
            self.on_change()
        messagebox.showinfo("AutoLock", f"Đã loại {n} mẫu không còn khớp bạn.", parent=self.top)


def filter_learned(lib: owner_mod.OwnerLibrary, fresh: np.ndarray, min_sim: float = owner_mod.ANCHOR_MIN) -> list[str]:
    """Id các mẫu tự học không còn khớp khuôn mặt vừa quét."""
    if not len(lib.learned) or not len(fresh):
        return []
    best = np.max(lib.learned @ fresh.T, axis=1)
    return [sid for sid, s in zip(lib.learned_ids, best) if s < min_sim]


class RescanDialog:
    def __init__(self, parent, cfg, lib, on_done):
        self.cfg, self.lib, self.on_done = cfg, lib, on_done
        self.top = tk.Toplevel(parent)
        self.top.title("Quét lại")
        self.top.transient(parent)
        self.top.grab_set()
        self.label = ttk.Label(self.top, text="Đang mở camera... Ngồi trước camera như bình thường.")
        self.label.pack(padx=10, pady=8)
        self.preview_w = preview_width(self.top, 400)
        self.video = video_label(self.top, self.preview_w)
        self.video.pack(padx=10, pady=(0, 10))
        self.engine = vision.FaceEngine()
        camlock.acquire()
        self.feed = CameraFeed(cfg.camera_index)
        self.top.after(800, self.feed.start)
        self.fresh: list = []
        self.started_at: float | None = None
        self.top.protocol("WM_DELETE_WINDOW", self.finish)
        self._photo = None
        self.top.after(100, self.loop)

    def loop(self):
        if self.feed.error:
            self.label.configure(text=self.feed.error)
            self.top.after(2000, self.finish)
            return
        frame = self.feed.latest()
        if frame is not None:
            if self.started_at is None:
                self.started_at = time.time()
            img = vision.enhance(frame)
            faces = self.engine.detect(img)
            if len(faces) == 1:
                feat = self.engine.describe(img, faces[0])
                # So với bộ gốc (không dùng mẫu tự học, vì chính chúng đang được kiểm tra).
                if self.lib.base_similarity(feat) >= self.cfg.owner_threshold:
                    self.fresh.append(feat)
            left = RESCAN_SECONDS - (time.time() - self.started_at)
            self.label.configure(text=f"Đang quét... {max(0, left):.0f}s · {len(self.fresh)} mẫu nhận ra bạn")
            self._photo = to_photo(img, max_width=self.preview_w)
            self.video.configure(image=self._photo)
            if left <= 0:
                self.finish()
                return
        self.top.after(150, self.loop)

    def finish(self):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        self.feed.stop()
        camlock.release()
        fresh = list(self.fresh)
        self.top.destroy()
        self.on_done(fresh)


def run() -> int:
    enable_dpi_awareness()
    vision.configure_cv()
    root = tk.Tk()
    SettingsWindow(root)
    root.mainloop()
    return 0

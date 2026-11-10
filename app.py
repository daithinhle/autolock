"""Tiến trình chính: vòng lặp theo dõi + tray."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time

import camlock
import config as config_mod
import logsetup
import owner as owner_mod
import paths
import schedule
import strangers
import vision
import winapi
from analyzer import Analyzer
from camera import Camera
from presence import (CameraPolicy, IdleLock, PresenceMonitor, Status, StrangerConfirmer, Verdict)

log = logging.getLogger(__name__)

RELOAD_INTERVAL = 2.0
HOUSEKEEPING_INTERVAL = 3600.0
CONSENT_INTERVAL = 5.0


class App:
    def __init__(self, overrides: dict | None = None, dry_run: bool = False, use_tray: bool = True):
        self.overrides = overrides or {}
        self.dry_run = dry_run
        self.use_tray = use_tray
        self.cfg_path = paths.config_path()
        self.owner_path = paths.owner_path()
        self.cfg = self._load_config()
        self._cfg_mtime = _mtime(self.cfg_path)
        self.has_battery = winapi.has_battery()

        now = time.time()
        self.quit_event = threading.Event()
        self.paused_until = 0.0
        self.children: list[subprocess.Popen] = []

        self.engine = vision.FaceEngine()
        self.library = owner_mod.OwnerLibrary.load(self.owner_path)
        self._owner_mtime = _mtime(self.owner_path)
        self.analyzer = Analyzer(self.cfg, self.engine, self.library,
                                 person_detector_factory=vision.PersonDetector)
        self.camera = Camera(self.cfg.camera_index)
        self.monitor = PresenceMonitor(self.cfg.lock_seconds, self.cfg.warn_seconds, self.cfg.warn_before_lock, now)
        self.idle_lock = IdleLock(self.cfg.idle_lock_minutes, self.cfg.idle_lock_warn_seconds)
        self.policy = CameraPolicy(self.camera_mode, self.cfg.on_demand_idle_seconds,
                                   self.cfg.periodic_check_minutes, now)
        self.confirmer = StrangerConfirmer()
        self.capture = strangers.StrangerCapture(paths.strangers_dir(), self.cfg.strangers_enabled,
                                                 self.cfg.strangers_retention_days)
        self.tray = None
        self.state = "paused"
        self.status_detail = "Đang khởi động"
        self._was_locked = False
        self._last_analysis = 0.0
        self._last_reload = 0.0
        self._last_housekeeping = 0.0
        self._last_consent = 0.0
        self._camera_busy = False
        self._lock_requested_at = 0.0
        self._last_verdict: Verdict | None = None

    # ---------- cấu hình ----------
    def _load_config(self) -> config_mod.Config:
        cfg = config_mod.load(self.cfg_path)
        for k, v in self.overrides.items():
            setattr(cfg, k, v)
        return cfg.normalized()

    @property
    def camera_mode(self) -> str:
        return self.cfg.effective_camera_mode(self.has_battery)

    def _apply_config(self, now: float) -> None:
        c = self.cfg
        self.analyzer.cfg = c
        self.monitor.configure(c.lock_seconds, c.warn_seconds, c.warn_before_lock)
        self.idle_lock.minutes, self.idle_lock.warn_seconds = c.idle_lock_minutes, c.idle_lock_warn_seconds
        self.policy.configure(self.camera_mode, c.on_demand_idle_seconds, c.periodic_check_minutes, now)
        self.capture.configure(c.strangers_enabled, c.strangers_retention_days)
        if c.camera_index != self.camera.index:
            self.camera.close()
            self.camera = Camera(c.camera_index)

    def _save_config_change(self, **changes) -> None:
        base = config_mod.load(self.cfg_path)
        for k, v in changes.items():
            setattr(base, k, v)
        config_mod.save(base, self.cfg_path)
        self._cfg_mtime = _mtime(self.cfg_path)
        for k, v in changes.items():
            self.overrides.pop(k, None)
        self.cfg = self._load_config()
        self._apply_config(time.time())
        self._refresh_tray()

    def _reload_if_changed(self, now: float) -> None:
        if now - self._last_reload < RELOAD_INTERVAL:
            return
        self._last_reload = now
        m = _mtime(self.cfg_path)
        if m != self._cfg_mtime:
            self._cfg_mtime = m
            self.cfg = self._load_config()
            self._apply_config(now)
            log.info("Đã nạp lại cấu hình")
            self._refresh_tray()
        m = _mtime(self.owner_path)
        if m != self._owner_mtime and (self.library is None or m != self.library.mtime):
            self._owner_mtime = m
            self.library = owner_mod.OwnerLibrary.load(self.owner_path)
            self.analyzer.set_library(self.library)
            log.info("Đã nạp lại khuôn mặt chủ máy (%s)",
                     "chưa đăng ký" if self.library is None
                     else f"{len(self.library.enrolled)} + {len(self.library.learned)} mẫu")
        elif self.library is not None and self.library.mtime:
            self._owner_mtime = self.library.mtime

    # ---------- menu tray ----------
    def status_text(self) -> str:
        return f"AutoLock: {self.status_detail}" + (" [dry-run]" if self.dry_run else "")

    def schedule_text(self) -> str:
        return schedule.describe(self.cfg)

    def is_paused(self) -> bool:
        return time.time() < self.paused_until

    def pause(self, minutes: int) -> None:
        self.paused_until = time.time() + minutes * 60
        log.info("Tạm dừng %d phút", minutes)
        self._refresh_tray()

    def resume(self) -> None:
        self.paused_until = 0.0
        self.monitor.reset(time.time())
        log.info("Tiếp tục")
        self._refresh_tray()

    def set_camera_mode(self, mode: str) -> None:
        self._save_config_change(camera_mode=mode)
        log.info("Chế độ camera: %s", mode)

    def set_idle_lock(self, minutes: int) -> None:
        self._save_config_change(idle_lock_minutes=minutes)
        log.info("Tự khóa khi không thao tác: %s", f"{minutes} phút" if minutes else "tắt")

    def toggle_schedule(self) -> None:
        self._save_config_change(schedule_enabled=not self.cfg.schedule_enabled)

    def stranger_photo_count(self) -> int:
        return len(strangers.list_photos(paths.strangers_dir()))

    def open_strangers(self) -> None:
        d = paths.strangers_dir()
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(d))
        except OSError as e:
            log.warning("Không mở được thư mục ảnh: %s", e)

    def autostart_enabled(self) -> bool:
        return winapi.autostart_enabled()

    def toggle_autostart(self) -> None:
        if self.dry_run:
            log.info("--dry-run: không thay đổi tự khởi động")
            return
        winapi.set_autostart(not winapi.autostart_enabled())
        self._refresh_tray()

    def _spawn(self, flag: str) -> None:
        self.children = [p for p in self.children if p.poll() is None]
        if any(getattr(p, "_autolock_flag", None) == flag for p in self.children):
            return
        cmd = _child_command(flag)
        try:
            p = subprocess.Popen(cmd, close_fds=True)
            p._autolock_flag = flag
            self.children.append(p)
        except OSError as e:
            log.error("Không mở được cửa sổ %s: %s", flag, e)

    def open_enroll(self) -> None:
        self._spawn("--enroll")

    def open_settings(self) -> None:
        self._spawn("--settings")

    def quit(self) -> None:
        log.info("Thoát")
        self.quit_event.set()

    def _refresh_tray(self) -> None:
        if self.tray:
            self.tray.refresh()

    def _notify(self, msg: str) -> None:
        log.info("Thông báo: %s", msg)
        if self.tray:
            self.tray.notify(msg)

    def _set_state(self, state: str, detail: str) -> None:
        changed = detail != self.status_detail
        self.state, self.status_detail = state, detail
        if self.tray:
            self.tray.set_state(state, self.status_text())
            if changed:
                self.tray.refresh()

    # ---------- vòng lặp ----------
    def run(self) -> None:
        log.info("AutoLock khởi động (dữ liệu: %s, chế độ camera: %s%s)", paths.data_dir(), self.camera_mode,
                 ", DRY-RUN" if self.dry_run else "")
        if self.use_tray:
            from tray import Tray
            self.tray = Tray(self)
            self.tray.start()
        if self.library is None and self.cfg.use_owner:
            log.info("Chưa đăng ký khuôn mặt chủ máy, mở cửa sổ đăng ký")
            self.open_enroll()
        try:
            while not self.quit_event.is_set():
                try:
                    delay = self.tick(time.time())
                except Exception:
                    log.exception("Lỗi trong vòng lặp")
                    self.camera.close()
                    delay = 2.0
                self.quit_event.wait(delay)
        finally:
            self.camera.close()
            if self.tray:
                self.tray.stop()
            log.info("Đã dừng")

    def _housekeeping(self, now: float) -> None:
        if now - self._last_housekeeping < HOUSEKEEPING_INTERVAL:
            return
        self._last_housekeeping = now
        logsetup.cleanup_old_logs(paths.log_path())
        strangers.cleanup(paths.strangers_dir(), self.cfg.strangers_retention_days)

    def tick(self, now: float) -> float:
        """Một vòng kiểm tra. Trả về số giây nghỉ trước vòng tiếp theo."""
        self._reload_if_changed(now)
        self._housekeeping(now)
        cfg = self.cfg

        # --- Máy đang khóa (kể cả Win+L): tắt camera, chờ mở khóa.
        if winapi.is_session_locked():
            if not self._was_locked:
                self._on_locked()
            self._set_state("locked", "Đã khóa")
            return 1.0
        if self._was_locked:
            self._on_unlocked(now)

        # --- Tạm dừng / cửa sổ con cần camera / ngoài lịch.
        if self.is_paused():
            return self._idle_state(now, f"Tạm dừng đến {time.strftime('%H:%M', time.localtime(self.paused_until))}")
        if camlock.requested_by_other():
            return self._idle_state(now, "Nhường camera cho cửa sổ đăng ký/cài đặt")
        if not schedule.is_active(cfg):
            return self._idle_state(now, "Ngoài lịch hoạt động")

        idle = winapi.idle_seconds()
        last_input = now - idle
        input_recent = idle < cfg.idle_grace

        # --- Tự khóa khi không thao tác (không cần camera).
        r = self.idle_lock.check(idle, last_input)
        if r == "warn":
            self._notify(f"Sẽ khóa sau {int(self.idle_lock.warn_seconds)}s vì không thao tác")
        elif r == "lock":
            self._lock(now, f"không thao tác {cfg.idle_lock_minutes} phút")
            return 1.0

        self.monitor.note_input(last_input)
        self.confirmer.expire(now)
        stranger_active = self.confirmer.pending or self.confirmer.confirmed

        if not (cfg.use_owner or cfg.use_person):
            self.camera.close()
            self._set_state("present", "Chỉ tự khóa khi không thao tác")
            return 0.5

        self._check_camera_consent(now)
        if not self.policy.want_camera(now, idle, stranger_active, self.camera.opened_at):
            self.camera.close()
            self._set_state("busy" if self._camera_busy else "present", "Đang làm việc (camera tắt)")
            return 0.5

        if not self.camera.open():
            self._set_state("paused", "Không có camera")
            return 1.0

        # --- Nhịp kiểm tra.
        interval = 1.0 / (1.0 if winapi.on_battery() else max(cfg.fps, 0.2))
        stranger_only = input_recent and not self.policy.check_requested and not self.confirmer.pending
        if stranger_only:
            interval = max(interval, cfg.continuous_check_seconds)  # đang gõ: chỉ kiểm tra người lạ
        if self.confirmer.pending:
            interval = 0.0  # nghi ngờ lần đầu: kiểm tra lại ngay
        if now - self._last_analysis < interval:
            self.camera.grab()  # không giải mã, chỉ giữ bộ đệm mới
            return min(0.5, interval - (now - self._last_analysis))

        frame = self.camera.read()
        if frame is None:
            # Frame lỗi không bao giờ bị tính là vắng mặt.
            return 0.2
        self._last_analysis = now
        if self.children and any(p.poll() is None for p in self.children):
            learn = False  # cửa sổ con có thể đang sửa owner.npz
        else:
            learn = True
        saved_learn = self.analyzer.cfg.learn_enabled
        self.analyzer.cfg.learn_enabled = saved_learn and learn
        try:
            analysis = self.analyzer.analyze(frame, now, input_recent)
        finally:
            self.analyzer.cfg.learn_enabled = saved_learn
        self.policy.check_done()
        self._handle(analysis, frame, now)
        return 0.05 if self.confirmer.pending else 0.1

    def _handle(self, analysis, frame, now: float) -> None:
        v = analysis.verdict
        if v is not self._last_verdict:
            log.debug("Kết luận: %s (giống chủ máy %s, người %s)", v.value,
                      None if analysis.best_similarity is None else round(analysis.best_similarity, 2),
                      analysis.person)
            self._last_verdict = v
        was_confirmed = self.confirmer.confirmed
        confirmed = self.confirmer.feed(v, now)
        if confirmed:
            if not was_confirmed:
                log.warning("Phát hiện người lạ (độ giống %.2f)", analysis.best_similarity or 0)
            self.monitor.mark_stranger(self.confirmer.first_seen)
            if v is Verdict.STRANGER:
                self.capture.maybe_capture(frame, analysis.face_boxes, now)
        elif v in (Verdict.OWNER, Verdict.PRESENT):
            self.monitor.mark_present(now)
        if v is Verdict.OWNER:
            self.capture.end_episode()

        observed = self.camera.ready_at
        if self.monitor.should_warn(now, observed):
            self._notify(f"Sẽ khóa sau {int(round(self.monitor.seconds_left(now)))}s"
                         + (" (người lạ)" if self.monitor.stranger else ""))
        status = self.monitor.status(now, observed)
        if status is Status.LOCK:
            self._lock(now, "người lạ" if self.monitor.stranger else "vắng mặt")
        elif status is Status.WARNING:
            self._set_state("warning", f"Vắng {int(self.monitor.absent_for(now))}s"
                            + (" (người lạ)" if self.monitor.stranger else ""))
        else:
            label = {Verdict.OWNER: "Có mặt", Verdict.PRESENT: "Có người"}.get(v, "Có mặt")
            self._set_state("busy" if self._camera_busy else "present", label)

    def _idle_state(self, now: float, detail: str) -> float:
        self.camera.close()
        self.monitor.reset(now)
        self.confirmer.reset()
        self.analyzer.tracker.reset()
        self._set_state("paused", detail)
        return 1.0

    def _check_camera_consent(self, now: float) -> None:
        if now - self._last_consent < CONSENT_INTERVAL:
            return
        self._last_consent = now
        try:
            busy = winapi.camera_in_use_by_other()
        except Exception:
            busy = False
        if busy != self._camera_busy:
            log.info("App khác %s camera", "đang dùng" if busy else "đã thôi dùng")
            self._camera_busy = busy

    def _lock(self, now: float, reason: str) -> None:
        if now - self._lock_requested_at < 3.0:
            return
        self._lock_requested_at = now
        if self.dry_run:
            log.warning("DRY-RUN: sẽ khóa máy (%s)", reason)
            self._set_state("locked", f"[dry-run] Đã khóa ({reason})")
            self._on_locked()
            self._on_unlocked(now)
            return
        log.warning("Khóa máy (%s)", reason)
        if not winapi.lock_workstation():
            log.error("LockWorkStation thất bại")
        self._on_locked()

    def _on_locked(self) -> None:
        if not self._was_locked:
            log.info("Máy đã khóa, tắt camera")
        self._was_locked = True
        self.camera.close()
        self.confirmer.reset()
        self.analyzer.tracker.reset()
        self.capture.end_episode()

    def _on_unlocked(self, now: float) -> None:
        if winapi.is_session_locked() and not self.dry_run:
            return
        self._was_locked = False
        log.info("Máy đã mở khóa")
        self.monitor.reset(now)
        self.confirmer.reset()
        self.policy.check_done()
        n = self.capture.take_new_count()
        if n:
            self._notify(f"Có {n} ảnh người lạ mới. Xem: menu tray → Ảnh người lạ")
        self._refresh_tray()


def _mtime(path) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _child_command(flag: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, flag]
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return [exe, os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"), flag]

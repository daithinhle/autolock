"""Chạy vòng lặp App.tick() với camera giả + đồng hồ giả (cần model ONNX)."""
from pathlib import Path

import cv2
import numpy as np
import pytest

import paths
import vision

FACE = Path(__file__).parent / "data" / "face.jpg"
pytestmark = pytest.mark.skipif(not (paths.models_dir() / vision.SFACE_FILE).exists() or not FACE.exists(),
                                reason="thiếu model hoặc ảnh mẫu")


class Clock:
    t = 1_800_000_000.0


class FakeCamera:
    frame = None

    def __init__(self, index=0):
        self.index = index
        self.opened_at = self.ready_at = None
        self.opens = 0

    @property
    def is_open(self):
        return self.opened_at is not None

    def open(self):
        if self.opened_at is None:
            self.opened_at = Clock.t
            self.opens += 1
        return True

    def close(self):
        self.opened_at = self.ready_at = None

    def grab(self):
        return True

    def read(self):
        if self.ready_at is None:
            self.ready_at = Clock.t
        return None if FakeCamera.frame is None else FakeCamera.frame.copy()


@pytest.fixture
def env(monkeypatch):
    import app as app_mod
    import owner
    import winapi

    state = {"idle": 100.0, "locked": False, "locks": 0}
    monkeypatch.setattr(winapi, "is_session_locked", lambda: state["locked"])
    monkeypatch.setattr(winapi, "idle_seconds", lambda: state["idle"])
    monkeypatch.setattr(winapi, "on_battery", lambda: False)
    monkeypatch.setattr(winapi, "has_battery", lambda: False)
    monkeypatch.setattr(winapi, "camera_in_use_by_other", lambda: False)

    def lock():
        state["locks"] += 1
        state["locked"] = True
        return True

    monkeypatch.setattr(winapi, "lock_workstation", lock)
    monkeypatch.setattr(app_mod, "Camera", FakeCamera)

    # Đăng ký chủ máy từ ảnh mẫu (vài biến thể sáng/tối/dịch).
    vision.configure_cv()
    fe = vision.FaceEngine()
    img = vision.imread(FACE)
    feats = []
    for i in range(24):
        v = cv2.convertScaleAbs(img, alpha=0.8 + 0.02 * i, beta=(i % 5) * 4)
        v = np.roll(v, i - 12, axis=1)
        f = max(fe.detect(v), key=lambda x: x.width)
        feats.append(fe.describe(v, f))
    owner.OwnerLibrary(np.array(feats)).save(paths.owner_path())

    a = app_mod.App(dry_run=False, use_tray=False)
    a.cfg.camera_mode = "continuous"
    a._apply_config(Clock.t)
    return a, state, img


def run(app, seconds, step=0.25):
    end = Clock.t + seconds
    while Clock.t < end:
        app.tick(Clock.t)
        Clock.t += step


def test_owner_present_then_absent_locks(env):
    app, state, img = env
    FakeCamera.frame = cv2.resize(img, (640, 480))
    run(app, 20)
    assert state["locks"] == 0
    assert app.state == "present"
    assert app._last_verdict.value == "owner"

    FakeCamera.frame = np.zeros((480, 640, 3), np.uint8)    # chủ máy rời đi
    run(app, 6)
    assert app.state == "warning" and state["locks"] == 0
    run(app, 8)
    assert state["locks"] == 1
    assert not app.camera.is_open                           # máy khóa thì tắt camera

    # Mở khóa: đếm lại từ đầu.
    state["locked"] = False
    FakeCamera.frame = cv2.resize(img, (640, 480))
    run(app, 5)
    assert app.state == "present" and state["locks"] == 1


def test_typing_keeps_unlocked_without_face(env):
    app, state, img = env
    FakeCamera.frame = np.zeros((480, 640, 3), np.uint8)
    state["idle"] = 1.0
    run(app, 30)
    assert state["locks"] == 0


def test_frame_errors_never_count_as_absent(env):
    app, state, img = env
    FakeCamera.frame = None
    run(app, 30)
    assert state["locks"] == 0


def test_pause_and_schedule_disable_monitoring(env):
    app, state, img = env
    FakeCamera.frame = np.zeros((480, 640, 3), np.uint8)
    app.pause(15)
    app.paused_until = Clock.t + 60
    run(app, 30)
    assert state["locks"] == 0 and app.state == "paused" and not app.camera.is_open


def test_idle_lock_without_camera(env):
    app, state, img = env
    app.cfg.use_owner = app.cfg.use_person = False
    app.cfg.idle_lock_minutes = 1
    app._apply_config(Clock.t)
    state["idle"] = 30
    run(app, 1)
    assert state["locks"] == 0
    state["idle"] = 61
    run(app, 1)
    assert state["locks"] == 1

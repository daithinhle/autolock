import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

import logsetup
import paths
import strangers
import vision
from conftest import ROOT


# ---------------- paths ----------------
def test_env_override(isolated_data_dir):
    assert paths.data_dir() == isolated_data_dir
    assert isolated_data_dir.is_dir()


def test_portable_dir_used_when_present(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOLOCK_DATA_DIR")
    app = tmp_path / "app"
    (app / "data").mkdir(parents=True)
    monkeypatch.setattr(paths, "app_dir", lambda: app)
    monkeypatch.setattr(paths, "is_private_local", lambda p: True)
    assert paths.data_dir() == app / "data"
    monkeypatch.setattr(paths, "is_private_local", lambda p: False)
    assert paths.data_dir() == tmp_path / "localappdata" / "AutoLock"


def test_no_portable_dir_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOLOCK_DATA_DIR")
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path / "app2")
    assert paths.data_dir() == tmp_path / "localappdata" / "AutoLock"


@pytest.mark.parametrize("sub", ["OneDrive/AutoLock", "OneDrive - Contoso/x", "Dropbox/a", "Google Drive/a",
                                 "iCloudDrive/a", "My Drive/a"])
def test_cloud_folders_not_private(tmp_path, sub):
    assert paths._in_cloud_folder(tmp_path / sub)
    assert not paths.is_private_local(tmp_path / sub)


def test_onedrive_env(tmp_path, monkeypatch):
    od = tmp_path / "Sync Root"
    monkeypatch.setenv("OneDrive", str(od))
    assert paths._in_cloud_folder(od / "AutoLock" / "data")


def test_local_disk_private(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows only")
    assert paths.is_private_local(tmp_path)
    assert not paths.is_private_local(r"\\server\share\data")


# ---------------- offline ----------------
def _run(code):
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=60)


def test_offline_blocks_external_and_allows_loopback():
    r = _run("""
        import socket, offline
        offline.install()
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        c = socket.create_connection(srv.getsockname(), timeout=5); c.close()
        print("loopback-ok")
        for target in [("93.184.216.34", 80), ("example.com", 80)]:
            try:
                socket.create_connection(target, timeout=2)
                print("LEAK", target)
            except offline.NetworkBlockedError:
                print("blocked")
        import urllib.request
        try:
            urllib.request.urlopen("http://example.com", timeout=2)
            print("LEAK http")
        except Exception as e:
            print("blocked" if "offline" in str(e) else "OTHER " + repr(e))
    """)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.split()
    assert lines[0] == "loopback-ok"
    assert lines[1:] == ["blocked", "blocked", "blocked"]


def test_is_loopback_host():
    import offline
    assert offline.is_loopback_host("127.0.0.1")
    assert offline.is_loopback_host("::1")
    assert offline.is_loopback_host("localhost")
    assert not offline.is_loopback_host("8.8.8.8")
    assert not offline.is_loopback_host("example.com")


# ---------------- log ----------------
def test_log_cleanup(tmp_path):
    log = tmp_path / "autolock.log"
    log.write_text("x")
    old = tmp_path / "autolock.log.2026-11-01_10"
    fresh = tmp_path / "autolock.log.2026-11-10_10"
    other = tmp_path / "other.txt"
    for p in (old, fresh, other):
        p.write_text("x")
    now = time.time()
    os.utime(old, (now - 25 * 3600, now - 25 * 3600))
    os.utime(other, (now - 99 * 3600, now - 99 * 3600))
    assert logsetup.cleanup_old_logs(log, now=now) == 1
    assert not old.exists() and fresh.exists() and other.exists() and log.exists()


# ---------------- người lạ ----------------
def test_stranger_capture_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "is_private_local", lambda p: True)
    cap = strangers.StrangerCapture(tmp_path / "strangers")
    frame = np.zeros((120, 160, 3), np.uint8)
    t = 1_700_000_000.0
    assert cap.maybe_capture(frame, [(10, 10, 40, 40)], t)
    assert cap.maybe_capture(frame, [], t + 5) is None          # < 10s
    assert cap.maybe_capture(frame, [], t + 10)
    assert cap.maybe_capture(frame, [], t + 20)
    assert cap.maybe_capture(frame, [], t + 30) is None         # tối đa 3 ảnh / lần
    cap.end_episode()
    assert cap.maybe_capture(frame, [], t + 40)
    assert cap.take_new_count() == 4 and cap.take_new_count() == 0


def test_stranger_capture_refuses_non_private(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "is_private_local", lambda p: False)
    cap = strangers.StrangerCapture(tmp_path / "strangers")
    assert cap.maybe_capture(np.zeros((10, 10, 3), np.uint8), [], 0) is None
    assert not (tmp_path / "strangers").exists()


def test_stranger_retention(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    now = time.time()
    for i in range(6):
        p = d / f"{i}.jpg"
        p.write_bytes(b"x")
        age = (i * 2) * 86400
        os.utime(p, (now - age, now - age))
    removed = strangers.cleanup(d, retention_days=7, now=now, max_files=3)
    left = sorted(p.stem for p in d.glob("*.jpg"))
    assert left == ["0", "1", "2"] and removed == 3


# ---------------- vision ----------------
def test_head_pose_and_frontal():
    lm = np.array([[40, 40], [80, 40], [60, 62], [45, 80], [75, 80]], np.float32)
    yaw, pitch = vision.head_pose(lm)
    assert abs(yaw) < 1e-6 and 0.4 < pitch < 0.7
    assert vision.is_frontal(lm)
    turned = lm.copy()
    turned[2, 0] = 78
    assert vision.head_pose(turned)[0] > 0.3 and not vision.is_frontal(turned)


def test_edges_and_iou():
    assert vision.touches_edge((0, 10, 50, 50), (480, 640))
    assert vision.touches_edge((600, 10, 50, 50), (480, 640))
    assert not vision.touches_edge((100, 100, 50, 50), (480, 640))
    assert vision.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1
    assert vision.iou((0, 0, 10, 10), (20, 20, 10, 10)) == 0


def test_enhance_brightens_dark_only():
    dark = np.full((60, 80, 3), 20, np.uint8)
    assert vision.enhance(dark).mean() > 40
    bright = np.full((60, 80, 3), 150, np.uint8)
    assert vision.enhance(bright) is bright


def test_imwrite_unicode_path(tmp_path):
    p = tmp_path / "ảnh người lạ.jpg"
    vision.imwrite(p, np.zeros((8, 8, 3), np.uint8))
    assert vision.imread(p).shape == (8, 8, 3)


models_present = (paths.models_dir() / vision.YUNET_FILE).exists()


@pytest.mark.skipif(not models_present, reason="chưa tải model (python tools/download_models.py)")
def test_models_load_and_run():
    vision.configure_cv()
    fe = vision.FaceEngine()
    pd = vision.PersonDetector()
    img = np.zeros((480, 640, 3), np.uint8)
    assert fe.detect(img) == []
    assert pd.detect(img) == []


# ---------------- đăng ký ----------------
def test_enroll_pose_checker_mirror_independent():
    import enroll
    pc = enroll.PoseChecker()
    for _ in range(4):
        pc.note("base", (0.02, 0.55))
    # Camera lật ảnh: "trái" ra yaw âm, "phải" phải ngược lại.
    assert pc.matches("left", (-0.2, 0.55))
    pc.note("left", (-0.2, 0.55))
    assert not pc.matches("right", (-0.2, 0.55))
    assert pc.matches("right", (0.2, 0.55))
    assert pc.matches("up", (0.0, 0.40)) and not pc.matches("up", (0.0, 0.60))
    assert pc.matches("down", (0.0, 0.70))
    assert pc.matches("front", (0.03, 0.56)) and not pc.matches("front", (0.2, 0.56))

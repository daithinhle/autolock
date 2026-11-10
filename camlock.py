"""Cửa sổ đăng ký/cài đặt (tiến trình con) báo cho tiến trình chính nhường camera.

Tiến trình con ghi PID của nó vào <data>/camera.request khi cần camera; tiến trình chính thấy file này
và PID còn sống thì tắt camera của mình.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import paths
import winapi

FILE_NAME = "camera.request"


def request_path() -> Path:
    return paths.data_dir() / FILE_NAME


def acquire() -> None:
    try:
        request_path().write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass


def release() -> None:
    p = request_path()
    try:
        if p.read_text(encoding="ascii").strip() == str(os.getpid()):
            p.unlink()
    except OSError:
        pass


@contextmanager
def holding():
    acquire()
    try:
        yield
    finally:
        release()


def requested_by_other() -> bool:
    p = request_path()
    try:
        pid = int(p.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False
    if winapi.pid_alive(pid):
        return True
    try:
        p.unlink()  # tiến trình con đã chết mà không dọn
    except OSError:
        pass
    return False

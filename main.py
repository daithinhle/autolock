"""AutoLock: tự khóa Windows khi chủ máy rời khỏi webcam.

    pythonw main.py [--dry-run] [--enroll | --settings] [tùy chọn ghi đè config]
"""
from __future__ import annotations

import offline

offline.install()  # chặn mạng trước khi nạp bất kỳ thư viện nào khác

import argparse  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402

import logsetup  # noqa: E402
import paths  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="AutoLock", description="Tự khóa Windows khi bạn rời khỏi webcam.")
    p.add_argument("--dry-run", action="store_true", help="chỉ ghi log, không khóa thật, không đăng ký tự khởi động")
    p.add_argument("--enroll", action="store_true", help="chỉ mở cửa sổ đăng ký khuôn mặt")
    p.add_argument("--settings", action="store_true", help="chỉ mở cửa sổ cài đặt")
    p.add_argument("--camera", type=int, help="số thứ tự camera")
    p.add_argument("--camera-mode", choices=["on_demand", "continuous"])
    p.add_argument("--lock", type=int, help="vắng bao nhiêu giây thì khóa")
    p.add_argument("--idle-lock", type=int, help="tự khóa sau N phút không thao tác (0 = tắt)")
    p.add_argument("--warn", type=int, help="vắng bao nhiêu giây thì icon vàng")
    p.add_argument("--fps", type=float, help="số lần kiểm tra mỗi giây")
    p.add_argument("--idle-grace", type=int, help="thao tác trong N giây gần nhất = có mặt")
    p.add_argument("--no-person", action="store_true", help="tắt phát hiện người")
    p.add_argument("--no-owner", action="store_true", help="tắt nhận diện chủ máy")
    p.add_argument("--no-tray", action="store_true", help="không hiện icon khay hệ thống")
    p.add_argument("--debug", action="store_true", help="log chi tiết, in ra console")
    return p.parse_args(argv)


def overrides_from_args(a: argparse.Namespace) -> dict:
    o = {}
    mapping = {"camera": "camera_index", "camera_mode": "camera_mode", "lock": "lock_seconds",
               "idle_lock": "idle_lock_minutes", "warn": "warn_seconds", "fps": "fps", "idle_grace": "idle_grace"}
    for arg, key in mapping.items():
        v = getattr(a, arg)
        if v is not None:
            o[key] = v
    if a.no_person:
        o["use_person"] = False
    if a.no_owner:
        o["use_owner"] = False
    return o


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.enroll or args.settings:
        logsetup.setup_child(logging.DEBUG if args.debug else logging.WARNING)
        if args.enroll:
            import enroll
            return enroll.run()
        import settings_ui
        return settings_ui.run()

    import winapi
    if not winapi.acquire_single_instance():
        return 0  # đã có một bản đang chạy

    logsetup.setup_main(paths.log_path(), logging.DEBUG if args.debug else logging.INFO, console=args.debug)
    log = logging.getLogger("autolock")
    try:
        import vision
        try:
            winapi.lower_priority()
        except Exception as e:
            log.warning("Không hạ được độ ưu tiên tiến trình: %s", e)
        vision.configure_cv()
        if not args.dry_run:
            try:
                winapi.ensure_autostart()
            except OSError as e:
                log.warning("Không đăng ký được chạy cùng Windows: %s", e)
        from app import App
        App(overrides_from_args(args), dry_run=args.dry_run, use_tray=not args.no_tray).run()
    except Exception:
        log.exception("Lỗi nghiêm trọng")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tải 3 model ONNX từ OpenCV Zoo vào models/ và kiểm tra SHA-256.

    .venv\\Scripts\\python tools\\download_models.py

Chỉ dùng lúc phát triển/đóng gói; app khi chạy không bao giờ truy cập mạng (xem offline.py).
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "face_detection_yunet/",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "face_recognition_sface_2021dec.onnx": (
        "face_recognition_sface/",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
    "object_detection_yolox_2022nov.onnx": (
        "object_detection_yolox/",
        "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out = Path(__file__).resolve().parent.parent / "models"
    out.mkdir(exist_ok=True)
    ok = True
    for name, (sub, digest) in MODELS.items():
        dest = out / name
        if dest.exists() and sha256(dest) == digest:
            print(f"OK   {name}")
            continue
        print(f"Tải  {name} ...")
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(BASE + sub + name, tmp)
        got = sha256(tmp)
        if got != digest:
            tmp.unlink()
            print(f"LỖI  {name}: SHA-256 không khớp ({got})", file=sys.stderr)
            ok = False
            continue
        tmp.replace(dest)
        print(f"OK   {name}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

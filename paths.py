"""Vị trí file: thư mục app, model, dữ liệu (portable hoặc %LOCALAPPDATA%).

Quy tắc chọn thư mục dữ liệu:
- Biến môi trường AUTOLOCK_DATA_DIR (dùng cho test) được ưu tiên.
- Có thư mục `data\\` cạnh AutoLock.exe / main.py, ghi được và là ổ cứng cục bộ
  không đồng bộ đám mây -> dùng nó (chế độ portable).
- Ngược lại -> %LOCALAPPDATA%\\AutoLock.
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

APP_NAME = "AutoLock"
ENV_DATA_DIR = "AUTOLOCK_DATA_DIR"

# Tên thư mục gốc của các dịch vụ đồng bộ đám mây phổ biến (so khớp không phân biệt hoa thường).
_CLOUD_DIR_PREFIXES = (
    "onedrive",          # OneDrive, OneDrive - Company
    "dropbox",
    "google drive",
    "googledrive",
    "my drive",
    "icloud drive",
    "iclouddrive",
    "icloud",
    "box",
    "box sync",
    "mega",
    "megasync",
    "pcloud drive",
    "nextcloud",
    "owncloud",
    "sync",              # Sync.com
    "yandex.disk",
)
_CLOUD_ENV_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")

DRIVE_FIXED = 3
# STORAGE_BUS_TYPE: USB, SD, MMC, iSCSI là ổ di động / qua mạng.
_REMOVABLE_BUS_TYPES = {7, 0x0C, 0x0D, 0x09}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Thư mục chứa AutoLock.exe (bản đóng gói) hoặc mã nguồn."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """Thư mục tài nguyên đóng gói (PyInstaller giải nén vào _MEIPASS)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else app_dir()


def models_dir() -> Path:
    return resource_dir() / "models"


def _localappdata_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def _is_writable_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        fd, name = tempfile.mkstemp(prefix=".write-test-", dir=str(path))
        os.close(fd)
        os.remove(name)
        return True
    except OSError:
        return False


def _in_cloud_folder(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    low = str(resolved).lower()
    for var in _CLOUD_ENV_VARS:
        root = os.environ.get(var)
        if root:
            r = str(Path(root)).lower().rstrip("\\/")
            if low == r or low.startswith(r + os.sep) or low.startswith(r + "/"):
                return True
    for part in resolved.parts[1:]:
        p = part.lower()
        for prefix in _CLOUD_DIR_PREFIXES:
            if p == prefix or (prefix in ("onedrive", "dropbox") and p.startswith(prefix)):
                return True
    return False


def _drive_root(path: Path) -> str | None:
    drive = path.drive
    if not drive or drive.startswith("\\\\") or drive.startswith("//"):
        return None  # UNC = ổ mạng
    return drive + "\\"


def _bus_type(drive_root: str) -> int | None:
    """STORAGE_BUS_TYPE của ổ chứa drive_root, None nếu không đọc được."""
    if sys.platform != "win32":
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                    wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                    wintypes.LPVOID]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    volume = "\\\\.\\" + drive_root.rstrip("\\")
    handle = k32.CreateFileW(volume, 0, 3, None, 3, 0, None)  # share read|write, OPEN_EXISTING
    if handle in (None, wintypes.HANDLE(-1).value):
        return None
    try:
        # STORAGE_PROPERTY_QUERY{PropertyId=StorageDeviceProperty(0), QueryType=PropertyStandardQuery(0)}
        query = (ctypes.c_ubyte * 12)()
        out = (ctypes.c_ubyte * 1024)()
        returned = wintypes.DWORD()
        IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
        ok = k32.DeviceIoControl(handle, IOCTL_STORAGE_QUERY_PROPERTY, query, 12, out, 1024,
                                 ctypes.byref(returned), None)
        if not ok or returned.value < 32:
            return None
        # STORAGE_DEVICE_DESCRIPTOR.BusType ở offset 28 (DWORD).
        return int.from_bytes(bytes(out[28:32]), "little")
    finally:
        k32.CloseHandle(handle)


def is_private_local(path: Path | str) -> bool:
    """True nếu path nằm trên ổ cứng cục bộ, không phải ổ mạng/USB/thẻ nhớ và không trong thư mục đồng bộ đám mây.

    Ảnh (người lạ, ảnh mặt thu nhỏ) chỉ được ghi khi hàm này trả True.
    """
    path = Path(path)
    if _in_cloud_folder(path):
        return False
    if sys.platform != "win32":
        return True
    try:
        root = _drive_root(path.resolve())
    except OSError:
        root = _drive_root(path.absolute())
    if root is None:
        return False
    if ctypes.windll.kernel32.GetDriveTypeW(root) != DRIVE_FIXED:
        return False
    bus = _bus_type(root)
    if bus is not None and bus in _REMOVABLE_BUS_TYPES:
        return False
    return True


def portable_data_dir() -> Path:
    return app_dir() / "data"


def data_dir(create: bool = True) -> Path:
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        d = Path(override)
    else:
        portable = portable_data_dir()
        if _is_writable_dir(portable) and is_private_local(portable):
            d = portable
        else:
            d = _localappdata_dir()
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def is_portable() -> bool:
    try:
        return data_dir(create=False).resolve() == portable_data_dir().resolve()
    except OSError:
        return False


def config_path() -> Path:
    return data_dir() / "config.json"


def owner_path() -> Path:
    return data_dir() / "owner.npz"


def log_path() -> Path:
    return data_dir() / "autolock.log"


def strangers_dir() -> Path:
    return data_dir() / "strangers"


def learned_dir() -> Path:
    return data_dir() / "learned"

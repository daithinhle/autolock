"""Các lời gọi Windows API qua ctypes/winreg."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import winreg
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_KEY = r"Software\AutoLock"
RUN_VALUE = "AutoLock"
FIRST_RUN_FLAG = "AutostartInitialized"
CONSENT_WEBCAM = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"


# ---------------- khóa máy / thao tác ----------------
def lock_workstation() -> bool:
    if not IS_WINDOWS:
        return False
    return bool(user32.LockWorkStation())


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    """Số giây kể từ lần gõ phím/di chuột cuối."""
    if not IS_WINDOWS:
        return 0.0
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    tick = kernel32.GetTickCount() & 0xFFFFFFFF
    return ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def is_session_locked() -> bool:
    """True khi màn hình khóa / UAC / màn hình đăng nhập đang hiển thị."""
    if not IS_WINDOWS:
        return False
    DESKTOP_SWITCHDESKTOP = 0x0100
    h = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not h:
        return True
    try:
        return not user32.SwitchDesktop(h)
    finally:
        user32.CloseDesktop(h)


# ---------------- nguồn điện ----------------
class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def _power_status():
    if not IS_WINDOWS:
        return None
    s = _SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None
    return s


def has_battery() -> bool:
    s = _power_status()
    return bool(s and s.BatteryFlag != 128 and s.BatteryFlag != 255)


def on_battery() -> bool:
    s = _power_status()
    return bool(s and s.ACLineStatus == 0)


# ---------------- tài nguyên ----------------
class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]


def lower_priority() -> None:
    """Below Normal + Efficiency mode (EcoQoS)."""
    if not IS_WINDOWS:
        return
    BELOW_NORMAL_PRIORITY_CLASS = 0x4000
    proc = kernel32.GetCurrentProcess()
    if not kernel32.SetPriorityClass(proc, BELOW_NORMAL_PRIORITY_CLASS):
        log.debug("SetPriorityClass lỗi %s", ctypes.get_last_error())
    try:
        ProcessPowerThrottling = 4
        state = _PROCESS_POWER_THROTTLING_STATE(1, 1, 1)  # EXECUTION_SPEED
        kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        if not kernel32.SetProcessInformation(proc, ProcessPowerThrottling, ctypes.byref(state), ctypes.sizeof(state)):
            log.debug("EcoQoS lỗi %s", ctypes.get_last_error())
    except AttributeError:
        pass


# ---------------- một bản duy nhất ----------------
_mutex = None


def acquire_single_instance(name: str = "Local\\AutoLock.SingleInstance") -> bool:
    global _mutex
    if not IS_WINDOWS:
        return True
    ERROR_ALREADY_EXISTS = 183
    _mutex = kernel32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def pid_alive(pid: int) -> bool:
    if not IS_WINDOWS:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(wintypes.HANDLE(h), ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(h))


# ---------------- chạy cùng Windows ----------------
def launch_command(*extra: str) -> str:
    """Lệnh khởi chạy app (bản exe hoặc pythonw main.py)."""
    if getattr(sys, "frozen", False):
        parts = [sys.executable]
    else:
        exe = sys.executable
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(pyw):
            exe = pyw
        parts = [exe, os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")]
    parts += list(extra)
    return " ".join(f'"{p}"' if " " in p or not p else p for p in parts)


def _read_value(root, key, name):
    try:
        with winreg.OpenKey(root, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _write_value(root, key, name, value, kind=None):
    kind = winreg.REG_SZ if kind is None else kind
    with winreg.CreateKeyEx(root, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    return _read_value(winreg.HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE) is not None


def set_autostart(enabled: bool) -> None:
    if not IS_WINDOWS:
        return
    if enabled:
        _write_value(winreg.HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE, launch_command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, RUN_VALUE)
        except OSError:
            pass
    mark_first_run_done()


def mark_first_run_done() -> None:
    if IS_WINDOWS:
        _write_value(winreg.HKEY_CURRENT_USER, APP_KEY, FIRST_RUN_FLAG, 1, winreg.REG_DWORD)


def ensure_autostart() -> None:
    """Lần chạy đầu trên máy này: đăng ký chạy cùng Windows. Sau đó chỉ cập nhật đường dẫn nếu app bị chuyển chỗ.

    Cờ "đã bật lần đầu" lưu ở HKCU\\Software\\AutoLock (theo máy) để bản portable sang máy mới vẫn tự đăng ký,
    còn người dùng đã tắt thì không tự bật lại.
    """
    if not IS_WINDOWS:
        return
    flag = _read_value(winreg.HKEY_CURRENT_USER, APP_KEY, FIRST_RUN_FLAG)
    current = _read_value(winreg.HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE)
    wanted = launch_command()
    if not flag:
        set_autostart(True)
        log.info("Đã đăng ký chạy cùng Windows")
    elif current is not None and current != wanted:
        _write_value(winreg.HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE, wanted)
        log.info("Cập nhật đường dẫn chạy cùng Windows: %s", wanted)


# ---------------- app khác đang dùng camera ----------------
def camera_in_use_by_other() -> bool:
    """Đọc ConsentStore: có app (khác AutoLock/python) đang dùng webcam (LastUsedTimeStop == 0)."""
    if not IS_WINDOWS:
        return False
    me = {os.path.basename(sys.executable).lower(), "python.exe", "pythonw.exe", "autolock.exe"}

    def walk(root_key, path):
        try:
            with winreg.OpenKey(root_key, path) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    sub_path = path + "\\" + sub
                    if sub == "NonPackaged":
                        if walk(root_key, sub_path):
                            return True
                        continue
                    name = sub.replace("#", "\\").rsplit("\\", 1)[-1].lower()
                    if name in me:
                        continue
                    start = _read_value(root_key, sub_path, "LastUsedTimeStart")
                    stop = _read_value(root_key, sub_path, "LastUsedTimeStop")
                    if start and stop == 0:
                        return True
        except OSError:
            return False
        return False

    return walk(winreg.HKEY_CURRENT_USER, CONSENT_WEBCAM)

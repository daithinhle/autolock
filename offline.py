"""Chặn mọi truy cập mạng ra ngoài máy bằng audit hook của Python.

Gọi `install()` càng sớm càng tốt khi khởi động. Audit hook không gỡ được, nên sau khi cài,
toàn bộ tiến trình (kể cả thư viện bên thứ ba dùng module socket của Python) chỉ còn kết nối
được tới loopback.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import sys

log = logging.getLogger(__name__)

_installed = False
_LOCAL_NAMES = {"localhost", "localhost.", "ip6-localhost", ""}


class NetworkBlockedError(PermissionError):
    pass


def is_loopback_host(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host).strip().strip("[]").lower()
    if host in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _address_allowed(address) -> bool:
    if isinstance(address, (str, bytes)):  # AF_UNIX / named pipe
        return True
    if isinstance(address, tuple) and address:
        return is_loopback_host(address[0])
    return False


def _hook(event: str, args) -> None:
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        address = args[1] if len(args) > 1 else None
        if event == "socket.sendmsg" and address is None:
            return  # socket đã connect, connect đã được kiểm tra
        sock = args[0]
        family = getattr(sock, "family", None)
        if family not in (socket.AF_INET, socket.AF_INET6):
            return
        if not _address_allowed(address):
            raise NetworkBlockedError(f"AutoLock offline: chặn kết nối tới {address!r}")
    elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
                   "socket.gethostbyaddr", "socket.getnameinfo"):
        host = args[0] if args else None
        if isinstance(host, tuple):
            host = host[0] if host else None
        if not is_loopback_host(host):
            raise NetworkBlockedError(f"AutoLock offline: chặn tra DNS {host!r}")
    elif event == "urllib.Request":
        url = str(args[0]) if args else ""
        if not url.lower().startswith("file:"):
            from urllib.parse import urlsplit
            if not is_loopback_host(urlsplit(url).hostname):
                raise NetworkBlockedError(f"AutoLock offline: chặn HTTP {url!r}")
    elif event == "http.client.connect":
        host = args[1] if len(args) > 1 else None
        if not is_loopback_host(host):
            raise NetworkBlockedError(f"AutoLock offline: chặn HTTP tới {host!r}")


def install() -> None:
    global _installed
    if _installed:
        return
    sys.addaudithook(_hook)
    _installed = True


def is_installed() -> bool:
    return _installed

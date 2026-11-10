"""Icon + menu ở khay hệ thống (pystray)."""
from __future__ import annotations

import logging
import threading
from functools import lru_cache

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

COLORS = {
    "present": (46, 160, 67),     # xanh lá: có mặt
    "warning": (230, 170, 0),     # vàng: sắp khóa
    "locked": (210, 45, 45),      # đỏ: đã khóa
    "paused": (128, 128, 128),    # xám: tạm dừng / không có camera / ngoài lịch
    "busy": (40, 110, 220),       # xanh dương: app khác đang dùng camera
}


@lru_cache(maxsize=None)
def make_icon(state: str, size: int = 64) -> Image.Image:
    color = COLORS.get(state, COLORS["paused"])
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0
    d.ellipse((2 * s, 2 * s, 62 * s, 62 * s), fill=color + (255,))
    # Thân camera + ống kính.
    white = (255, 255, 255, 255)
    d.rounded_rectangle((13 * s, 22 * s, 43 * s, 44 * s), radius=4 * s, fill=white)
    d.polygon([(43 * s, 30 * s), (53 * s, 23 * s), (53 * s, 43 * s), (43 * s, 36 * s)], fill=white)
    d.ellipse((22 * s, 27 * s, 34 * s, 39 * s), fill=color + (255,))
    return img


class Tray:
    """Bọc pystray. `app` cung cấp các thuộc tính/hàm được menu gọi."""

    def __init__(self, app):
        import pystray
        self._pystray = pystray
        self.app = app
        self.state = "paused"
        self.icon = pystray.Icon("AutoLock", make_icon(self.state), "AutoLock", menu=self._menu())
        self._thread: threading.Thread | None = None

    # ---------- menu ----------
    def _menu(self):
        ps = self._pystray
        Item, Menu = ps.MenuItem, ps.Menu
        app = self.app

        def pause(minutes):
            return lambda icon, item: app.pause(minutes)

        def mode(m):
            return Item({"on_demand": "Khi cần", "continuous": "Liên tục"}[m],
                        lambda icon, item: app.set_camera_mode(m),
                        checked=lambda item: app.camera_mode == m, radio=True)

        def idle(minutes):
            label = "Tắt" if minutes == 0 else f"{minutes} phút"
            return Item(label, lambda icon, item: app.set_idle_lock(minutes),
                        checked=lambda item: app.cfg.idle_lock_minutes == minutes, radio=True)

        from config import IDLE_LOCK_PRESETS
        idle_items = [idle(m) for m in IDLE_LOCK_PRESETS]
        idle_items.append(Item(lambda item: "Tùy chỉnh..." if app.cfg.idle_lock_minutes in IDLE_LOCK_PRESETS
                               else f"Tùy chỉnh ({app.cfg.idle_lock_minutes} phút)...",
                               lambda icon, item: app.open_settings(),
                               checked=lambda item: app.cfg.idle_lock_minutes not in IDLE_LOCK_PRESETS,
                               radio=True))

        return Menu(
            Item(lambda item: app.status_text(), None, enabled=False),
            Menu.SEPARATOR,
            Item("Tạm dừng 15 phút", pause(15)),
            Item("Tạm dừng 30 phút", pause(30)),
            Item("Tạm dừng 60 phút", pause(60)),
            Item("Tiếp tục", lambda icon, item: app.resume(), visible=lambda item: app.is_paused()),
            Menu.SEPARATOR,
            Item("Chế độ camera", Menu(mode("on_demand"), mode("continuous"))),
            Item("Tự khóa khi không thao tác", Menu(*idle_items)),
            Item(lambda item: f"Chỉ chạy theo lịch ({app.schedule_text()})",
                 lambda icon, item: app.toggle_schedule(),
                 checked=lambda item: app.cfg.schedule_enabled),
            Item(lambda item: f"Ảnh người lạ ({app.stranger_photo_count()})",
                 lambda icon, item: app.open_strangers()),
            Menu.SEPARATOR,
            Item("Đăng ký lại khuôn mặt", lambda icon, item: app.open_enroll()),
            Item("Cài đặt...", lambda icon, item: app.open_settings()),
            Item("Chạy cùng Windows", lambda icon, item: app.toggle_autostart(),
                 checked=lambda item: app.autostart_enabled()),
            Menu.SEPARATOR,
            Item("Thoát", lambda icon, item: app.quit()),
        )

    # ---------- vòng đời ----------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self.icon.run()
        except Exception:
            log.exception("Tray lỗi")

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass

    def set_state(self, state: str, tooltip: str) -> None:
        if state != self.state:
            self.state = state
            self.icon.icon = make_icon(state)
        tooltip = tooltip[:120]
        if self.icon.title != tooltip:
            self.icon.title = tooltip

    def refresh(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str, title: str = "AutoLock") -> None:
        try:
            self.icon.notify(message, title)
        except Exception as e:
            log.debug("Không hiện được thông báo: %s", e)

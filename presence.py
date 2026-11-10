"""Logic quyết định (thuần, không phụ thuộc camera/Windows) để unit test được.

- classify(): một lần kiểm tra -> OWNER / STRANGER / PRESENT / ABSENT.
- StrangerConfirmer: "người lạ" cần 2 lần kiểm tra liên tiếp cách nhau <= 3s.
- PresenceMonitor: đếm thời gian vắng -> cảnh báo / khóa.
- IdleLock: tự khóa khi không thao tác.
- CameraPolicy: chế độ Khi cần / Liên tục, kiểm tra định kỳ.
"""
from __future__ import annotations

import enum
import random
from dataclasses import dataclass

STRANGER_CONFIRM_WINDOW = 3.0
MIN_OBSERVE_BEFORE_LOCK = 4.0
CAMERA_MIN_ON = 5.0


class Verdict(enum.Enum):
    OWNER = "owner"          # thấy mặt chủ máy
    STRANGER = "stranger"    # chỉ thấy mặt người lạ, đủ rõ
    PRESENT = "present"      # không rõ ai nhưng thấy người / có thao tác
    ABSENT = "absent"


@dataclass
class FaceInfo:
    similarity: float | None   # None = không dùng nhận diện chủ máy
    clear: bool                # đủ rõ để đánh giá
    tracked: bool = False      # đang được bám theo là chủ máy


def classify(faces: list[FaceInfo], person: bool, input_recent: bool,
             owner_threshold: float = 0.40, stranger_threshold: float = 0.25) -> Verdict:
    if any(f.tracked or (f.similarity is not None and f.similarity >= owner_threshold) for f in faces):
        return Verdict.OWNER
    if faces and all(f.clear and f.similarity is not None and f.similarity < stranger_threshold for f in faces):
        return Verdict.STRANGER
    if person or input_recent:
        return Verdict.PRESENT
    return Verdict.ABSENT


class StrangerConfirmer:
    """Người lạ phải được thấy ở 2 lần kiểm tra liên tiếp cách nhau <= 3s."""

    def __init__(self, window: float = STRANGER_CONFIRM_WINDOW):
        self.window = window
        self.first_seen: float | None = None
        self._last: float | None = None
        self.confirmed = False

    @property
    def pending(self) -> bool:
        """Đã nghi ngờ 1 lần, cần kiểm tra lại ngay."""
        return self.first_seen is not None and not self.confirmed

    def feed(self, verdict: Verdict, now: float) -> bool:
        if verdict is Verdict.STRANGER:
            if self.confirmed:
                self._last = now
            elif self._last is not None and now - self._last <= self.window:
                self.confirmed = True
                self._last = now
            else:
                self.first_seen = now
                self._last = now
        elif self.confirmed and verdict is not Verdict.OWNER:
            # Đã xác nhận người lạ: chỉ thấy lại chủ máy mới gỡ (người lạ quay đi vẫn là người lạ).
            pass
        else:
            self.reset()
        return self.confirmed

    def expire(self, now: float) -> None:
        """Nghi ngờ lần đầu quá hạn mà chưa kiểm tra lại thì bỏ."""
        if self.pending and self._last is not None and now - self._last > self.window:
            self.reset()

    def reset(self) -> None:
        self.first_seen = None
        self._last = None
        self.confirmed = False


class Status(enum.Enum):
    PRESENT = "present"
    WARNING = "warning"
    LOCK = "lock"


class PresenceMonitor:
    def __init__(self, lock_seconds: float, warn_seconds: float, warn_before_lock: float, now: float):
        self.lock_seconds = lock_seconds
        self.warn_seconds = warn_seconds
        self.warn_before_lock = warn_before_lock
        self.last_present = now
        self.stranger = False
        self._warned = False

    def configure(self, lock_seconds: float, warn_seconds: float, warn_before_lock: float) -> None:
        self.lock_seconds, self.warn_seconds, self.warn_before_lock = lock_seconds, warn_seconds, warn_before_lock

    def reset(self, now: float) -> None:
        self.last_present = now
        self.stranger = False
        self._warned = False

    def mark_present(self, now: float) -> None:
        self.stranger = False
        if now > self.last_present:
            self.last_present = now
        self._warned = False

    def note_input(self, last_input: float) -> None:
        """Thao tác bàn phím/chuột là bằng chứng có mặt (trừ khi đã xác nhận người lạ)."""
        if not self.stranger and last_input > self.last_present:
            self.last_present = last_input
            self._warned = False

    def mark_stranger(self, first_seen: float) -> None:
        self.stranger = True
        self.last_present = min(self.last_present, first_seen)

    def absent_for(self, now: float) -> float:
        return max(0.0, now - self.last_present)

    def status(self, now: float, observed_since: float | None) -> Status:
        """observed_since: thời điểm camera sẵn sàng (None = không quan sát được -> không khóa)."""
        absent = self.absent_for(now)
        if absent >= self.lock_seconds and observed_since is not None \
                and now - observed_since >= MIN_OBSERVE_BEFORE_LOCK:
            return Status.LOCK
        if absent >= self.warn_seconds:
            return Status.WARNING
        return Status.PRESENT

    def should_warn(self, now: float, observed_since: float | None) -> bool:
        """True đúng một lần mỗi đợt vắng, khi còn <= warn_before_lock giây trước khi khóa."""
        if self._warned or observed_since is None or self.warn_before_lock <= 0:
            return False
        if self.lock_seconds - self.absent_for(now) <= self.warn_before_lock:
            self._warned = True
            return True
        return False

    def seconds_left(self, now: float) -> float:
        return max(0.0, self.lock_seconds - self.absent_for(now))


class IdleLock:
    """Khóa sau N phút không gõ phím/di chuột (dù camera vẫn thấy bạn), báo trước 15s."""

    def __init__(self, minutes: float, warn_seconds: float = 15):
        self.minutes = minutes
        self.warn_seconds = warn_seconds
        self._warned_for: float | None = None

    @property
    def enabled(self) -> bool:
        return self.minutes > 0

    def check(self, idle_seconds: float, last_input: float) -> str | None:
        """'lock', 'warn' (một lần mỗi đợt) hoặc None."""
        if not self.enabled:
            return None
        limit = self.minutes * 60
        if idle_seconds >= limit:
            return "lock"
        if idle_seconds >= limit - self.warn_seconds and self._warned_for != last_input:
            self._warned_for = last_input
            return "warn"
        return None


class CameraPolicy:
    """Quyết định khi nào camera bật.

    - continuous: luôn bật.
    - on_demand: bật khi ngừng thao tác >= idle_on giây, khi tới lần kiểm tra định kỳ (~period ±20%),
      hoặc khi đang nghi ngờ / đã xác nhận người lạ. Đã bật thì giữ tối thiểu 5s.
    """

    def __init__(self, mode: str, idle_on: float, period_minutes: float, now: float,
                 rng: random.Random | None = None):
        self.mode = mode
        self.idle_on = idle_on
        self.period = period_minutes * 60.0
        self.rng = rng or random.Random()
        self.check_requested = False
        self.next_check = self._schedule(now)

    def configure(self, mode: str, idle_on: float, period_minutes: float, now: float) -> None:
        changed = period_minutes * 60.0 != self.period
        self.mode, self.idle_on, self.period = mode, idle_on, period_minutes * 60.0
        if changed:
            self.next_check = self._schedule(now)

    def _schedule(self, now: float) -> float | None:
        if self.period <= 0:
            return None
        return now + self.period * self.rng.uniform(0.8, 1.2)

    def want_camera(self, now: float, idle_seconds: float, stranger_active: bool,
                    camera_opened_at: float | None) -> bool:
        if self.mode == "continuous":
            return True
        if self.next_check is not None and now >= self.next_check:
            self.check_requested = True
            self.next_check = self._schedule(now)
        if idle_seconds >= self.idle_on or self.check_requested or stranger_active:
            return True
        if camera_opened_at is not None and now - camera_opened_at < CAMERA_MIN_ON:
            return True
        return False

    def check_done(self) -> None:
        self.check_requested = False

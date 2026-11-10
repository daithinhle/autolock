"""Thư viện khuôn mặt chủ máy: 24 mẫu đăng ký + tối đa 150 mẫu tự học, và bám theo khuôn mặt.

Chỉ lưu vector đặc trưng (owner.npz). Ảnh mặt thu nhỏ của mẫu tự học chỉ được lưu khi người dùng bật.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

import vision

log = logging.getLogger(__name__)

ENROLL_SAMPLES = 24
LEARN_MAX = 150
LEARN_MAX_PER_DAY = 30
LEARN_MIN_INTERVAL = 20.0
LEARN_BELOW = 0.55           # chỉ học khi điểm < 0.55 (góc chưa có trong hồ sơ)
ANCHOR_MIN = 0.30            # chống trôi: mẫu học phải giống bộ gốc >= 0.30
TRACK_START = 0.50           # nhận ra chắc chắn -> bắt đầu bám theo
TRACK_GAP = 2.0
TRACK_GAP_INPUT = 5.0
TRACK_MIN_IOU = 0.2


class OwnerLibrary:
    def __init__(self, enrolled: np.ndarray | None = None):
        self.enrolled = np.zeros((0, 128), np.float32) if enrolled is None else _as_matrix(enrolled)
        self.learned = np.zeros((0, 128), np.float32)
        self.learned_ts = np.zeros((0,), np.float64)
        self.learned_ids: list[str] = []
        self.learn_day = ""
        self.learn_day_count = 0
        self.last_learn_ts = 0.0
        self.dropped_ids: list[str] = []   # mẫu cũ bị bỏ ở lần add_learned gần nhất
        self.path: Path | None = None
        self.mtime: float | None = None

    # ---------- lưu / tải ----------
    @classmethod
    def load(cls, path: Path) -> "OwnerLibrary | None":
        try:
            with np.load(path, allow_pickle=False) as z:
                lib = cls(z["enrolled"])
                if "learned" in z.files and len(z["learned"]):
                    lib.learned = _as_matrix(z["learned"])
                    lib.learned_ts = np.asarray(z["learned_ts"], np.float64).reshape(-1)
                    lib.learned_ids = [str(s) for s in z["learned_ids"]]
                    n = min(len(lib.learned), len(lib.learned_ts), len(lib.learned_ids))
                    lib.learned, lib.learned_ts, lib.learned_ids = lib.learned[:n], lib.learned_ts[:n], lib.learned_ids[:n]
                if "learn_day" in z.files:
                    lib.learn_day = str(z["learn_day"])
                    lib.learn_day_count = int(z["learn_day_count"])
                if len(lib.learned_ts):
                    lib.last_learn_ts = float(lib.learned_ts.max())
        except FileNotFoundError:
            return None
        except Exception as e:  # file hỏng
            log.warning("Không đọc được %s: %s", path, e)
            return None
        if len(lib.enrolled) == 0:
            return None
        lib.path = Path(path)
        try:
            lib.mtime = os.stat(path).st_mtime
        except OSError:
            pass
        return lib

    def save(self, path: Path | None = None) -> None:
        path = Path(path or self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as f:
            np.savez(f, enrolled=self.enrolled, learned=self.learned, learned_ts=self.learned_ts,
                     learned_ids=np.array(self.learned_ids, dtype="<U64"),
                     learn_day=np.array(self.learn_day), learn_day_count=np.array(self.learn_day_count))
        os.replace(tmp, path)
        self.path = path
        try:
            self.mtime = os.stat(path).st_mtime
        except OSError:
            pass

    # ---------- so khớp ----------
    @property
    def all_features(self) -> np.ndarray:
        if len(self.learned):
            return np.vstack([self.enrolled, self.learned])
        return self.enrolled

    def similarity(self, feature: np.ndarray) -> float:
        """Độ giống cao nhất với toàn bộ thư viện."""
        return float(np.max(self.all_features @ feature))

    def base_similarity(self, feature: np.ndarray) -> float:
        """Độ giống cao nhất với 24 mẫu đăng ký gốc."""
        return float(np.max(self.enrolled @ feature))

    def learned_base_scores(self) -> np.ndarray:
        if not len(self.learned):
            return np.zeros((0,), np.float32)
        return np.max(self.learned @ self.enrolled.T, axis=1)

    # ---------- tự học ----------
    def can_learn(self, now: float) -> bool:
        if now - self.last_learn_ts < LEARN_MIN_INTERVAL:
            return False
        if self.learn_day == _day(now) and self.learn_day_count >= LEARN_MAX_PER_DAY:
            return False
        return True

    def add_learned(self, feature: np.ndarray, now: float | None = None) -> str | None:
        """Thêm mẫu tự học nếu qua giới hạn tốc độ và chống trôi. Trả về id mẫu hoặc None."""
        now = time.time() if now is None else now
        feature = vision.normalize(feature)
        if not self.can_learn(now):
            return None
        if self.base_similarity(feature) < ANCHOR_MIN:
            return None
        sid = uuid.uuid4().hex[:12]
        self.learned = np.vstack([self.learned, feature[None]]).astype(np.float32)
        self.learned_ts = np.append(self.learned_ts, now)
        self.learned_ids.append(sid)
        day = _day(now)
        if self.learn_day != day:
            self.learn_day, self.learn_day_count = day, 0
        self.learn_day_count += 1
        self.last_learn_ts = now
        dropped = []
        while len(self.learned) > LEARN_MAX:
            oldest = int(np.argmin(self.learned_ts))
            dropped.append(self.learned_ids[oldest])
            self._remove_index(oldest)
        self.dropped_ids = dropped
        return sid

    def remove_learned(self, ids) -> int:
        ids = set(ids)
        idx = [i for i, s in enumerate(self.learned_ids) if s in ids]
        for i in sorted(idx, reverse=True):
            self._remove_index(i)
        return len(idx)

    def clear_learned(self) -> None:
        self.learned = np.zeros((0, 128), np.float32)
        self.learned_ts = np.zeros((0,), np.float64)
        self.learned_ids = []

    def _remove_index(self, i: int) -> None:
        self.learned = np.delete(self.learned, i, axis=0)
        self.learned_ts = np.delete(self.learned_ts, i)
        del self.learned_ids[i]


def _as_matrix(a) -> np.ndarray:
    m = np.asarray(a, np.float32)
    if m.ndim == 1:
        m = m[None]
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return (m / norms).astype(np.float32)


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def thumbnail_path(learned_dir: Path, sid: str) -> Path:
    return learned_dir / f"{sid}.jpg"


def delete_thumbnails(learned_dir: Path, ids=None) -> None:
    """Xóa ảnh thu nhỏ (ids=None: xóa hết)."""
    if not learned_dir.is_dir():
        return
    targets = learned_dir.glob("*.jpg") if ids is None else (thumbnail_path(learned_dir, s) for s in ids)
    for p in targets:
        try:
            p.unlink()
        except OSError:
            pass


def prune_thumbnails(learned_dir: Path, keep_ids) -> None:
    """Xóa ảnh thu nhỏ không còn mẫu tương ứng."""
    if not learned_dir.is_dir():
        return
    keep = set(keep_ids)
    for p in learned_dir.glob("*.jpg"):
        if p.stem not in keep:
            try:
                p.unlink()
            except OSError:
                pass


@dataclass
class _Track:
    box: tuple
    ts: float


class OwnerTracker:
    """Bám theo khuôn mặt chủ máy giữa các frame.

    Sau một lần nhận ra chắc chắn (>= 0.5), cùng khuôn mặt đó (chỉ 1 mặt trong hình, khung mặt chồng lên vị trí cũ,
    cách nhau <= 2s, hoặc <= 5s khi bàn phím/chuột vẫn được dùng) vẫn là chủ máy dù điểm tụt.
    """

    def __init__(self):
        self._track: _Track | None = None

    def reset(self) -> None:
        self._track = None

    @property
    def active(self) -> bool:
        return self._track is not None

    def update(self, faces: list, now: float, input_recent: bool) -> bool:
        """Cập nhật với danh sách Face (đã có similarity). Trả True nếu mặt duy nhất đang được bám theo.

        Gọi sau mỗi lần phân tích frame; nếu True thì faces[0] được coi là chủ máy.
        """
        if self._track is not None:
            gap = TRACK_GAP_INPUT if input_recent else TRACK_GAP
            if now - self._track.ts > gap:
                self._track = None
        if len(faces) != 1:
            # Không mặt: giữ chuỗi chờ hết hạn. Nhiều mặt: không bám (cắt chuỗi).
            if len(faces) > 1:
                self._track = None
            return False
        face = faces[0]
        sim = face.similarity if face.similarity is not None else 0.0
        if sim >= TRACK_START:
            self._track = _Track(face.box, now)
            return True
        if self._track is not None and vision.iou(self._track.box, face.box) >= TRACK_MIN_IOU:
            self._track = _Track(face.box, now)
            return True
        self._track = None
        return False

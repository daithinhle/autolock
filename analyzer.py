"""Phân tích một frame -> Verdict, kèm bám theo và tự học mẫu khuôn mặt chủ máy."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import owner as owner_mod
import paths
import vision
from config import Config
from presence import FaceInfo, Verdict, classify

log = logging.getLogger(__name__)

PERSON_REUSE = 1.5


@dataclass
class Analysis:
    verdict: Verdict
    faces: list = field(default_factory=list)
    person: bool | None = None
    best_similarity: float | None = None
    image: np.ndarray | None = None          # frame đã tăng sáng (dùng để chụp ảnh người lạ)

    @property
    def face_boxes(self):
        return [f.box for f in self.faces]


class Analyzer:
    def __init__(self, cfg: Config, engine: vision.FaceEngine, library: owner_mod.OwnerLibrary | None,
                 person_detector_factory=None, learned_dir: Path | None = None):
        self.cfg = cfg
        self.engine = engine
        self.library = library
        self._person_factory = person_detector_factory
        self._person: vision.PersonDetector | None = None
        self.tracker = owner_mod.OwnerTracker()
        self.learned_dir = learned_dir or paths.learned_dir()
        self._thumb_private: bool | None = None
        self._person_seen_at: float | None = None

    def set_library(self, library: owner_mod.OwnerLibrary | None) -> None:
        self.library = library
        self.tracker.reset()

    def _person_detector(self) -> vision.PersonDetector | None:
        if self._person is None and self._person_factory is not None:
            try:
                self._person = self._person_factory()
            except Exception as e:
                log.error("Không nạp được model phát hiện người: %s", e)
                self._person_factory = None
        return self._person

    def _detect_person(self, img: np.ndarray, now: float) -> bool | None:
        """Kết quả "có người" được dùng lại tối đa PERSON_REUSE giây (model nặng nhất)."""
        if self._person_seen_at is not None and now - self._person_seen_at < PERSON_REUSE:
            return True
        det = self._person_detector()
        if det is None:
            return None
        found = det.has_big_person(img)
        self._person_seen_at = now if found else None
        return found

    def analyze(self, frame: np.ndarray, now: float, input_recent: bool) -> Analysis:
        cfg = self.cfg
        img = vision.enhance(frame)
        faces = self.engine.detect(img)
        use_owner = cfg.use_owner and self.library is not None
        if use_owner:
            for f in faces:
                feat = self.engine.describe(img, f)
                f.similarity = self.library.similarity(feat)
        else:
            for f in faces:
                # Vẫn cần độ nét cho cổng chất lượng; không có thư viện thì không kết luận người lạ.
                crop = self.engine.aligned(img, f)
                f.sharpness = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

        tracked = self.tracker.update(faces, now, input_recent) if use_owner else False
        infos = [FaceInfo(similarity=f.similarity, clear=vision.is_clear(f, img.shape),
                          tracked=tracked and i == 0) for i, f in enumerate(faces)]
        verdict = classify(infos, False, input_recent, cfg.owner_threshold, cfg.stranger_threshold)
        person = None
        if verdict is Verdict.ABSENT and cfg.use_person:
            person = self._detect_person(img, now)
            if person:
                verdict = Verdict.PRESENT

        if tracked and cfg.learn_enabled and use_owner:
            self._maybe_learn(img, faces[0], now)

        best = max((f.similarity for f in faces if f.similarity is not None), default=None)
        return Analysis(verdict=verdict, faces=faces, person=person, best_similarity=best, image=img)

    def _maybe_learn(self, img: np.ndarray, face: vision.Face, now: float) -> None:
        lib = self.library
        if face.similarity is None or face.similarity >= owner_mod.LEARN_BELOW or face.feature is None:
            return
        if not vision.is_learnable(face) or not lib.can_learn(now):
            return
        sid = lib.add_learned(face.feature, now)
        if sid is None:
            return
        try:
            lib.save()
        except OSError as e:
            log.warning("Không lưu được mẫu tự học: %s", e)
            return
        log.info("Học mẫu mới (điểm %.2f, tổng %d mẫu tự học)", face.similarity, len(lib.learned))
        if lib.dropped_ids:
            owner_mod.delete_thumbnails(self.learned_dir, lib.dropped_ids)
        if self.cfg.learn_thumbnails:
            if self._thumb_private is None:
                self._thumb_private = paths.is_private_local(self.learned_dir.parent)
                if not self._thumb_private:
                    log.warning("Thư mục dữ liệu không riêng tư cục bộ, không lưu ảnh mặt thu nhỏ")
            if self._thumb_private:
                try:
                    self.learned_dir.mkdir(parents=True, exist_ok=True)
                    crop = self.engine.aligned(img, face)
                    vision.imwrite(owner_mod.thumbnail_path(self.learned_dir, sid), crop)
                except Exception as e:
                    log.warning("Không lưu được ảnh thu nhỏ: %s", e)

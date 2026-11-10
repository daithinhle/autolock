"""Phát hiện/nhận diện khuôn mặt (YuNet + SFace) và phát hiện người (YOLOX), 100% local."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import paths

log = logging.getLogger(__name__)

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"
YOLOX_FILE = "object_detection_yolox_2022nov.onnx"

# Cổng "mặt đủ rõ để kết luận người lạ".
CLEAR_MIN_WIDTH = 64
CLEAR_MIN_SCORE = 0.8
# Cổng chất lượng khi học mẫu mới.
LEARN_MIN_WIDTH = 80
LEARN_MIN_SCORE = 0.9
# Độ nét: phương sai Laplacian trên ảnh mặt đã căn chỉnh 112x112.
SHARP_MIN = 25.0
# Gần chính diện.
FRONTAL_MAX_YAW = 0.30
FRONTAL_PITCH_RANGE = (0.25, 0.80)
EDGE_MARGIN = 2

DARK_MEAN = 70.0           # độ sáng trung bình dưới mức này thì tăng sáng
PERSON_MIN_HEIGHT = 0.30   # người "đủ lớn": cao >= 30% khung hình
PERSON_MIN_AREA = 0.06     # hoặc chiếm >= 6% diện tích
PERSON_SCORE = 0.5


def configure_cv() -> None:
    cv2.setNumThreads(1)
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass
    try:
        cv2.ocl.setUseOpenCL(False)
    except Exception:
        pass


@dataclass
class Face:
    box: tuple[float, float, float, float]   # x, y, w, h
    landmarks: np.ndarray                    # 5x2: mắt phải, mắt trái, mũi, miệng phải, miệng trái
    score: float
    row: np.ndarray = field(repr=False)      # hàng gốc của YuNet (15 giá trị)
    feature: np.ndarray | None = field(default=None, repr=False)
    sharpness: float = 0.0
    similarity: float | None = None          # độ giống chủ máy (cao nhất trên thư viện)

    @property
    def width(self) -> float:
        return self.box[2]


def head_pose(landmarks: np.ndarray) -> tuple[float, float]:
    """(yaw, pitch) chuẩn hóa theo khoảng cách hai mắt.

    yaw  = độ lệch ngang của mũi so với trung điểm hai mắt (dương = mũi lệch sang phải ảnh).
    pitch = vị trí dọc của mũi giữa đường mắt và đường miệng (0 = ngang mắt, 1 = ngang miệng).
    """
    re, le, nose, mr, ml = [np.asarray(p, dtype=np.float64) for p in landmarks]
    eye_mid = (re + le) / 2.0
    mouth_mid = (mr + ml) / 2.0
    eye_dist = float(np.linalg.norm(le - re)) or 1.0
    yaw = float((nose[0] - eye_mid[0]) / eye_dist)
    span = float(mouth_mid[1] - eye_mid[1])
    pitch = float((nose[1] - eye_mid[1]) / span) if abs(span) > 1e-6 else 0.5
    return yaw, pitch


def is_frontal(landmarks: np.ndarray) -> bool:
    yaw, pitch = head_pose(landmarks)
    return abs(yaw) <= FRONTAL_MAX_YAW and FRONTAL_PITCH_RANGE[0] <= pitch <= FRONTAL_PITCH_RANGE[1]


def touches_edge(box, frame_shape, margin: int = EDGE_MARGIN) -> bool:
    x, y, w, h = box
    fh, fw = frame_shape[:2]
    return x < margin or y < margin or x + w > fw - margin or y + h > fh - margin


def is_clear(face: Face, frame_shape) -> bool:
    """Mặt đủ rõ để kết luận là người lạ."""
    return (face.width >= CLEAR_MIN_WIDTH
            and face.score >= CLEAR_MIN_SCORE
            and is_frontal(face.landmarks)
            and face.sharpness >= SHARP_MIN
            and not touches_edge(face.box, frame_shape))


def is_learnable(face: Face) -> bool:
    return face.width >= LEARN_MIN_WIDTH and face.score >= LEARN_MIN_SCORE and face.sharpness >= SHARP_MIN


def enhance(frame: np.ndarray) -> np.ndarray:
    """Tăng sáng ảnh tối (CLAHE trên kênh độ sáng + gamma)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    if mean >= DARK_MEAN:
        return frame
    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    y = ycrcb[:, :, 0]
    gamma = 0.5 if mean < 35 else 0.7
    lut = (np.power(np.arange(256) / 255.0, gamma) * 255.0).clip(0, 255).astype(np.uint8)
    y = cv2.LUT(y, lut)
    y = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(y)
    ycrcb[:, :, 0] = y
    return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class FaceEngine:
    def __init__(self, models: Path | None = None, score_threshold: float = 0.6):
        models = models or paths.models_dir()
        self.detector = cv2.FaceDetectorYN.create(str(models / YUNET_FILE), "", (320, 320),
                                                  score_threshold, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(str(models / SFACE_FILE), "")
        self._size = (320, 320)

    def detect(self, frame: np.ndarray) -> list[Face]:
        h, w = frame.shape[:2]
        if (w, h) != self._size:
            self.detector.setInputSize((w, h))
            self._size = (w, h)
        _, rows = self.detector.detect(frame)
        faces: list[Face] = []
        if rows is None:
            return faces
        for r in rows:
            faces.append(Face(box=(float(r[0]), float(r[1]), float(r[2]), float(r[3])),
                              landmarks=r[4:14].reshape(5, 2).copy(), score=float(r[14]), row=r.copy()))
        return faces

    def aligned(self, frame: np.ndarray, face: Face) -> np.ndarray:
        return self.recognizer.alignCrop(frame, face.row)

    def describe(self, frame: np.ndarray, face: Face) -> np.ndarray:
        """Tính vector đặc trưng (chuẩn hóa) + độ nét cho khuôn mặt."""
        crop = self.aligned(frame, face)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        face.sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        face.feature = normalize(self.recognizer.feature(crop))
        return face.feature


class PersonDetector:
    """YOLOX-S (COCO), chỉ lấy lớp người."""

    INPUT = 640
    STRIDES = (8, 16, 32)

    def __init__(self, models: Path | None = None):
        models = models or paths.models_dir()
        self.net = cv2.dnn.readNet(str(models / YOLOX_FILE))
        grids, strides = [], []
        for s in self.STRIDES:
            n = self.INPUT // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), s))
        self._grids = np.concatenate(grids, 0).astype(np.float32)
        self._strides = np.concatenate(strides, 0).astype(np.float32)

    def detect(self, frame: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        """Danh sách (x, y, w, h, score) của người trong khung hình."""
        h, w = frame.shape[:2]
        ratio = min(self.INPUT / h, self.INPUT / w)
        rh, rw = int(h * ratio), int(w * ratio)
        padded = np.full((self.INPUT, self.INPUT, 3), 114, dtype=np.uint8)
        padded[:rh, :rw] = cv2.resize(frame, (rw, rh), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        blob = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None].astype(np.float32))
        self.net.setInput(blob)
        out = self.net.forward()[0]
        boxes_xy = (out[:, :2] + self._grids) * self._strides
        boxes_wh = np.exp(out[:, 2:4]) * self._strides
        scores = out[:, 4] * out[:, 5]  # objectness * xác suất lớp "person" (0)
        keep = scores >= PERSON_SCORE
        if not np.any(keep):
            return []
        xy, wh, sc = boxes_xy[keep], boxes_wh[keep], scores[keep]
        rects = [[float(cx - bw / 2) / ratio, float(cy - bh / 2) / ratio, float(bw) / ratio, float(bh) / ratio]
                 for (cx, cy), (bw, bh) in zip(xy, wh)]
        idx = cv2.dnn.NMSBoxes(rects, sc.tolist(), PERSON_SCORE, 0.45)
        return [(*rects[i], float(sc[i])) for i in np.array(idx).reshape(-1)]

    def has_big_person(self, frame: np.ndarray) -> bool:
        fh, fw = frame.shape[:2]
        for x, y, w, h, _ in self.detect(frame):
            if h >= PERSON_MIN_HEIGHT * fh or (w * h) >= PERSON_MIN_AREA * fw * fh:
                return True
        return False


def imwrite(path: Path, img: np.ndarray, quality: int = 90) -> None:
    """cv2.imwrite không xử lý được đường dẫn Unicode trên Windows."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise OSError("Không mã hóa được ảnh")
    Path(path).write_bytes(buf.tobytes())


def imread(path: Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0

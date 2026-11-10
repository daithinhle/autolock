import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Không bao giờ ghi vào %LOCALAPPDATA% khi chạy test."""
    d = tmp_path / "data"
    monkeypatch.setenv("AUTOLOCK_DATA_DIR", str(d))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    return d


@pytest.fixture
def rng():
    return np.random.default_rng(1234)


def unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


def near(base, rng, noise):
    """Vector gần `base` (độ giống giảm dần theo noise)."""
    return unit(base + rng.normal(0, noise, base.shape).astype(np.float32))


@pytest.fixture
def owner_vectors(rng):
    base = unit(rng.normal(size=128))
    enrolled = np.stack([near(base, rng, 0.03) for _ in range(24)])
    return base, enrolled

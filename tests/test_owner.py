from datetime import datetime

import numpy as np

import owner
import paths
from conftest import near, unit


class F:
    """Face giả cho OwnerTracker."""

    def __init__(self, box, sim):
        self.box, self.similarity = box, sim


def test_save_load_roundtrip(owner_vectors, rng):
    base, enrolled = owner_vectors
    lib = owner.OwnerLibrary(enrolled)
    lib.add_learned(near(base, rng, 0.05), now=1000)
    lib.save(paths.owner_path())
    lib2 = owner.OwnerLibrary.load(paths.owner_path())
    assert lib2.enrolled.shape == (24, 128)
    assert len(lib2.learned) == 1 and lib2.learned_ids == lib.learned_ids
    assert lib2.last_learn_ts == 1000
    assert abs(lib2.similarity(base) - lib.similarity(base)) < 1e-6


def test_load_missing_or_corrupt(tmp_path):
    assert owner.OwnerLibrary.load(tmp_path / "x.npz") is None
    p = tmp_path / "bad.npz"
    p.write_bytes(b"garbage")
    assert owner.OwnerLibrary.load(p) is None


def test_learning_rate_limits(owner_vectors, rng):
    base, enrolled = owner_vectors
    lib = owner.OwnerLibrary(enrolled)
    t = 1_700_000_000.0
    assert lib.add_learned(near(base, rng, 0.05), t)
    assert lib.add_learned(near(base, rng, 0.05), t + 10) is None      # < 20s
    assert lib.add_learned(near(base, rng, 0.05), t + 20)
    # Giới hạn 30 mẫu/ngày.
    lib2 = owner.OwnerLibrary(enrolled)
    morning = datetime(2026, 11, 10, 8, 0).timestamp()
    added = sum(lib2.add_learned(near(base, rng, 0.05), morning + i * 21) is not None for i in range(40))
    assert added == owner.LEARN_MAX_PER_DAY
    # Ngày mới thì học tiếp.
    assert lib2.add_learned(near(base, rng, 0.05), morning + 86400)


def test_learning_cap_drops_oldest(owner_vectors, rng):
    base, enrolled = owner_vectors
    lib = owner.OwnerLibrary(enrolled)
    t = 0.0
    first = None
    for i in range(owner.LEARN_MAX + 5):
        t += 86400 / 30 + 1  # tránh giới hạn ngày
        sid = lib.add_learned(near(base, rng, 0.05), t)
        assert sid
        first = first or sid
    assert len(lib.learned) == owner.LEARN_MAX
    assert first not in lib.learned_ids
    assert len(lib.enrolled) == 24  # mẫu đăng ký không bao giờ bị thay


def test_anti_drift(owner_vectors, rng):
    _, enrolled = owner_vectors
    lib = owner.OwnerLibrary(enrolled)
    stranger = unit(rng.normal(size=128))
    assert lib.base_similarity(stranger) < owner.ANCHOR_MIN
    assert lib.add_learned(stranger, 1000) is None


def test_remove_and_clear(owner_vectors, rng):
    base, enrolled = owner_vectors
    lib = owner.OwnerLibrary(enrolled)
    ids = [lib.add_learned(near(base, rng, 0.05), 1000 + 30 * i) for i in range(3)]
    assert lib.remove_learned([ids[1]]) == 1
    assert lib.learned_ids == [ids[0], ids[2]]
    assert len(lib.learned_base_scores()) == 2
    lib.clear_learned()
    assert len(lib.learned) == 0


def test_tracker_follows_single_face():
    tr = owner.OwnerTracker()
    assert tr.update([F((100, 100, 80, 80), 0.6)], 0, False)
    assert tr.update([F((105, 102, 80, 80), 0.2)], 1.5, False)      # điểm tụt, vẫn là chủ máy
    assert not tr.update([F((105, 102, 80, 80), 0.2)], 4.0, False)  # cách > 2s


def test_tracker_gap_longer_with_input():
    tr = owner.OwnerTracker()
    tr.update([F((100, 100, 80, 80), 0.6)], 0, True)
    assert tr.update([F((100, 100, 80, 80), 0.2)], 4.5, True)


def test_tracker_breaks_on_two_faces_or_jump():
    tr = owner.OwnerTracker()
    tr.update([F((100, 100, 80, 80), 0.6)], 0, False)
    assert not tr.update([F((100, 100, 80, 80), 0.2), F((300, 100, 80, 80), 0.1)], 0.5, False)
    assert not tr.update([F((100, 100, 80, 80), 0.2)], 1.0, False)
    tr.update([F((100, 100, 80, 80), 0.6)], 2, False)
    assert not tr.update([F((400, 100, 80, 80), 0.2)], 2.5, False)   # mặt khác vị trí


def test_thumbnail_helpers(tmp_path):
    d = tmp_path / "learned"
    d.mkdir()
    for s in ("a", "b", "c"):
        (d / f"{s}.jpg").write_bytes(b"x")
    owner.prune_thumbnails(d, ["a", "b"])
    assert sorted(p.stem for p in d.glob("*.jpg")) == ["a", "b"]
    owner.delete_thumbnails(d, ["a"])
    assert [p.stem for p in d.glob("*.jpg")] == ["b"]
    owner.delete_thumbnails(d)
    assert not list(d.glob("*.jpg"))


def test_filter_learned(owner_vectors, rng):
    import settings_ui
    base, enrolled = owner_vectors
    lib = owner.OwnerLibrary(enrolled)
    good = lib.add_learned(near(base, rng, 0.05), 1000)
    # Mẫu "trôi" (dựng tay, bỏ qua chống trôi) không khớp khuôn mặt vừa quét.
    odd = unit(rng.normal(size=128))
    lib.learned = np.vstack([lib.learned, odd[None]])
    lib.learned_ts = np.append(lib.learned_ts, 2000)
    lib.learned_ids.append("odd")
    fresh = np.stack([near(base, rng, 0.03) for _ in range(5)])
    assert settings_ui.filter_learned(lib, fresh) == ["odd"]
    assert good not in settings_ui.filter_learned(lib, fresh)

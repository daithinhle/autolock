import random

from presence import (CameraPolicy, FaceInfo, IdleLock, PresenceMonitor, Status, StrangerConfirmer, Verdict,
                      classify)

CLEAR = dict(clear=True)


def test_owner_face_wins():
    faces = [FaceInfo(0.1, True), FaceInfo(0.45, True)]
    assert classify(faces, False, False) is Verdict.OWNER


def test_tracked_face_is_owner_even_with_low_score():
    assert classify([FaceInfo(0.2, True, tracked=True)], False, False) is Verdict.OWNER


def test_stranger_requires_all_faces_clear():
    assert classify([FaceInfo(0.1, True)], False, True) is Verdict.STRANGER
    # Một mặt không rõ -> "không rõ ai" -> dựa vào người / bàn phím.
    assert classify([FaceInfo(0.1, True), FaceInfo(0.1, False)], False, True) is Verdict.PRESENT
    assert classify([FaceInfo(0.1, False)], False, False) is Verdict.ABSENT


def test_ambiguous_score_falls_back():
    assert classify([FaceInfo(0.3, True)], True, False) is Verdict.PRESENT
    assert classify([FaceInfo(0.3, True)], False, False) is Verdict.ABSENT


def test_no_owner_library_never_stranger():
    assert classify([FaceInfo(None, True)], False, True) is Verdict.PRESENT


def test_no_face_person_or_input():
    assert classify([], True, False) is Verdict.PRESENT
    assert classify([], False, True) is Verdict.PRESENT
    assert classify([], False, False) is Verdict.ABSENT


def test_stranger_needs_two_checks_within_3s():
    c = StrangerConfirmer()
    assert not c.feed(Verdict.STRANGER, 0.0)
    assert c.pending
    assert not c.feed(Verdict.STRANGER, 3.5)   # quá 3s -> tính lại từ đầu
    assert c.feed(Verdict.STRANGER, 5.0)
    assert c.first_seen == 3.5


def test_stranger_interrupted_by_other_verdict():
    c = StrangerConfirmer()
    c.feed(Verdict.STRANGER, 0)
    c.feed(Verdict.PRESENT, 0.5)
    assert not c.pending
    assert not c.feed(Verdict.STRANGER, 1.0)


def test_confirmed_stranger_sticky_until_owner():
    c = StrangerConfirmer()
    c.feed(Verdict.STRANGER, 0)
    c.feed(Verdict.STRANGER, 1)
    assert c.feed(Verdict.PRESENT, 2)       # quay mặt đi vẫn là người lạ
    assert not c.feed(Verdict.OWNER, 3)


def test_pending_expires():
    c = StrangerConfirmer()
    c.feed(Verdict.STRANGER, 0)
    c.expire(2)
    assert c.pending
    c.expire(4)
    assert not c.pending


def test_lock_after_absence_with_min_observation():
    m = PresenceMonitor(lock_seconds=12, warn_seconds=3, warn_before_lock=5, now=0)
    assert m.status(2, observed_since=0) is Status.PRESENT
    assert m.status(3, observed_since=0) is Status.WARNING
    assert m.status(12, observed_since=0) is Status.LOCK
    # Camera vừa sẵn sàng (chế độ Khi cần): phải quan sát ít nhất 4s.
    assert m.status(12, observed_since=10) is Status.WARNING
    assert m.status(14, observed_since=10) is Status.LOCK
    # Không quan sát được (camera lỗi) thì không bao giờ khóa.
    assert m.status(100, observed_since=None) is Status.WARNING


def test_input_counts_as_presence_unless_stranger():
    m = PresenceMonitor(12, 3, 5, now=0)
    m.note_input(10)
    assert m.status(15, 0) is Status.WARNING
    assert m.status(21, 0) is not Status.LOCK
    m.mark_stranger(first_seen=11)
    m.note_input(20)   # người lạ gõ phím
    assert m.status(23, 0) is Status.LOCK


def test_stranger_clock_starts_no_later_than_first_sighting():
    m = PresenceMonitor(12, 3, 5, now=0)
    m.note_input(30)
    m.mark_stranger(first_seen=25)
    assert m.last_present == 25


def test_warn_once_per_absence():
    m = PresenceMonitor(12, 3, 5, now=0)
    assert not m.should_warn(6, 0)
    assert m.should_warn(7, 0)
    assert not m.should_warn(8, 0)
    m.mark_present(9)
    assert m.should_warn(16, 0)


def test_idle_lock():
    il = IdleLock(minutes=0)
    assert il.check(10_000, 0) is None
    il = IdleLock(minutes=10, warn_seconds=15)
    assert il.check(584, 0) is None
    assert il.check(585, 0) == "warn"
    assert il.check(590, 0) is None
    assert il.check(600, 0) == "lock"
    assert il.check(585, 100) == "warn"   # đợt mới


def test_camera_policy_continuous_always_on():
    p = CameraPolicy("continuous", 8, 3, now=0)
    assert p.want_camera(0, 0, False, None)


def test_camera_policy_on_demand():
    p = CameraPolicy("on_demand", 8, 0, now=0)
    assert not p.want_camera(1, idle_seconds=1, stranger_active=False, camera_opened_at=None)
    assert p.want_camera(9, idle_seconds=8, stranger_active=False, camera_opened_at=None)
    # Đã bật thì giữ tối thiểu 5s.
    assert p.want_camera(12, idle_seconds=0, stranger_active=False, camera_opened_at=9)
    assert not p.want_camera(15, idle_seconds=0, stranger_active=False, camera_opened_at=9)
    assert p.want_camera(15, idle_seconds=0, stranger_active=True, camera_opened_at=None)


def test_camera_policy_periodic_jitter():
    p = CameraPolicy("on_demand", 8, 3, now=0, rng=random.Random(0))
    assert 144 <= p.next_check <= 216
    t = p.next_check
    assert not p.want_camera(t - 1, 0, False, None)
    assert p.want_camera(t, 0, False, None)
    assert p.check_requested
    assert p.want_camera(t + 1, 0, False, None)   # chờ tới khi phân tích xong một frame
    p.check_done()
    assert not p.want_camera(t + 10, 0, False, None)
    assert p.next_check >= t + 144

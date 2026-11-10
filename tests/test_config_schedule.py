import json
from datetime import datetime

import config
import paths
import schedule


def test_defaults_when_missing(tmp_path):
    c = config.load(tmp_path / "nope.json")
    assert c.lock_seconds == 12 and c.owner_threshold == 0.40 and c.stranger_threshold == 0.25
    assert c.idle_lock_minutes == 0 and not c.schedule_enabled
    assert c.schedule_days == [0, 1, 2, 3, 4]


def test_roundtrip_and_clamp(tmp_path):
    p = tmp_path / "config.json"
    c = config.Config(lock_seconds=3, on_demand_idle_seconds=500, periodic_check_minutes=99,
                      strangers_retention_days=0, schedule_days=[6, 1, 1, 9], schedule_end="25:00",
                      camera_mode="weird")
    config.save(c, p)
    c2 = config.load(p)
    assert c2.lock_seconds == 5
    assert c2.on_demand_idle_seconds == 120
    assert c2.periodic_check_minutes == 60
    assert c2.strangers_retention_days == 1
    assert c2.schedule_days == [1, 6]
    assert c2.schedule_end == "24:00"
    assert c2.camera_mode == ""


def test_unknown_keys_and_bad_json(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"lock_seconds": 20, "bogus": 1}), encoding="utf-8")
    assert config.load(p).lock_seconds == 20
    p.write_text("{not json", encoding="utf-8")
    assert config.load(p).lock_seconds == 12


def test_effective_camera_mode():
    c = config.Config()
    assert c.effective_camera_mode(has_battery=True) == "on_demand"
    assert c.effective_camera_mode(has_battery=False) == "continuous"
    c.camera_mode = "continuous"
    assert c.effective_camera_mode(has_battery=True) == "continuous"


def test_config_path_is_isolated(isolated_data_dir):
    assert paths.config_path().parent == isolated_data_dir


def test_parse_time():
    assert config.parse_time("00:00") == 0
    assert config.parse_time("24:00") == 1440
    assert config.parse_time("7:30") == 450
    assert config.parse_time("24:01") is None
    assert config.parse_time("12:60") is None
    assert config.parse_time("abc") is None


# 2026-11-09 là Thứ 2.
MON = datetime(2026, 11, 9)


def at(day_offset, h, m=0):
    return MON.replace(day=MON.day + day_offset, hour=h, minute=m)


def test_schedule_whole_day_weekdays():
    days = [0, 1, 2, 3, 4]
    assert schedule.in_window(at(0, 0), days, "00:00", "24:00")
    assert schedule.in_window(at(4, 23, 59), days, "00:00", "24:00")
    assert not schedule.in_window(at(5, 12), days, "00:00", "24:00")   # Thứ 7


def test_schedule_daytime_window():
    days = [0]
    assert not schedule.in_window(at(0, 7, 59), days, "08:00", "17:30")
    assert schedule.in_window(at(0, 8, 0), days, "08:00", "17:30")
    assert not schedule.in_window(at(0, 17, 30), days, "08:00", "17:30")


def test_schedule_overnight_counts_for_start_day():
    days = [4]  # Thứ 6
    assert schedule.in_window(at(4, 23), days, "22:00", "06:00")
    assert schedule.in_window(at(5, 5, 59), days, "22:00", "06:00")    # rạng sáng Thứ 7 thuộc ca Thứ 6
    assert not schedule.in_window(at(5, 6), days, "22:00", "06:00")
    assert not schedule.in_window(at(4, 3), days, "22:00", "06:00")    # rạng sáng Thứ 6 thuộc ca Thứ 5


def test_schedule_disabled_is_always_active():
    c = config.Config(schedule_enabled=False, schedule_days=[])
    assert schedule.is_active(c, at(6, 3))
    c.schedule_enabled = True
    assert not schedule.is_active(c, at(6, 3))

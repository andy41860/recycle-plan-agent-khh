import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "disposal-plan" / "scripts" / "next_pickup.py"
SCHEDULE = json.loads((ROOT / "mcp_recycle" / "schedule.json").read_text(encoding="utf-8"))

spec = importlib.util.spec_from_file_location("next_pickup", SCRIPT)
np = importlib.util.module_from_spec(spec)
spec.loader.exec_module(np)

BOTH = ["資源回收", "一般垃圾"]


def run(now, categories=BOTH, schedule=SCHEDULE):
    return np.compute({"now": now, "schedule": schedule, "categories": categories})["results"]


def with_exceptions(*exceptions):
    s = copy.deepcopy(SCHEDULE)
    s["exceptions"] = list(exceptions)
    return s


def test_before_window_today():
    r = run("2026-10-23T15:34:00+08:00")
    for cat in BOTH:
        assert r[cat] == {"date": "2026-10-23", "weekday": "週五", "start": "18:30", "end": "20:30",
                          "is_today": True, "note": None}


def test_during_window_counts_as_today():
    assert run("2026-10-23T19:00:00+08:00")["資源回收"]["is_today"] is True


def test_after_window_next_day():
    r = run("2026-10-23T21:00:00+08:00")
    assert r["資源回收"]["date"] == "2026-10-27" and r["資源回收"]["weekday"] == "週二"
    assert r["一般垃圾"]["date"] == "2026-10-24" and r["一般垃圾"]["weekday"] == "週六"
    assert r["一般垃圾"]["is_today"] is False


def test_exactly_at_end_is_past():
    assert run("2026-10-23T20:30:00+08:00")["一般垃圾"]["date"] == "2026-10-24"


def test_not_collected_today_wednesday():
    r = run("2026-10-21T10:00:00+08:00", ["一般垃圾"])
    assert r["一般垃圾"]["date"] == "2026-10-22" and r["一般垃圾"]["weekday"] == "週四"


def test_recycling_skips_to_next_tuesday():
    r = run("2026-10-24T21:00:00+08:00", ["資源回收"])
    assert r["資源回收"]["date"] == "2026-10-27"


def test_exception_stops_collection():
    s = with_exceptions({"date": "2026-10-30", "collect": [], "note": "停收"})
    r = run("2026-10-29T21:00:00+08:00", ["一般垃圾"], s)
    assert r["一般垃圾"]["date"] == "2026-10-31"


def test_exception_adds_collection_with_note():
    s = with_exceptions({"date": "2026-10-28", "collect": ["資源回收"], "note": "加收"})
    r = run("2026-10-27T21:00:00+08:00", ["資源回收"], s)
    assert r["資源回收"]["date"] == "2026-10-28"
    assert r["資源回收"]["weekday"] == "週三"
    assert r["資源回收"]["note"] == "加收"


def test_nothing_within_15_days_is_null():
    s = copy.deepcopy(SCHEDULE)
    s["weekly"] = {k: [] for k in s["weekly"]}
    assert run("2026-10-23T10:00:00+08:00", ["資源回收"], s) == {"資源回收": None}


def test_exactly_day_14_found_day_15_not():
    s = copy.deepcopy(SCHEDULE)
    s["weekly"] = {k: [] for k in s["weekly"]}
    s["exceptions"] = [{"date": "2026-11-06", "collect": ["一般垃圾"], "note": ""}]  # d=14
    assert run("2026-10-23T10:00:00+08:00", ["一般垃圾"], s)["一般垃圾"]["date"] == "2026-11-06"
    s["exceptions"] = [{"date": "2026-11-07", "collect": ["一般垃圾"], "note": ""}]  # d=15
    assert run("2026-10-23T10:00:00+08:00", ["一般垃圾"], s) == {"一般垃圾": None}


def test_now_without_timezone():
    with pytest.raises(ValueError, match="時區"):
        run("2026-10-23T15:34:00")


def test_unknown_category():
    with pytest.raises(ValueError, match="未知類別"):
        run("2026-10-23T15:34:00+08:00", ["廚餘"])


def test_bad_schedule():
    with pytest.raises(ValueError):
        run("2026-10-23T15:34:00+08:00", BOTH, {"weekly": {}})


def _cli(payload: str):
    return subprocess.run([sys.executable, str(SCRIPT)], input=payload, capture_output=True,
                          text=True, encoding="utf-8", env={"PYTHONUTF8": "1", "PATH": ""})


def test_subprocess_end_to_end():
    payload = json.dumps({"now": "2026-10-23T15:34:00+08:00", "schedule": SCHEDULE, "categories": BOTH},
                         ensure_ascii=False)
    p = _cli(payload)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["now"] == "2026-10-23T15:34:00+08:00"
    assert out["results"]["資源回收"]["weekday"] == "週五"


def test_subprocess_errors_exit_1():
    assert _cli("not json").returncode == 1
    bad = json.dumps({"now": "2026-10-23T15:34:00", "schedule": SCHEDULE, "categories": BOTH})
    p = _cli(bad)
    assert p.returncode == 1 and "時區" in p.stderr

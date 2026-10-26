import json
from pathlib import Path

import pytest

from recycle_schedule.server import load_schedule

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "mcp_recycle" / "schedule.json"


def test_matches_spec():
    data = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    assert data["area"] == "預設收運點"
    assert data["pickup_window"] == {"start": "18:30", "end": "20:30"}
    assert data["weekly"] == {
        "mon": ["一般垃圾"],
        "tue": ["一般垃圾", "資源回收"],
        "wed": [],
        "thu": ["一般垃圾"],
        "fri": ["一般垃圾", "資源回收"],
        "sat": ["一般垃圾"],
        "sun": [],
    }
    assert data["exceptions"] == []
    assert len(data["notes"]) == 3
    assert data["source"] == {
        "name": "高雄市環保局開放資料「垃圾清運路線及時間」",
        "query_url": "https://kepbgps.kcg.gov.tw/",
        "compiled": "2026-10-23",
    }


def test_passes_validation():
    assert load_schedule(SCHEDULE)["area"] == "預設收運點"


def test_eval_fixture_valid_and_has_exception():
    fx = ROOT / "eval" / "schedule_fixture.json"
    if fx.exists():
        data = load_schedule(fx)
        assert {"date": "2026-10-30", "collect": [], "note": "評測用停收日"} in data["exceptions"]


def test_error_names_field(tmp_path):
    data = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    del data["pickup_window"]["end"]
    data["weekly"]["mon"] = ["廚餘"]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load_schedule(p)
    assert "pickup_window.end" in str(e.value)
    assert "weekly.mon" in str(e.value)


def test_rereads_file_each_call(tmp_path):
    data = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    p = tmp_path / "s.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert load_schedule(p)["exceptions"] == []
    data["exceptions"] = [{"date": "2027-02-06", "collect": [], "note": "春節停收"}]
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert load_schedule(p)["exceptions"][0]["note"] == "春節停收"

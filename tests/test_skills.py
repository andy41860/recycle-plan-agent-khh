import json
import os
from pathlib import Path

import pytest

from recycle_agent.tools.skills import list_skills, load_skill_text, run_script, skills_prompt

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "skills"


@pytest.fixture
def sdir(tmp_path):
    scripts = tmp_path / "demo" / "scripts"
    scripts.mkdir(parents=True)
    (tmp_path / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 測試用\n---\n\n# 內文\n你好\n", encoding="utf-8")
    (scripts / "echo.py").write_text(
        "import sys, json\nd = json.loads(sys.stdin.read())\nprint(json.dumps({'got': d}, ensure_ascii=False))\n",
        encoding="utf-8")
    (scripts / "fail.py").write_text("import sys\nprint('壞掉了', file=sys.stderr)\nsys.exit(3)\n", encoding="utf-8")
    (scripts / "slow.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    (scripts / "notjson.py").write_text("print('hello')\n", encoding="utf-8")
    (scripts / "noisy.py").write_text("import sys\nprint('x' * 5000, file=sys.stderr)\nsys.exit(1)\n", encoding="utf-8")
    (tmp_path / "secret.py").write_text("print('{}')\n", encoding="utf-8")
    (tmp_path / "demo" / "other.py").write_text("print('{}')\n", encoding="utf-8")
    return tmp_path


def test_list_and_prompt():
    skills = list_skills(REAL)
    assert [s["name"] for s in skills] == ["disposal-plan"]
    assert "disposal-plan：" in skills_prompt(REAL)


def test_load_skill_strips_frontmatter(sdir):
    text = load_skill_text("demo", sdir)
    assert text.startswith("# 內文") and "name:" not in text


def test_load_unknown_lists_available(sdir):
    assert "demo" in load_skill_text("nope", sdir)


def test_chinese_round_trip(sdir):
    out = run_script("demo", "echo.py", json.dumps({"物品": "手搖杯", "類別": ["資源回收"]}, ensure_ascii=False), sdir)
    assert json.loads(out) == {"got": {"物品": "手搖杯", "類別": ["資源回收"]}}


@pytest.mark.parametrize("script", ["../other.py", "..\\other.py", "../../secret.py", "sub/../../other.py"])
def test_path_traversal_rejected(sdir, script):
    assert run_script("demo", script, "{}", sdir).startswith("錯誤")


def test_absolute_path_rejected(sdir):
    assert run_script("demo", str(sdir / "secret.py"), "{}", sdir).startswith("錯誤")


def test_skill_name_traversal_rejected(sdir):
    assert run_script("..", "secret.py", "{}", sdir).startswith("錯誤")


def test_symlink_escape_rejected(sdir):
    link = sdir / "demo" / "scripts" / "link.py"
    try:
        os.symlink(sdir / "secret.py", link)
    except (OSError, NotImplementedError):
        pytest.skip("無法建立符號連結")
    assert run_script("demo", "link.py", "{}", sdir).startswith("錯誤")


def test_non_py_rejected(sdir):
    (sdir / "demo" / "scripts" / "x.txt").write_text("hi", encoding="utf-8")
    assert "只能執行 .py" in run_script("demo", "x.txt", "{}", sdir)


def test_missing_script(sdir):
    assert "找不到腳本" in run_script("demo", "nope.py", "{}", sdir)


def test_invalid_input_json_not_executed(sdir):
    assert "不是合法 JSON" in run_script("demo", "echo.py", "{not json", sdir)


def test_timeout(sdir):
    assert "逾時" in run_script("demo", "slow.py", "{}", sdir, timeout=1)


def test_non_json_output(sdir):
    assert "不是 JSON" in run_script("demo", "notjson.py", "{}", sdir)


def test_nonzero_exit_includes_stderr(sdir):
    out = run_script("demo", "fail.py", "{}", sdir)
    assert out.startswith("錯誤") and "壞掉了" in out and "3" in out


def test_stderr_truncated(sdir):
    out = run_script("demo", "noisy.py", "{}", sdir)
    assert out.count("x") == 1000


def test_real_next_pickup_through_runner():
    schedule = json.loads((ROOT / "mcp_recycle" / "schedule.json").read_text(encoding="utf-8"))
    payload = json.dumps({"now": "2026-10-24T21:00:00+08:00", "schedule": schedule, "categories": ["資源回收"]},
                         ensure_ascii=False)
    out = json.loads(run_script("disposal-plan", "next_pickup.py", payload, REAL))
    assert out["results"]["資源回收"]["weekday"] == "週二"

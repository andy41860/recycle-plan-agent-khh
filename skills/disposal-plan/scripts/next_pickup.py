"""計算各類別的下一個收運日。只用標準函式庫。

stdin：{"now": ISO 8601 含時區, "schedule": get_schedule 回傳, "categories": ["資源回收", "一般垃圾"]}
stdout：{"now": ..., "results": {類別: {date, weekday, start, end, is_today, note} | null}}
錯誤：訊息寫到 stderr，結束碼 1。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, time, timedelta

VALID_CATEGORIES = ("資源回收", "一般垃圾")
WEEK_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_ZH = ("週一", "週二", "週三", "週四", "週五", "週六", "週日")
SEARCH_DAYS = 15  # d = 0 .. 14


def _parse_hhmm(value, field: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        raise ValueError(f"schedule.{field} 必須是 HH:MM，實際為 {value!r}") from None


def _validate_schedule(schedule) -> tuple[time, time, dict, dict]:
    if not isinstance(schedule, dict):
        raise ValueError("schedule 必須是物件")
    window = schedule.get("pickup_window")
    if not isinstance(window, dict):
        raise ValueError("schedule.pickup_window 缺少或格式錯誤")
    start = _parse_hhmm(window.get("start"), "pickup_window.start")
    end = _parse_hhmm(window.get("end"), "pickup_window.end")
    weekly = schedule.get("weekly")
    if not isinstance(weekly, dict):
        raise ValueError("schedule.weekly 缺少或格式錯誤")
    for key in WEEK_KEYS:
        if not isinstance(weekly.get(key), list):
            raise ValueError(f"schedule.weekly.{key} 必須是陣列")
    exceptions = {}
    for i, exc in enumerate(schedule.get("exceptions") or []):
        if not isinstance(exc, dict) or not isinstance(exc.get("date"), str) or not isinstance(exc.get("collect"), list):
            raise ValueError(f"schedule.exceptions[{i}] 格式錯誤，需有 date 與 collect")
        exceptions[exc["date"]] = exc
    return start, end, weekly, exceptions


def compute(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("輸入必須是 JSON 物件")
    try:
        now = datetime.fromisoformat(payload["now"])
    except KeyError:
        raise ValueError("缺少 now") from None
    except (TypeError, ValueError):
        raise ValueError(f"now 不是合法的 ISO 8601：{payload.get('now')!r}") from None
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now 必須含時區偏移，例如 2026-10-23T15:34:00+08:00")

    categories = payload.get("categories")
    if not isinstance(categories, list):
        raise ValueError("categories 必須是陣列")
    unknown = [c for c in categories if c not in VALID_CATEGORIES]
    if unknown:
        raise ValueError(f"未知類別 {unknown}，只接受 {list(VALID_CATEGORIES)}")

    start, end, weekly, exceptions = _validate_schedule(payload.get("schedule"))

    results: dict = {}
    for cat in categories:
        found = None
        for d in range(SEARCH_DAYS):
            day = now + timedelta(days=d)
            iso = day.date().isoformat()
            exc = exceptions.get(iso)
            collect = exc["collect"] if exc else weekly[WEEK_KEYS[day.weekday()]]
            if cat not in collect:
                continue
            if d == 0 and not now.time() < end:
                continue
            found = {
                "date": iso,
                "weekday": WEEKDAY_ZH[day.weekday()],
                "start": start.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
                "is_today": d == 0,
                "note": (exc.get("note") or None) if exc else None,
            }
            break
        results[cat] = found
    return {"now": payload["now"], "results": results}


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        payload = json.loads(sys.stdin.read())
        out = compute(payload)
    except json.JSONDecodeError as e:
        print(f"輸入不是合法 JSON：{e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

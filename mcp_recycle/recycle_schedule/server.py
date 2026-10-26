"""recycle-schedule MCP server：回傳寫死的收運時刻表。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, ValidationError

ROOT = Path(__file__).resolve().parent.parent.parent
Category = Literal["一般垃圾", "資源回收"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PickupWindow(_Model):
    start: str
    end: str


class Weekly(_Model):
    mon: list[Category]
    tue: list[Category]
    wed: list[Category]
    thu: list[Category]
    fri: list[Category]
    sat: list[Category]
    sun: list[Category]


class ScheduleException(_Model):
    date: str
    collect: list[Category]
    note: str = ""


class Source(_Model):
    name: str
    query_url: str
    compiled: str


class Schedule(_Model):
    area: str
    pickup_window: PickupWindow
    weekly: Weekly
    exceptions: list[ScheduleException]
    notes: list[str]
    source: Source


def schedule_path() -> Path:
    p = Path(os.environ.get("SCHEDULE_PATH") or "mcp_recycle/schedule.json")
    return p if p.is_absolute() else ROOT / p


def load_schedule(path: Path | None = None) -> dict:
    """每次都重新讀檔並驗證；格式錯誤時指出是哪個欄位。"""
    path = path or schedule_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"找不到時刻表檔案：{path}") from None
    except json.JSONDecodeError as e:
        raise ValueError(f"時刻表 JSON 格式錯誤（{path}）：{e}") from None
    try:
        return Schedule.model_validate(raw).model_dump()
    except ValidationError as e:
        detail = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise ValueError(f"時刻表欄位錯誤（{path}）：{detail}") from None


mcp = FastMCP(
    "recycle-schedule",
    host=os.environ.get("MCP_HOST") or "127.0.0.1",
    port=int(os.environ.get("MCP_PORT") or 8001),
)


@mcp.tool()
def get_schedule() -> dict:
    """取得預設收運點的完整收運時刻表（收運時段、每週各類別收運日、例外日期、說明、資料來源）。"""
    return load_schedule()


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

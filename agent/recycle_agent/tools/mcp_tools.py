"""MCP 工具：recycle-schedule（streamable HTTP）與 time（stdio），以及評測用假時鐘。"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from .. import config

# 評測用：每題可更新這個模組層級變數（None 時讀 AGENT_FAKE_NOW）。
FAKE_NOW: str | None = None


def fake_now() -> str | None:
    return FAKE_NOW or os.environ.get("AGENT_FAKE_NOW") or config.AGENT_FAKE_NOW or None


def _fake_clock_tool() -> StructuredTool:
    """與 mcp-server-time 的 get_current_time 同名、同參數、同回傳格式。"""

    def get_current_time(timezone: str) -> str:
        now = fake_now()
        dt = datetime.fromisoformat(now)
        if dt.tzinfo is None:
            raise ValueError("AGENT_FAKE_NOW 必須含時區偏移")
        local = dt.astimezone(ZoneInfo(timezone))
        return (
            '{"timezone": "%s", "datetime": "%s", "day_of_week": "%s", "is_dst": false}'
            % (timezone, local.isoformat(timespec="seconds"), local.strftime("%A"))
        )

    return StructuredTool.from_function(
        func=get_current_time,
        name="get_current_time",
        description="Get current time in a specific timezone (IANA name, e.g. 'Asia/Taipei').",
    )


def _client() -> MultiServerMCPClient:
    servers = {"recycle-schedule": {"transport": "streamable_http", "url": config.MCP_RECYCLE_URL}}
    if not fake_now():
        servers["time"] = {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "mcp_server_time", "--local-timezone", config.TIMEZONE],
        }
    return MultiServerMCPClient(servers)


async def load_mcp_tools() -> list:
    """回傳 get_schedule 與 get_current_time（只暴露這兩個給模型）。"""
    client = _client()
    try:
        tools = await client.get_tools()
    except Exception as e:
        raise RuntimeError(
            f"無法連線 recycle-schedule MCP server（MCP_RECYCLE_URL={config.MCP_RECYCLE_URL}）。"
            f"請先啟動：uv run --package mcp-recycle python -m recycle_schedule.server。原始錯誤：{e}"
        ) from e
    wanted = {"get_schedule", "get_current_time"}
    tools = [t for t in tools if t.name in wanted]
    if fake_now():
        tools.append(_fake_clock_tool())
    missing = wanted - {t.name for t in tools}
    if missing:
        raise RuntimeError(f"MCP 缺少工具：{', '.join(sorted(missing))}")
    return tools

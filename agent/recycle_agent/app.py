"""Chainlit UI：即時顯示每一步的 Thought / Action / Observation。"""

from __future__ import annotations

import asyncio
import json
import time

import chainlit as cl
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from recycle_agent.graph import EMPTY_THOUGHT, build_agent, message_text

OBS_LIMIT = 800

STARTERS = [
    ("多物品丟棄計畫", "手搖杯、廢電池、紙便當盒今晚能丟嗎？"),
    ("單一物品分類", "保麗龍便當盒要丟哪？"),
    ("今天收什麼", "今天有收資源回收嗎？幾點？"),
    ("知識庫沒有的物品", "用過的暖暖包要怎麼丟？"),
]

_graph = None
_graph_lock = asyncio.Lock()


async def get_graph():
    """第一次使用時才建立（含知識庫與 MCP 檢查），之後共用；每則訊息仍獨立處理。"""
    global _graph
    async with _graph_lock:
        if _graph is None:
            _graph = await build_agent()
        return _graph


def truncate(text: str, limit: int = OBS_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截斷，共 {len(text)} 字）"


@cl.set_starters
async def set_starters():
    return [cl.Starter(label=label, message=message) for label, message in STARTERS]


@cl.on_message
async def on_message(message: cl.Message):
    try:
        graph = await get_graph()
    except Exception as e:  # 缺環境變數、知識庫未建立、MCP 連不上
        await cl.Message(content=f"⚠️ 啟動失敗：{e}").send()
        return

    start = time.perf_counter()
    steps = 0
    final = ""
    try:
        async for update in graph.astream(
            {"messages": [HumanMessage(content=message.content)], "steps": 0}, stream_mode="updates"
        ):
            for node, out in update.items():
                for msg in out.get("messages", []):
                    if isinstance(msg, AIMessage):
                        if node == "reason":
                            steps += 1
                        if msg.tool_calls:
                            await show_thought_and_actions(msg)
                        else:
                            final = message_text(msg.content)
                    elif isinstance(msg, ToolMessage):
                        async with cl.Step(name=f"Observation：{msg.name}", type="tool") as step:
                            step.output = truncate(message_text(msg.content))
    except Exception as e:
        await cl.Message(content=f"⚠️ 執行失敗：{e}").send()
        return

    elapsed = time.perf_counter() - start
    footer = f"共 {steps} 步・耗時 {elapsed:.1f} 秒"
    await cl.Message(content=f"{final}\n\n---\n*{footer}*").send()


async def show_thought_and_actions(msg: AIMessage) -> None:
    async with cl.Step(name="Thought", type="llm") as step:
        step.output = message_text(msg.content).strip() or EMPTY_THOUGHT
    for call in msg.tool_calls:  # 平行呼叫時每個 call 各一個 Step
        async with cl.Step(name=f"Action：{call['name']}", type="tool") as step:
            step.language = "json"
            step.output = json.dumps(call["args"], ensure_ascii=False, indent=2)

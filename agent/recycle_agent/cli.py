"""命令列執行：uv run python -m recycle_agent.cli "問題" """

from __future__ import annotations

import asyncio
import json
import sys
import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .graph import EMPTY_THOUGHT, build_agent, message_text

OBS_LIMIT = 800


async def run(question: str) -> int:
    graph = await build_agent()
    start = time.perf_counter()
    steps = 0
    final = ""
    async for update in graph.astream(
        {"messages": [HumanMessage(content=question)], "steps": 0}, stream_mode="updates"
    ):
        for node, out in update.items():
            for msg in out.get("messages", []):
                if isinstance(msg, AIMessage):
                    if node == "reason":
                        steps += 1
                    if msg.tool_calls:
                        print(f"\n[Thought] {message_text(msg.content).strip() or EMPTY_THOUGHT}")
                        for c in msg.tool_calls:
                            print(f"[Action] {c['name']}({json.dumps(c['args'], ensure_ascii=False)})")
                    else:
                        final = message_text(msg.content)
                elif isinstance(msg, ToolMessage):
                    text = message_text(msg.content)
                    if len(text) > OBS_LIMIT:
                        text = text[:OBS_LIMIT] + f"…（已截斷，共 {len(text)} 字）"
                    print(f"[Observation] {msg.name}: {text}")
    print(f"\n===== 最終回答 =====\n{final}")
    print(f"\n共 {steps} 步・耗時 {time.perf_counter() - start:.1f} 秒")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print('用法：python -m recycle_agent.cli "問題"', file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(" ".join(sys.argv[1:])))
    except RuntimeError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

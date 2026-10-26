"""LangGraph ReAct：reason → act → reason …，自行實作迴圈（不使用預建 agent）。"""

from __future__ import annotations

import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from . import config

DUPLICATE_MESSAGE = "此工具剛以相同參數呼叫過，結果已在上方，請改用其他方式或直接作答。"
EMPTY_THOUGHT = "（模型未輸出推理文字）"


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    steps: int


def message_text(content) -> str:
    """取出文字：content 可能是字串（含空字串）或 content-block list。"""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


# ---- 重複呼叫偵測（純函式）----

def call_key(call: dict) -> tuple[str, str]:
    return call["name"], json.dumps(call.get("args", {}), sort_keys=True, ensure_ascii=False)


def previous_call_keys(messages: list) -> set[tuple[str, str]]:
    """上一輪 act 的 key：最後一則 AIMessage（本輪）之前，最近一則帶 tool_calls 的 AIMessage。"""
    for msg in reversed(messages[:-1]):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            return {call_key(c) for c in msg.tool_calls}
    return set()


def split_calls(tool_calls: list[dict], previous: set[tuple[str, str]]) -> tuple[list[dict], set[str]]:
    """回傳 (要執行的 calls, 被攔下的 tool_call_id)。與上一輪相同、或同輪內重複者攔下，同輪只執行第一個。"""
    to_run: list[dict] = []
    blocked: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for call in tool_calls:
        key = call_key(call)
        if key in previous or key in seen:
            blocked.add(call["id"])
        else:
            to_run.append(call)
            seen.add(key)
    return to_run, blocked


def merge_tool_messages(tool_calls: list[dict], executed: dict[str, ToolMessage], blocked: set[str]) -> list[ToolMessage]:
    """依原 tool call 順序合併執行結果與攔截訊息。"""
    merged = []
    for call in tool_calls:
        if call["id"] in blocked:
            merged.append(ToolMessage(content=DUPLICATE_MESSAGE, tool_call_id=call["id"], name=call["name"]))
        elif call["id"] in executed:
            merged.append(executed[call["id"]])
        else:
            merged.append(ToolMessage(content="工具沒有回傳結果。", tool_call_id=call["id"], name=call["name"], status="error"))
    return merged


# ---- 節點與路由 ----

def make_reason_node(llm, tools, system_prompt: str):
    bound = llm.bind_tools(tools, parallel_tool_calls=True)

    async def reason(state: AgentState) -> dict:
        response = await bound.ainvoke([SystemMessage(content=system_prompt), *state["messages"]])
        return {"messages": [response], "steps": state.get("steps", 0) + 1}

    return reason


def make_act_node(tools):
    tool_node = ToolNode(tools, handle_tool_errors=True)

    async def act(state: AgentState, config: RunnableConfig) -> dict:
        messages = state["messages"]
        ai = messages[-1]
        to_run, blocked = split_calls(ai.tool_calls, previous_call_keys(messages))
        executed: dict[str, ToolMessage] = {}
        if to_run:
            result = await tool_node.ainvoke({"messages": [AIMessage(content="", tool_calls=to_run)]}, config)
            executed = {m.tool_call_id: m for m in result["messages"]}
        return {"messages": merge_tool_messages(ai.tool_calls, executed, blocked)}

    return act


def make_limit_node(max_steps: int):
    def limit(state: AgentState) -> dict:
        lines = []
        for msg in state["messages"]:
            if isinstance(msg, AIMessage):
                for c in msg.tool_calls:
                    lines.append(f"- {c['name']}({json.dumps(c.get('args', {}), ensure_ascii=False)})")
        called = "\n".join(lines) or "（尚未呼叫任何工具）"
        text = (
            f"已達步驟上限（{max_steps}），無法完成這次查詢。\n\n已呼叫過的工具與參數：\n{called}\n\n"
            "建議把問題拆小，例如一次只問一兩個物品，或把分類與收運時間分開問。"
        )
        return {"messages": [AIMessage(content=text)]}

    return limit


def make_router(max_steps: int):
    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        return "act" if state["steps"] < max_steps else "limit"

    return route


def build_graph(llm, tools, system_prompt: str, max_steps: int | None = None):
    max_steps = max_steps or config.MAX_STEPS
    g = StateGraph(AgentState)
    g.add_node("reason", make_reason_node(llm, tools, system_prompt))
    g.add_node("act", make_act_node(tools))
    g.add_node("limit", make_limit_node(max_steps))
    g.add_edge(START, "reason")
    g.add_conditional_edges("reason", make_router(max_steps), {"act": "act", "limit": "limit", END: END})
    g.add_edge("act", "reason")
    g.add_edge("limit", END)
    return g.compile()  # 無 checkpointer：每次提問獨立


async def build_agent():
    """組合 LLM、工具與 system prompt，回傳編譯好的 graph。"""
    from langchain_openai import ChatOpenAI

    from .prompts import build_system_prompt
    from .tools import build_tools

    config.require("OPENAI_API_KEY", "LLM_MODEL", "EMBED_MODEL")
    tools = await build_tools()
    return build_graph(ChatOpenAI(model=config.LLM_MODEL), tools, build_system_prompt())

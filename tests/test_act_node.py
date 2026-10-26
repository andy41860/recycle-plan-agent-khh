import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from recycle_agent.graph import (
    DUPLICATE_MESSAGE,
    AgentState,
    call_key,
    make_act_node,
    make_limit_node,
    make_router,
    merge_tool_messages,
    message_text,
    previous_call_keys,
    split_calls,
)

CALLS_LOG: list[str] = []


@tool
def echo(text: str) -> str:
    """echo"""
    CALLS_LOG.append(text)
    return f"echo:{text}"


@tool
def boom(text: str) -> str:
    """always fails"""
    raise RuntimeError("壞了")


def c(id_, name="echo", **args):
    return {"id": id_, "name": name, "args": args, "type": "tool_call"}


def test_call_key_ignores_arg_order_and_keeps_chinese():
    assert call_key(c("1", a=1, b="中")) == call_key(c("2", b="中", a=1))
    assert "中" in call_key(c("1", b="中"))[1]
    assert call_key(c("1", text="a")) != call_key(c("1", text="b"))
    assert call_key(c("1", "echo", text="a")) != call_key(c("1", "boom", text="a"))


def test_split_same_round_keeps_first_only():
    run, blocked = split_calls([c("1", text="a"), c("2", text="a"), c("3", text="b")], set())
    assert [x["id"] for x in run] == ["1", "3"]
    assert blocked == {"2"}


def test_split_blocks_calls_from_previous_round():
    prev = {call_key(c("x", text="a"))}
    run, blocked = split_calls([c("1", text="a"), c("2", text="b")], prev)
    assert [x["id"] for x in run] == ["2"] and blocked == {"1"}


def test_previous_call_keys_uses_last_round_only():
    msgs = [
        HumanMessage(content="q"),
        AIMessage(content="", tool_calls=[c("1", text="old")]),
        ToolMessage(content="r", tool_call_id="1"),
        AIMessage(content="", tool_calls=[c("2", text="prev")]),
        ToolMessage(content="r", tool_call_id="2"),
        AIMessage(content="", tool_calls=[c("3", text="now")]),
    ]
    assert previous_call_keys(msgs) == {call_key(c("2", text="prev"))}
    assert previous_call_keys(msgs[:1] + [AIMessage(content="", tool_calls=[c("1")])]) == set()


def test_merge_preserves_original_order():
    calls = [c("1", text="a"), c("2", text="a"), c("3", text="b")]
    executed = {"3": ToolMessage(content="B", tool_call_id="3"), "1": ToolMessage(content="A", tool_call_id="1")}
    merged = merge_tool_messages(calls, executed, {"2"})
    assert [m.tool_call_id for m in merged] == ["1", "2", "3"]
    assert [m.content for m in merged] == ["A", DUPLICATE_MESSAGE, "B"]


def _act(messages):
    """把 act 節點放進只有它一個節點的 graph 執行（ToolNode 需要 graph runtime）。"""
    g = StateGraph(AgentState)
    g.add_node("act", make_act_node([echo, boom]))
    g.add_edge(START, "act")
    g.add_edge("act", END)
    result = asyncio.run(g.compile().ainvoke({"messages": messages, "steps": 1}))
    return result["messages"][len(messages):]


def test_act_node_same_round_duplicate_executes_once():
    CALLS_LOG.clear()
    out = _act([HumanMessage(content="q"),
                AIMessage(content="", tool_calls=[c("1", text="a"), c("2", text="a"), c("3", text="b")])])
    assert CALLS_LOG == ["a", "b"]
    assert [m.tool_call_id for m in out] == ["1", "2", "3"]
    assert out[0].content == "echo:a" and out[1].content == DUPLICATE_MESSAGE and out[2].content == "echo:b"


def test_act_node_repeat_of_previous_round_blocked():
    CALLS_LOG.clear()
    out = _act([
        HumanMessage(content="q"),
        AIMessage(content="", tool_calls=[c("1", text="a")]),
        ToolMessage(content="echo:a", tool_call_id="1"),
        AIMessage(content="", tool_calls=[c("2", text="a"), c("3", text="b")]),
    ])
    assert CALLS_LOG == ["b"]
    assert out[0].content == DUPLICATE_MESSAGE and out[1].content == "echo:b"


def test_act_node_tool_error_does_not_raise():
    out = _act([HumanMessage(content="q"), AIMessage(content="", tool_calls=[c("1", "boom", text="a"), c("2", text="z")])])
    assert "壞了" in out[0].content and out[1].content == "echo:z"


def test_router():
    route = make_router(3)
    with_calls = AIMessage(content="", tool_calls=[c("1")])
    assert route({"messages": [with_calls], "steps": 2}) == "act"
    assert route({"messages": [with_calls], "steps": 3}) == "limit"
    assert route({"messages": [AIMessage(content="done")], "steps": 99}) == END


def test_limit_node_lists_calls():
    msgs = [HumanMessage(content="q"), AIMessage(content="", tool_calls=[c("1", text="手搖杯")])]
    text = make_limit_node(12)({"messages": msgs, "steps": 12})["messages"][0].content
    assert "已達步驟上限（12）" in text and "echo" in text and "手搖杯" in text


def test_message_text_handles_str_empty_and_blocks():
    assert message_text("hi") == "hi"
    assert message_text("") == ""
    assert message_text([{"type": "text", "text": "a"}, {"type": "tool_use", "id": "x"}, {"type": "text", "text": "b"}]) == "ab"

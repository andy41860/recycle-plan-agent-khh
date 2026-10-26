"""評測：uv run eval/run_eval.py [--only ID] [--repeat N]

自行啟動 mcp-recycle（port 8011、使用 eval/schedule_fixture.json），每題設定假時鐘，
再用 LLM 做結構化抽取判分，產出 eval/results.md。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
MCP_PORT = 8011
DEFAULT_NOW = "2026-10-23T18:00:00+08:00"
FOOD_LINK = "https://recycle.ksepb.kcg.gov.tw/StaticPage/classification"

# 必須在 import recycle_agent.config 之前設定（config 在 import 時讀環境變數）
os.environ["MCP_RECYCLE_URL"] = f"http://127.0.0.1:{MCP_PORT}/mcp"
os.environ["AGENT_FAKE_NOW"] = DEFAULT_NOW

Result = Literal["資源回收", "一般垃圾", "特殊管道", "查無資料"]


class ItemResult(BaseModel):
    name: str = Field(description="使用題目指定的名稱")
    result: Result


class PickupResult(BaseModel):
    category: Literal["資源回收", "一般垃圾"]
    date: str | None = Field(description="回答給出的下次收運日 YYYY-MM-DD；沒有給出則為 null")
    start: str | None = Field(description="收運開始時間 HH:MM；沒有給出則為 null")


class Extraction(BaseModel):
    items: list[ItemResult] = Field(description="回答中對各物品／部位的處理結果")
    pickups: list[PickupResult] = Field(description="回答中給出的各類別下次收運時間；沒有則為空陣列")
    out_of_scope: bool = Field(description="回答是否把問題判定為與垃圾處理無關並婉拒")
    has_food_waste_link: bool = Field(description=f"回答是否包含廚餘分類連結 {FOOD_LINK}")


def wait_port(port: int, proc: subprocess.Popen, timeout: float = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            socket.create_connection(("127.0.0.1", port), 1).close()
            return True
        except OSError:
            time.sleep(0.5)
    return False


def start_mcp() -> subprocess.Popen:
    env = {
        **os.environ,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(MCP_PORT),
        "SCHEDULE_PATH": str(EVAL_DIR / "schedule_fixture.json"),
        "PYTHONUTF8": "1",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "recycle_schedule.server"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )


def stop_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


EXTRACT_PROMPT = """你是評測用的資訊抽取器。依下列「問題」與「Agent 的回答」，抽取結構化結果。只根據回答的內容，不要自行補充或判斷對錯。

處理結果只有四種：資源回收、一般垃圾、特殊管道（回答指向電池回收點、大型家具、廢機動車輛、裝潢廢料等指定管道）、查無資料（回答明確表示知識庫查無此物品）。

items：請用這些名稱回報：{names}。回答沒有提到的項目就省略。
pickups：回答給出的各類別（資源回收／一般垃圾）下次收運日期與開始時間，沒有給出就留空。日期用 YYYY-MM-DD。
out_of_scope：回答是否婉拒並導回垃圾分類主題。
has_food_waste_link：回答是否包含 {link}。

問題：{question}

Agent 的回答：
{answer}
"""


def grade(case: dict, ext: Extraction, tool_names: list[str], answer: str) -> list[str]:
    """回傳錯誤清單，空表示通過。"""
    expect = case["expect"]
    errors: list[str] = []
    got = {i.name: i.result for i in ext.items}
    for name, want in (expect.get("items") or {}).items():
        if got.get(name) != want:
            errors.append(f"{name}：預期 {want}，實際 {got.get(name, '（未提及）')}")
    got_p = {p.category: p for p in ext.pickups}
    for cat, want in (expect.get("pickups") or {}).items():
        p = got_p.get(cat)
        want_date, want_start = str(want["date"]), str(want["start"])
        if not p or p.date != want_date or p.start != want_start:
            actual = f"{p.date} {p.start}" if p else "（未提及）"
            errors.append(f"收運 {cat}：預期 {want_date} {want_start}，實際 {actual}")
    if expect.get("out_of_scope"):
        if not ext.out_of_scope:
            errors.append("範圍外：未婉拒")
        if tool_names:
            errors.append(f"範圍外：不應呼叫工具，實際呼叫 {tool_names}")
    if expect.get("food_waste_link") and not (ext.has_food_waste_link or FOOD_LINK in answer):
        errors.append("缺少廚餘分類連結")
    return errors


async def run_case(graph, extractor, case: dict, mcp_tools_module) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    from recycle_agent.graph import message_text

    mcp_tools_module.FAKE_NOW = str(case.get("now") or DEFAULT_NOW)
    start = time.perf_counter()
    state = await graph.ainvoke(
        {"messages": [HumanMessage(content=case["question"])], "steps": 0},
        {"recursion_limit": 100},
    )
    elapsed = time.perf_counter() - start
    msgs = state["messages"]
    answer = message_text(msgs[-1].content)
    tool_names = [c["name"] for m in msgs if isinstance(m, AIMessage) for c in m.tool_calls]
    names = list((case["expect"].get("items") or {}).keys()) or ["（無）"]
    ext: Extraction = await extractor.ainvoke(
        EXTRACT_PROMPT.format(names="、".join(names), link=FOOD_LINK, question=case["question"], answer=answer)
    )
    errors = grade(case, ext, tool_names, answer)
    return {
        "id": case["id"], "type": case["type"], "ok": not errors, "errors": errors,
        "steps": state["steps"], "elapsed": elapsed, "limit": answer.startswith("已達步驟上限"),
        "answer": answer, "tools": tool_names, "expect": case["expect"], "ext": ext,
    }


def metrics(runs: list[dict]) -> dict:
    item_total = item_ok = nf_total = nf_guess = pick_total = pick_ok = scope_total = scope_ok = 0
    for r in runs:
        got = {i.name: i.result for i in r["ext"].items}
        for name, want in (r["expect"].get("items") or {}).items():
            item_total += 1
            item_ok += got.get(name) == want
            if want == "查無資料":
                nf_total += 1
                nf_guess += name in got and got[name] != "查無資料"
        got_p = {p.category: p for p in r["ext"].pickups}
        for cat, want in (r["expect"].get("pickups") or {}).items():
            pick_total += 1
            p = got_p.get(cat)
            pick_ok += bool(p and p.date == str(want["date"]) and p.start == str(want["start"]))
        if r["expect"].get("out_of_scope"):
            scope_total += 1
            scope_ok += r["ext"].out_of_scope and not r["tools"]
    n = len(runs)
    return {
        "classification": (item_ok, item_total), "guess": (nf_guess, nf_total),
        "pickup": (pick_ok, pick_total), "scope": (scope_ok, scope_total),
        "avg_steps": sum(r["steps"] for r in runs) / n, "avg_elapsed": sum(r["elapsed"] for r in runs) / n,
        "limit_hits": sum(r["limit"] for r in runs), "passed": sum(r["ok"] for r in runs), "n": n,
    }


def pct(pair: tuple[int, int]) -> str:
    ok, total = pair
    return f"{ok / total:.0%}（{ok}/{total}）" if total else "—"


def write_report(runs: list[dict], repeat: int, cfg) -> Path:
    m = metrics(runs)
    lines = [
        "# 評測結果", "",
        f"- 時間：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 模型：{cfg.LLM_MODEL}（embedding：{cfg.EMBED_MODEL}）",
        f"- RAG_SCORE_THRESHOLD：{cfg.RAG_SCORE_THRESHOLD}，RAG_TOP_K：{cfg.RAG_TOP_K}，MAX_STEPS：{cfg.MAX_STEPS}",
        f"- 題數：{len({r['id'] for r in runs})}，每題重複：{repeat}，總執行：{m['n']}，完全通過：{m['passed']}/{m['n']}", "",
        "## 指標", "",
        "| 指標 | 數值 |", "| --- | --- |",
        f"| 分類正確率（逐項） | {pct(m['classification'])} |",
        f"| 查無資料亂猜率 | {pct(m['guess'])} |",
        f"| 收運日正確率 | {pct(m['pickup'])} |",
        f"| 範圍外處理率 | {pct(m['scope'])} |",
        f"| 平均步數 | {m['avg_steps']:.1f} |",
        f"| 平均耗時 | {m['avg_elapsed']:.1f} 秒 |",
        f"| 達步數上限次數 | {m['limit_hits']} |", "",
        "## 逐題結果", "",
        "| id | 類型 | 通過 | 步數 | 耗時(秒) | 錯誤項目 |", "| --- | --- | --- | --- | --- | --- |",
    ]
    by_id: dict[str, list[dict]] = {}
    for r in runs:
        by_id.setdefault(r["id"], []).append(r)
    failed = []
    for cid, rs in by_id.items():
        ok = sum(r["ok"] for r in rs)
        errs = sorted({e for r in rs for e in r["errors"]})
        lines.append(
            f"| {cid} | {rs[0]['type']} | {'✅' if ok == len(rs) else '❌'} {ok}/{len(rs)} "
            f"| {sum(r['steps'] for r in rs) / len(rs):.1f} | {sum(r['elapsed'] for r in rs) / len(rs):.1f} "
            f"| {'；'.join(errs).replace('|', '／')} |"
        )
        failed += [r for r in rs if not r["ok"]][:1]
    lines += ["", "## 失敗題的完整回答", ""]
    if not failed:
        lines.append("（無）")
    for r in failed:
        lines += [f"### {r['id']}", "", f"呼叫的工具：{', '.join(r['tools']) or '（無）'}", "",
                  f"錯誤：{'；'.join(r['errors'])}", "", "```text", r["answer"], "```", ""]
    out = EVAL_DIR / "results.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


async def main_async(args) -> int:
    cases = yaml.safe_load((EVAL_DIR / "cases.yaml").read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
        if not cases:
            print(f"找不到題目 {args.only}", file=sys.stderr)
            return 2

    proc = start_mcp()
    try:
        if not wait_port(MCP_PORT, proc):
            print("mcp-recycle 無法啟動", file=sys.stderr)
            return 1

        from langchain_openai import ChatOpenAI

        from recycle_agent import config
        from recycle_agent.graph import build_agent
        from recycle_agent.tools import mcp_tools

        graph = await build_agent()
        extractor = ChatOpenAI(model=config.LLM_MODEL).with_structured_output(Extraction)

        runs: list[dict] = []
        for case in cases:
            for i in range(args.repeat):
                r = await run_case(graph, extractor, case, mcp_tools)
                runs.append(r)
                tag = f"#{i + 1}" if args.repeat > 1 else ""
                print(f"{'PASS' if r['ok'] else 'FAIL'} {r['id']}{tag}  {r['steps']} 步 {r['elapsed']:.1f}s"
                      + ("" if r["ok"] else f"  {'；'.join(r['errors'])}"), flush=True)
        out = write_report(runs, args.repeat, config)
        m = metrics(runs)
        print(f"\n分類 {pct(m['classification'])}｜亂猜 {pct(m['guess'])}｜收運 {pct(m['pickup'])}｜範圍外 {pct(m['scope'])}"
              f"｜平均 {m['avg_steps']:.1f} 步 {m['avg_elapsed']:.1f}s｜達上限 {m['limit_hits']}")
        print(f"報告：{out}")
        return 0
    finally:
        stop_proc(proc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只跑指定 id")
    ap.add_argument("--repeat", type=int, default=1, help="每題重複次數")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())

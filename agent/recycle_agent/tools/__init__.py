from __future__ import annotations


async def build_tools() -> list:
    """組合所有工具：search_rules、load_skill、run_skill_script、get_schedule、get_current_time。"""
    from .mcp_tools import load_mcp_tools
    from .rag import get_store, search_rules
    from .skills import load_skill, run_skill_script

    get_store()  # 啟動檢查：知識庫不存在時立即報錯
    return [search_rules, load_skill, run_skill_script, *await load_mcp_tools()]

"""設定：以 repo 根目錄的 .env 管理，相對路徑一律以 repo 根目錄為基準。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name) or default


OPENAI_API_KEY = _get("OPENAI_API_KEY")
LLM_MODEL = _get("LLM_MODEL")
EMBED_MODEL = _get("EMBED_MODEL")
RAG_TOP_K = int(_get("RAG_TOP_K", "3"))
RAG_SCORE_THRESHOLD = float(_get("RAG_SCORE_THRESHOLD", "0.35"))
MAX_STEPS = int(_get("MAX_STEPS", "12"))
TIMEZONE = _get("TIMEZONE", "Asia/Taipei")
CHROMA_PATH = _path(_get("CHROMA_PATH", "./.chroma"))
RULES_PDF = _path(_get("RULES_PDF", "data/kaohsiung_recycle_rules.pdf"))
SKILLS_DIR = _path(_get("SKILLS_DIR", "skills"))
MCP_RECYCLE_URL = _get("MCP_RECYCLE_URL", "http://localhost:8001/mcp")
AGENT_FAKE_NOW = _get("AGENT_FAKE_NOW")


def require(*names: str) -> None:
    """缺少必填變數時報錯並列出缺哪些。"""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(f"缺少必填環境變數：{', '.join(missing)}。請複製 .env.example 為 .env 並填入。")

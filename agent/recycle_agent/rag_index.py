"""ingest 與 search_rules 共用的索引設定。"""

from __future__ import annotations

import re

EXPECTED_CATEGORIES = 15
COLLECTION_METADATA = {"hnsw:space": "cosine"}


def collection_name(embed_model: str) -> str:
    """Chroma 名稱限制：3–512 字元，只能用 [A-Za-z0-9._-]，首尾須為英數。換 embedding 模型即對應新索引。"""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", embed_model).strip("-._")
    return f"recycle_rules__{slug}"


def collection_space(col) -> str:
    """讀出 collection 實際使用的距離；相容不同版本的 chromadb。"""
    cfg = getattr(col, "configuration", None)
    if cfg is not None:
        try:
            if isinstance(cfg, dict) or hasattr(cfg, "__getitem__"):
                space = cfg["hnsw"]["space"]
                if space:
                    return str(space)
        except (KeyError, TypeError, IndexError):
            pass
        try:
            space = cfg.hnsw_configuration.space
            if space:
                return str(space)
        except AttributeError:
            pass
    meta = getattr(col, "metadata", None) or {}
    return str(meta.get("hnsw:space", "l2"))

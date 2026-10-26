"""search_rules：查詢回收分類表知識庫。"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.tools import tool

from .. import config
from ..rag_index import COLLECTION_METADATA, EXPECTED_CATEGORIES, collection_name, collection_space

NOT_FOUND = "查無資料"
INGEST_HINT = "請先執行 `uv run scripts/ingest.py`（或 `docker compose run --rm ingest`）建立知識庫。"


@lru_cache(maxsize=1)
def get_store():
    """建立與 ingest 相同的 Chroma store，並做啟動檢查。重新 ingest 後需重啟 agent。"""
    import chromadb
    from langchain_chroma import Chroma
    from langchain_openai import OpenAIEmbeddings

    config.require("OPENAI_API_KEY", "EMBED_MODEL")
    name = collection_name(config.EMBED_MODEL)
    client = chromadb.PersistentClient(path=str(config.CHROMA_PATH))
    try:
        col = client.get_collection(name)
    except Exception as e:
        raise RuntimeError(f"找不到知識庫 collection「{name}」。{INGEST_HINT}") from e
    count = col.count()
    if count == 0:
        raise RuntimeError(f"知識庫 collection「{name}」是空的。{INGEST_HINT}")
    space = collection_space(col)
    if space != "cosine":
        raise RuntimeError(f"知識庫距離為 {space}，預期 cosine。{INGEST_HINT}")
    return Chroma(
        client=client,
        collection_name=name,
        embedding_function=OpenAIEmbeddings(model=config.EMBED_MODEL),
        collection_metadata=COLLECTION_METADATA,
    )


def format_results(results: list[tuple], threshold: float) -> str:
    """results: [(Document, score)]。低於門檻的丟棄；全部低於門檻回傳固定字串。"""
    kept = sorted((r for r in results if r[1] >= threshold), key=lambda r: r[1], reverse=True)
    if not kept:
        return NOT_FOUND
    blocks = []
    for i, (doc, score) in enumerate(kept, start=1):
        m = doc.metadata
        blocks.append(
            f"[{i}] 類別 {int(m['category_id']):02d}／{m['category']}"
            f"（PDF 第 {m['page']} 頁，相似度 {score:.2f}）\n{doc.page_content}"
        )
    m = kept[0][0].metadata
    source = f"資料來源：{m['source_name']} {m['source_url']}（擷取日期 {m['retrieved']}）"
    return "\n\n".join(blocks) + "\n\n" + source


@tool
def search_rules(query: str) -> str:
    """查詢高雄市環保局「回收分類表」，取得物品的回收類別、條件與前處理方式。
    一次只查一個物品；query 用物品名稱即可（例如「寶特瓶」「保麗龍便當盒」）。
    多個物品請分別呼叫，可在同一輪平行呼叫。查不到時回傳「查無資料」。"""
    results = get_store().similarity_search_with_relevance_scores(query, k=config.RAG_TOP_K)
    return format_results(results, config.RAG_SCORE_THRESHOLD)

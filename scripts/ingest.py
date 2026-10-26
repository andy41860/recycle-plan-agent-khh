"""把回收分類表 PDF 寫入 Chroma（每類一頁 = 一個 chunk）。

用法：
    uv run scripts/ingest.py [--dry-run] [--probe 查詢 ...] [--probe-only]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from recycle_agent.rag_index import (  # noqa: E402
    COLLECTION_METADATA,
    EXPECTED_CATEGORIES,
    collection_name,
    collection_space,
)
from recycle_agent.rulebook import read_rule_pages  # noqa: E402


def resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def build_store(embed_model: str, chroma_path: Path):
    import chromadb
    from langchain_chroma import Chroma
    from langchain_openai import OpenAIEmbeddings

    client = chromadb.PersistentClient(path=str(chroma_path))
    store = Chroma(
        client=client,
        collection_name=collection_name(embed_model),
        embedding_function=OpenAIEmbeddings(model=embed_model),
        collection_metadata=COLLECTION_METADATA,
    )
    return client, store


def probe(store, queries: list[str], top_k: int) -> None:
    for q in queries:
        print(f"\n== {q}")
        results = store.similarity_search_with_relevance_scores(q, k=top_k)
        for doc, score in results:
            m = doc.metadata
            print(f"  {score:6.3f}  類別 {m['category_id']:02d} {m['category']}（第 {m['page']} 頁）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只解析 PDF 並印出 chunk，不需 API key")
    ap.add_argument("--probe", action="append", default=[], metavar="查詢", help="寫入後印出 top-k 分數，可重複")
    ap.add_argument("--probe-only", action="store_true", help="不重建，只執行 --probe")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_env()
    pdf = resolve(os.environ.get("RULES_PDF") or "data/kaohsiung_recycle_rules.pdf")
    top_k = int(os.environ.get("RAG_TOP_K") or 3)

    if args.dry_run:
        meta, pages = read_rule_pages(pdf)
        print(f"PDF：{pdf}\nmetadata：{meta}\n共 {len(pages)} 個 chunk")
        for p in pages:
            print(f"\n--- cat-{p.category_id:02d}｜第 {p.page} 頁｜{p.category}｜{len(p.text)} 字")
            print(p.text)
        return 0

    missing = [k for k in ("OPENAI_API_KEY", "EMBED_MODEL") if not os.environ.get(k)]
    if missing:
        print(f"缺少環境變數：{', '.join(missing)}（請設定 .env）", file=sys.stderr)
        return 1
    embed_model = os.environ["EMBED_MODEL"]
    chroma_path = resolve(os.environ.get("CHROMA_PATH") or "./.chroma")

    if args.probe_only:
        _, store = build_store(embed_model, chroma_path)
        probe(store, args.probe, top_k)
        return 0

    meta, pages = read_rule_pages(pdf)
    client, _ = build_store(embed_model, chroma_path)
    name = collection_name(embed_model)
    try:
        client.delete_collection(name)
    except Exception as e:  # NotFoundError（新版）或 ValueError（舊版）
        import chromadb.errors as ce

        if not isinstance(e, (getattr(ce, "NotFoundError", ValueError), ValueError)):
            raise
    client, store = build_store(embed_model, chroma_path)

    texts = [p.text for p in pages]
    metadatas = [
        {
            "category": p.category,
            "category_id": p.category_id,
            "page": p.page,
            "source": pdf.name,
            **meta,
        }
        for p in pages
    ]
    ids = [f"cat-{p.category_id:02d}" for p in pages]
    store.add_texts(texts, metadatas, ids)

    col = client.get_collection(name)
    count = col.count()
    space = collection_space(col)
    if count != EXPECTED_CATEGORIES:
        print(f"驗證失敗：collection 筆數 {count}，預期 {EXPECTED_CATEGORIES}", file=sys.stderr)
        return 1
    if space != "cosine":
        print(f"驗證失敗：距離為 {space}，預期 cosine", file=sys.stderr)
        return 1
    print(f"已寫入 {count} 筆到 collection「{name}」（{space}）→ {chroma_path}")

    if args.probe:
        probe(store, args.probe, top_k)
    return 0


if __name__ == "__main__":
    sys.exit(main())

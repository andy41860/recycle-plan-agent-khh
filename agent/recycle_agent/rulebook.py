"""回收分類表 PDF 的格式約定與逐頁讀取（ingest 與測試共用）。

PDF 結構：
- 第 1 頁：封面，不進知識庫。
- 第 2 頁起：每類一頁，第一行固定為「【類別 NN／TT】類別名稱」。
- 欄位依序為「可回收物品：」「回收要領：」「不可回收：」（可省略），最後是「常見俗稱（…）：」與「・俗稱 → 原文品項」。
- 文件資訊含 /SourceName、/SourceURL、/Retrieved。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ALIAS_BULLET = "・"
MARKER_RE = re.compile(r"^【類別\s*(\d{2})／(\d{2})】\s*(.+)$")
# 一行開頭符合這些樣式就是新段落；否則視為排版換行，接回上一行。
PARA_START_RE = re.compile(
    r"^(【類別|(?:可回收物品|回收要領|不可回收|常見俗稱)[：（]|\d+\.(?!\d)|" + ALIAS_BULLET + ")"
)


class RulebookError(ValueError):
    pass


@dataclass(frozen=True)
class RulePage:
    category_id: int
    category: str
    page: int  # 1-based
    text: str


def normalize(text: str) -> str:
    """把 PDF 擷取文字的排版換行接回去，只保留段落換行。"""
    out: list[str] = []
    for line in (s.strip() for s in text.replace("\r", "").splitlines()):
        if not line:
            continue
        if not out or PARA_START_RE.match(line):
            out.append(line)
            continue
        prev = out[-1]
        sep = " " if _is_ascii_word(prev[-1]) and _is_ascii_word(line[0]) else ""
        out[-1] = prev + sep + line
    return "\n".join(out)


def _is_ascii_word(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def read_rule_pages(pdf_path: str | Path) -> tuple[dict[str, str], list[RulePage]]:
    """逐頁讀 PDF，回傳 (文件 metadata, 類別頁)。第 1 頁封面略過；之後任何一頁缺類別標記都視為錯誤。"""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    info = reader.metadata or {}
    meta = {
        "source_name": str(info.get("/SourceName", "")),
        "source_url": str(info.get("/SourceURL", "")),
        "retrieved": str(info.get("/Retrieved", "")),
    }
    pages: list[RulePage] = []
    totals: set[int] = set()
    for idx, page in enumerate(reader.pages, start=1):
        text = normalize(page.extract_text() or "")
        m = MARKER_RE.match(text.split("\n", 1)[0])
        if not m:
            if idx == 1:  # 封面
                continue
            raise RulebookError(f"第 {idx} 頁沒有類別標記，PDF 格式不符")
        totals.add(int(m.group(2)))
        pages.append(RulePage(int(m.group(1)), m.group(3).strip(), idx, text))

    if not pages:
        raise RulebookError(f"{pdf_path} 找不到任何「【類別 NN／TT】」頁面")
    if len(totals) != 1:
        raise RulebookError(f"類別總數標記不一致：{sorted(totals)}")
    total = totals.pop()
    ids = [p.category_id for p in pages]
    if ids != list(range(1, total + 1)):
        raise RulebookError(f"類別頁不完整或順序錯誤：預期 1..{total}，實際 {ids}")
    return meta, pages

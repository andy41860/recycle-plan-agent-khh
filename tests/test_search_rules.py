from langchain_core.documents import Document

from recycle_agent.tools.rag import NOT_FOUND, format_results

META = {
    "category_id": 3,
    "category": "塑膠容器、平板包材、其他塑膠",
    "page": 4,
    "source_name": "高雄市政府環境保護局 資源回收網「回收分類表」",
    "source_url": "https://recycle.ksepb.kcg.gov.tw/StaticPage/table?SiteDirectory=recycle",
    "retrieved": "2026-10-23",
}


def doc(**over):
    return Document(page_content="內文", metadata={**META, **over})


def test_all_below_threshold_is_exact_not_found():
    assert format_results([(doc(), 0.2), (doc(), 0.1)], 0.35) == NOT_FOUND == "查無資料"


def test_empty_results():
    assert format_results([], 0.35) == "查無資料"


def test_sorted_filtered_and_formatted():
    out = format_results([(doc(category_id=1, category="紙類", page=2), 0.4), (doc(), 0.52), (doc(page=9), 0.1)], 0.35)
    assert out.startswith("[1] 類別 03／塑膠容器、平板包材、其他塑膠（PDF 第 4 頁，相似度 0.52）\n內文")
    assert "[2] 類別 01／紙類（PDF 第 2 頁，相似度 0.40）" in out
    assert "[3]" not in out
    assert out.endswith(
        "資料來源：高雄市政府環境保護局 資源回收網「回收分類表」 "
        "https://recycle.ksepb.kcg.gov.tw/StaticPage/table?SiteDirectory=recycle（擷取日期 2026-10-23）"
    )

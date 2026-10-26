from pathlib import Path

import pytest

from recycle_agent.rulebook import RulebookError, normalize, read_rule_pages

PDF = Path(__file__).resolve().parent.parent / "data" / "kaohsiung_recycle_rules.pdf"

CATEGORIES = [
    (1, "紙類", 2),
    (2, "紙容器、紙餐具", 3),
    (3, "塑膠容器、平板包材、其他塑膠", 4),
    (4, "玻璃容器", 5),
    (5, "鐵、鋁容器", 6),
    (6, "舊衣", 7),
    (7, "乾電池(一次用、二次用電池(可充電電池))", 8),
    (8, "保麗龍", 9),
    (9, "家電物品", 10),
    (10, "資訊物品", 11),
    (11, "輪胎", 12),
    (12, "照明光源(含LED照明光源)", 13),
    (13, "汽車、機車、腳踏車", 14),
    (14, "大型家具", 15),
    (15, "其他類", 16),
]

CHUNK_LENGTHS = [250, 183, 687, 274, 149, 201, 283, 298, 175, 155, 119, 380, 194, 190, 147]

GOLDEN_FIRST = """【類別 01／15】紙類
可回收物品：各種紙製品，如報紙、紙箱、電腦報表紙、電話簿、牛皮紙袋、雜誌、書籍、紙類、瓦楞紙等。
回收要領：鋪平疊好，並加以捆綁後送交回收車，紙箱請拆開鋪平。
不可回收：塑膠光面廢紙、複寫紙、護貝及離型紙(貼紙底襯)、衛生紙、紙尿布。
常見俗稱（檢索輔助，非官方內容；→ 右側為本頁原文品項）：
・宅配紙箱、瓦楞紙箱 → 紙箱
・舊書、課本、參考書 → 書籍
・面紙、餐巾紙 → 衛生紙
・尿布、成人紙尿褲 → 紙尿布
・貼紙底紙 → 離型紙(貼紙底襯)
・護貝紙 → 護貝"""


@pytest.fixture(scope="module")
def book():
    return read_rule_pages(PDF)


def test_fifteen_pages_match_table(book):
    _, pages = book
    assert [(p.category_id, p.category, p.page) for p in pages] == CATEGORIES


def test_metadata(book):
    meta, _ = book
    assert meta["source_url"] == "https://recycle.ksepb.kcg.gov.tw/StaticPage/table?SiteDirectory=recycle"
    assert meta["retrieved"] == "2026-10-23"
    assert meta["source_name"] == "高雄市政府環境保護局 資源回收網「回收分類表」"


def test_first_chunk_golden(book):
    assert book[1][0].text == GOLDEN_FIRST


def test_chunk_lengths(book):
    assert [len(p.text) for p in book[1]] == CHUNK_LENGTHS


def test_no_garbled_characters(book):
    for p in book[1]:
        assert "�" not in p.text
        assert not any("" <= ch <= "" for ch in p.text), p.category


def test_english_line_breaks_get_space(book):
    text = book[1][11].text
    assert "(High Intensity Discharge, HID)" in text
    assert "(Light Emitting Diode ,LED)" in text


def test_normalize_cjk_join():
    assert normalize("可回收物品：紙\n張") == "可回收物品：紙張"


def test_normalize_ascii_word_gets_space():
    assert normalize("回收要領：Light\nEmitting") == "回收要領：Light Emitting"


def test_normalize_number_not_paragraph():
    assert normalize("寬度大於\n2.6公分") == "寬度大於2.6公分"


def test_normalize_numbered_item_is_paragraph():
    assert normalize("回收要領：\n1.拆開") == "回收要領：\n1.拆開"
    assert normalize("回收要領：甲乙\n1.拆開") == "回收要領：甲乙\n1.拆開"


def test_missing_marker_raises(tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.add_blank_page(200, 200)
    p = tmp_path / "bad.pdf"
    with p.open("wb") as f:
        w.write(f)
    with pytest.raises(RulebookError):
        read_rule_pages(p)

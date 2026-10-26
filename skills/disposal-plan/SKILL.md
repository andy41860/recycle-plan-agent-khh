---
name: disposal-plan
description: 整理丟棄計畫與回答收運時間。凡是要判斷「今天／今晚／下次什麼時候能丟」，或同時處理多個物品時使用；日期一律由腳本 next_pickup.py 計算。
---

# 丟棄計畫

## 步驟

1. 確認每個物品都已用 `search_rules` 查過（每次一個物品），複合材質已拆成部位（例如手搖杯拆成杯身與吸管）。
2. 確認已取得 `get_schedule` 與 `get_current_time` 的結果。
3. 收集需要收運的類別（只有「資源回收」「一般垃圾」兩種；特殊管道與查無資料的不要放進來），呼叫：

   `run_skill_script(skill="disposal-plan", script="next_pickup.py", input_json=...)`

   `input_json` 為 JSON 字串：

   ```json
   {"now": "<get_current_time 回傳的 datetime，原樣>",
    "schedule": {"<get_schedule 的完整回傳，原樣>": "..."},
    "categories": ["資源回收", "一般垃圾"]}
   ```

   不得自行推算星期或日期，一律以腳本輸出為準。`is_today` 為 true 代表今天還趕得上（收運時段進行中也算）。

4. 依以下分組輸出，沒有項目的分組省略：
   - **今天可丟**：物品／部位、結果、收運時段；資源回收物附回收要領。
   - **之後再丟**：同上，註明日期（含星期）與時段；腳本結果有 `note` 時一併說明。
   - **特殊管道**：說明知識庫原文指定的管道，不排入垃圾車時段。
   - **查無資料**：建議洽詢清潔隊；廚餘附 <https://recycle.ksepb.kcg.gov.tw/StaticPage/classification>。
   - **時刻表說明**：轉述 `notes`，並提醒國定假日、春節、颱風等異動，以「高雄市清潔車便民查詢系統」<https://kepbgps.kcg.gov.tw/> 或清潔隊公告為準。
5. 結尾附資料來源（分類：回收分類表名稱、網址、擷取日期；時間：時刻表 `source`）與「實際收運以清潔隊公告為準」。

## 只問收運時間

同樣要執行 `next_pickup.py`（即使只問「今天有沒有收」），再用簡短格式回答：哪一天（含星期）、幾點到幾點、是否今天。若今天不收或時段已過，直接給下一個收運日。

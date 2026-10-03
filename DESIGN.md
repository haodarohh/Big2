# 大老二 CLI — 設計文件

## 技術棧
- 語言：Python
- 執行方式：`uv run big2`（CLI）或 `uv run big2 --server-mode`（瀏覽器版，uv 專案，`pyproject.toml` 管理相依套件）
- HTTP client（呼叫 jev）：`requests`
- Web server：Flask，靜態檔案（`src/big2/static/index.html`/`app.js`/`style.css`）+ 幾個 JSON API
- AI 對手：OpenRouter `POST https://openrouter.ai/api/alpha/decisions`，model `typesafe/jev-1.13`
- API key：環境變數 `OPENROUTER_API_KEY`

## 架構：CLI 與瀏覽器版共用的部分
- `game.py` 的 `GameEngine`（誰的回合、目前要求的牌型、一輪全過牌後控制權回到最後出牌者、有人出完牌）是兩種介面共用的核心狀態機，`apply(move)` 是唯一的變動入口
- CLI（`run_game`）直接在 `GameEngine` 上為每個座位（含真人）阻塞呼叫 `Controller.choose_move`
- 瀏覽器版（`web.py`）不會對真人座位呼叫 `choose_move`（那會卡在 `input()`）：真人的出牌由 HTTP request 提供，經 `validate_move` 驗證合法性後直接 `GameEngine.apply`；AI 座位則用 `run_ai_batch` 連續跑，直到又輪到真人或遊戲結束才回傳
- 兩種介面都用同一個 `AIController`（同一套呼叫 jev、重試、fallback 的邏輯）與同一個 `GameLogger`（`logs/game-<timestamp>.jsonl`）

## 瀏覽器版 API（單一全域對局，無 session id）
- `GET /`：回應 `static/index.html`
- `POST /api/new_game` `{players, human}`：開新局，回傳到「輪到真人（或遊戲結束）」為止的事件記錄 + 當前狀態
- `POST /api/move` `{indices}`：真人出牌（`indices` 是目前手牌排序後的 1-based 編號，空陣列＝過牌），回傳這手牌之後連續 AI 回合的事件記錄 + 當前狀態
- `GET /api/state`：目前狀態快照（給重新整理頁面用，不含事件記錄）
- 前端拿到的事件記錄會逐筆播放動畫，而不是瞬間跳到最終狀態；為什麼用「同步算完整批才回傳」而不是即時串流，見 [docs/adr/0001-sync-request-response-for-web-turns.md](docs/adr/0001-sync-request-response-for-web-turns.md)

## 規則（台灣常見版本）
- 單張大小：3 最小、2 最大；花色破同點數的平手（黑桃>紅心>方塊>梅花）
- 對子大小：先比點數，點數相同時比對子中花色較大的那張（同點數的兩副對子可能同時存在，因為一個點數有4張牌）
- 2 不可用於順子
- 五張牌型排序（大到小）：同花順 > 鐵支(四張+1 拖牌) > 葫蘆 > 順子
- 沒有「同花」這個牌型：五張同花色但不連續，不是合法牌型，不能出
- 出牌只能被「相同張數」的牌型壓過（例如對子只能被對子壓），沒有「鐵支任何時候都能炸」的百搭規則
- 開局：持有梅花3的玩家先出，且第一手必須包含梅花3
- 過牌：一輪內其他家全部過牌後，控制權回到最後出牌者，可自由開新牌型

## 人數與發牌
- 2~4 人可設定，真人玩家可設為 0 或 1 人（0 = 純觀戰，其餘皆 AI），其餘座位皆為 AI
- 4 人：每人 13 張
- 3 人：每人 17 張，剩 1 張移除不用
- 2 人：每人 26 張

## 比賽制度
- 單局制：有人出完手牌，遊戲結束並顯示贏家，不做跨局計分

## AI 出牌邏輯
1. 每回合窮舉該 AI 手牌中「所有有效牌型組合」：任意單張、任意能組成的有效對子/三條/五張牌型（同花順/鐵支/葫蘆/順子）+ 一個「過牌」選項
2. **不預先篩選這些組合是否壓得過場上目前的牌**——連同場上狀態（目前要求的牌型/張數、上家出了什麼、各家剩餘張數等）一併寫進送給 jev 的 `state`，讓 jev 自行判斷該選哪個選項
   - `GameEngine.history` 保留整局出牌／過牌事件，包含真人回合與勝利回合；一輪全過牌不會清空歷史
   - 每次選牌前建立 `TurnContext` 公開快照：座位順序、自己座位、最新剩餘張數、最後出牌者、完整歷史；快照不含對手手牌或可修改的引擎參照
   - `state` 保留完整自己的手牌，讓模型自行判斷拆牌代價與是否繼續壓牌；程式不評分或推薦候選。過牌不能當作對方確定沒有能壓牌的證據
   - `AIController.personality` 預設 `balanced`，可從程式設定 `conservative` 或 `aggressive`；人格只改策略提示，不改候選或合法性判斷，不新增介面選單
3. 用 `choice` 類型的 decision 呼叫 jev，`criteria` 就是步驟 1 窮舉出的選項
4. 收到 jev 的選擇後，程式驗證是否真的合法（張數/牌型/大小是否真能壓過場上要求）
   - 合法：出牌
   - 不合法：把具體原因（例如「這是對子，但目前必須出三條以上」）回饋給 jev，重試，最多 5 次
   - 5 次仍失敗：自動過牌；若當時必須主動出牌（不能過），則自動出目前手牌中最小的合法單張

## AI 公開局勢介面

1. `GameEngine.apply` 保存成功出牌與過牌的 `TurnEvent`，包含真人與勝利回合。一輪全過牌只重置出牌條件，不清空 `history`；新局歷史為空。
2. `GameEngine.turn_context()` 建立 frozen `TurnContext`：
   - `seat_names: tuple[str, ...]`：座位與出牌順序。
   - `remaining: tuple[int, ...]`：與座位對齊的目前張數。
   - `current_seat: int`：選牌者座位。
   - `last_play_seat: int | None`：開局為 `None`；之後保留最後出牌者，包含一輪全過牌後。
   - `history: tuple[str, ...]`：依序描述玩家、出牌／過牌、公開牌型與牌。
3. `Controller.choose_move` 接受尾端可選參數 `context: TurnContext | None = None`。HumanController 接受但不使用；AIController 將快照、自己的完整手牌與人格寫入 state。
4. `run_game` 與 `run_ai_batch` 每次選牌前傳入最新快照，讓真人事件與跨批次歷史都保留。

快照只含不可變的公開值，不持有引擎、其他玩家手牌或可修改的事件參照。直接以原有四參數呼叫 AIController 仍可使用；自訂 controller 若供遊戲入口呼叫，需接受 `context` 參數。

### 人格與策略約束

- `balanced`：衡量保留組合、主導權與出牌進度。
- `conservative`：較重視保牌與避免不必要的追壓。
- `aggressive`：較願意花大牌搶主導權與加速出完。

人格文字集中於 game.py；無效設定在建構時拋出 `ValueError`。人格只影響提示，不改 options、候選生成、合法性判斷或重試。

共通提示要求模型自行衡量拆牌後的剩牌結構，參考公開歷史與對手張數；能直接出完或對手即將出完時提高緊迫性。過牌不證明對手沒有能壓的牌。規則摘要維持同張數互壓、無普通同花、2 不進順子，以及既有牌型與點數／花色排序。

## 記錄
- 每場遊戲存一份 `logs/game-<timestamp>.jsonl`
- 每次 AI 呼叫記一行 JSON：時間戳、玩家、提供給 jev 的選項、jev 原始回覆、是否為重試/第幾次重試

## 人類玩家介面
- 顯示手牌並編號，如 `[1]3♦ [2]5♠ ...`
- 輸入編號組合出牌，如 `1 3 5`；輸入空白或 `p` 表示過牌

## 啟動參數
- CLI flag 指定人數與真人座位數，如 `uv run big2 --players 4 --human 1`
- 未指定時互動式詢問

## 明確不做的部分
- 沒有離線/規則型備援 AI（AI 一定呼叫 jev；單元測試中對 API 呼叫做 mock，不算是產品功能）
- 沒有存檔/讀檔（單一 session 打完即結束）
- 沒有跨局計分

## 已知風險
- 完整歷史與既有大候選集增加模型輸入負擔；依需求不截斷歷史或裁切候選。
- 測試證明資料與策略提示正確傳遞，無法保證模型遵循程度或勝率提升。
- 網頁路徑透過實際使用的 `run_ai_batch` 驗證；未測 live browser 或真實模型對局。
- `typesafe/jev-1.13` 為 OpenRouter alpha 服務（`/api/alpha/decisions`），且回傳為機率式選擇，非保證選中最優解；重試機制與自動過牌 fallback 是為了避免遊戲卡死

## AI 局勢與人格的測試驗證

測試實際執行引擎、控制器、兩個遊戲入口與暫存 log；只在外部 `request_choice` 邊界使用 stub，不需 API key 或 live server。

| 驗收項目 | tests/test_game.py 測試 |
| --- | --- |
| 完整公開資訊與隱藏牌邊界 | `test_cli_ai_receives_public_context` |
| 跨輪歷史、快照獨立、新局與勝利事件 | `test_history_survives_trick_reset_and_snapshot_is_independent` |
| 真人事件、跨批次歷史與輪到真人時停止 | `test_batch_context_includes_human_turns_and_previous_batches` |
| 人格只改提示、拒絕無效設定 | `test_personalities_change_guidance_only`、`test_unknown_personality_is_rejected` |
| 不合法選項回饋、重試及過牌 | `test_illegal_choice_retries_with_same_context`、`test_illegal_choice_can_retry_to_pass` |
| 服務失敗後過牌或最小合法單張 | `test_following_falls_back_to_pass_after_errors`、`test_opening_falls_back_to_three_of_clubs_after_errors`、`test_leading_falls_back_to_smallest_single_after_errors` |

實作前曾以 `test_cli_ai_receives_public_context` 重現缺少公開資訊：`1 failed, 3 deselected`，舊 state 缺少 `Your seat: 0 (P0)`。原實作階段的 game 測試 13 個、全套 33 個通過；後續新增 CLI 測試後，2026-10-03 重新驗證：

```sh
.venv/bin/python -m pytest tests/test_game.py -q
# 13 passed
.venv/bin/python -m pytest -q
# 36 passed
GIT_HOOKS_SKIP=1 git diff --check
GIT_HOOKS_SKIP=1 git diff --cached --check
# 兩者皆 exit 0，無輸出
```

測試環境使用 Python 3.12.14 與 uv.lock 的既有依賴。沒有剩餘實作阻擋。

# Big2

![Big2 瀏覽器版遊玩畫面](docs/images/gameplay.jpg)

大老二（台灣規則），2~4 人，真人玩家 0 或 1 人，其餘座位由 [jev](https://openrouter.ai/typesafe/jev-1.13)（OpenRouter 上的 decision model）擔任 AI 對手。有命令列版跟瀏覽器版，共用同一套規則與 AI 邏輯。完整規則與架構設計見 [DESIGN.md](DESIGN.md)。

## 安裝需求
- [uv](https://docs.astral.sh/uv/)
- OpenRouter API key（放在環境變數 `OPENROUTER_API_KEY`）— 只有真的要讓 AI 出牌時才需要，AI 每次出牌都會呼叫一次 jev API 並產生費用

### 改用本機 AI 伺服器（選用）
預設連 OpenRouter 上的 jev。設定下列環境變數，可改把同樣格式的請求送到本機的 `rapid-mlx system-one`（laya）伺服器；此時不需要 `OPENROUTER_API_KEY`：
```sh
export BIG2_AI_URL=http://127.0.0.1:8000/v1/systemone
export BIG2_AI_MODEL=laya   # 選填；不設就不送 model，由伺服器用預設值
```
若同時設了 `OPENROUTER_API_KEY`，它會一併送到 `BIG2_AI_URL` 指向的伺服器，請只連你信任的位址。

## 執行（命令列版）
```sh
export OPENROUTER_API_KEY=sk-or-...
uv run big2
```

啟動時會互動式詢問人數與真人玩家人數，也可以用參數直接指定：
```sh
uv run big2 --players 4 --human 1   # 4 人局，1 位真人 + 3 個 AI
uv run big2 --players 2 --human 0   # 2 人局，純觀戰（AI 對打）
```

## 執行（瀏覽器版）
```sh
export OPENROUTER_API_KEY=sk-or-...
uv run big2 --server-mode            # 預設監聽 http://127.0.0.1:8765/
uv run big2 --server-mode --host 0.0.0.0 --port 9000
```
啟動後打開印出來的網址即可開始，人數與真人玩家人數改在網頁上選。同一時間只支援一局（單一全域對局，沒有 session），適合一個人在自己電腦上玩，不是多人連線對戰。

## 測試
```sh
uv run pytest
```
單元測試只涵蓋牌型/發牌/回合邏輯，不會呼叫真的 jev API。

## 牌局紀錄
每場遊戲會在 `logs/game-<timestamp>.jsonl` 留下每一次 AI 呼叫的請求選項、jev 回覆、是否合法/第幾次重試，方便之後檢討 AI 表現。AI 單回合最多重試 10 次，用完會記錄改用的備案（過牌或出最小單張）；遊戲打完時會再寫一筆 `ai_stats`，統計呼叫總數、失敗次數與用完重試的回合數。

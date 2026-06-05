## run

server: `uv run python app.py`

client:
```
uv run python test_webhook.py mention   # 模擬 @bot
uv run python test_webhook.py join      # 模擬入群
uv run python test_webhook.py fever     # 模擬「開始輔導」完整三問流程
```

token check:
```
curl -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN" https://api.line.me/v2/bot/info
```

tests:
```
uv run pytest tests/
```

---

## features

### icebreaker cards
入群自動送破冰卡片（A/B/C 三種風格，`ICEBREAKER_STYLE` 切換）。

### fever-bot coaching
在群組輸入 **`開始輔導`** 觸發一對一輔導流程：
1. Bot 從 10 題題庫隨機出第一題。
2. 學員回答 → Bot 用 LLM 動態生成第二題（依上下文）。
3. 學員回答 → Bot 生成第三題。
4. 學員回答 → Bot 送出個人化建議 🎯。

輸入 **`取消`** 或 **`結束輔導`** 可隨時中止。

### @mention echo
@Bot 任意文字 → Bot 回傳去掉 mention 後的內容。

---

## env vars

| 變數 | 必填 | 說明 |
|---|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | LINE Messaging API token |
| `LINE_CHANNEL_SECRET` | ✅ | LINE webhook 驗簽密鑰 |
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API key |
| `OPENROUTER_MODEL` | — | LLM 模型，預設 `moonshotai/kimi-k2` |
| `SESSION_TTL_SECONDS` | — | Session 逾時秒數，預設 1800 |
| `FEVER_DATA_SOURCE` | — | 課程資源 .txt 路徑（留空用純 LLM） |
| `ICEBREAKER_STYLE` | — | A / B / C，預設 A |

複製 `.env.example` 為 `.env` 並填入真實值。

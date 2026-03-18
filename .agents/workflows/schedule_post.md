---
description: 予約投稿を登録する
---

# 予約投稿ワークフロー

// turbo-all

## 手順

1. `/create_post` ワークフローでテキストと画像を準備する

2. ユーザーに予約日時を確認する（`Asia/Tokyo`）

3. 予約投稿を登録する
```bash
curl -s -X POST http://localhost:8000/api/posts/schedule \
  -H "Content-Type: application/json" \
  -d '{"account": "{account_name}", "text": "投稿テキスト", "media": [], "scheduled_at": "2026-03-18T12:00:00"}' | python3 -m json.tool
```

4. 予約状況を確認する
```bash
curl -s "http://localhost:8000/api/posts/scheduled?account={account_name}" | python3 -m json.tool
```

5. 予約をキャンセルする場合
```bash
curl -s -X DELETE "http://localhost:8000/api/posts/scheduled/{post_id}?account={account_name}" | python3 -m json.tool
```

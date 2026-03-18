---
description: X投稿を作成する（テキスト + 画像）
---

# X投稿作成ワークフロー

// turbo-all

## 手順

1. ユーザーから投稿テーマ・方向性を聞く

2. 対象アカウント名を確認する
```bash
curl -s http://localhost:8000/api/accounts | python3 -m json.tool
```

3. アカウントの `character.md` を読む
```bash
cat accounts/{account_name}/character.md
```

4. `idea_notes/` からネタを確認する（任意）
```bash
ls accounts/{account_name}/idea_notes/
```

5. 280文字以内で投稿テキストを作成する
   - `character.md` のトーン・スタイルに従う
   - 文字数をスクリプトで確認:
```bash
python3 -c "from src.utils import count_characters; print(count_characters('投稿テキスト'))"
```

6. 画像が必要な場合、`generate_image` ツールで画像を生成し、JPEG/PNGとして保存する
   - ファイル名は `{ポストID}_{連番}.jpg` 形式
   - 保存先: `accounts/{account_name}/images/`

7. ユーザーに投稿内容を提示して確認を取る
   - テキスト全文
   - 画像（あれば）
   - 対象アカウント名を明示

8. ユーザーの指示に従い投稿する

   即時投稿の場合:
```bash
curl -s -X POST http://localhost:8000/api/posts/publish \
  -H "Content-Type: application/json" \
  -d '{"account": "{account_name}", "text": "投稿テキスト", "media": []}' | python3 -m json.tool
```

   予約投稿の場合:
```bash
curl -s -X POST http://localhost:8000/api/posts/schedule \
  -H "Content-Type: application/json" \
  -d '{"account": "{account_name}", "text": "投稿テキスト", "media": [], "scheduled_at": "2026-03-18T12:00:00"}' | python3 -m json.tool
```

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

6. **【重要】記事シェア投稿かどうかを判定する**
   - `idea_notes/prisma_article_promotion.md` の「記事シェア」セクションに該当するネタか確認
   - 記事シェアの場合は **必ず `self_reply_text` を設定する**（省略厳禁）
   - フォーマット:
   ```
   記事の詳細はこちら
   https://prisma.aqsh.co.jp/articles/{slug}/?utm_source=twitter&utm_medium=social&utm_campaign=article_share&utm_content={YYYYMMDD}

   【無料】性格＆適性診断
   https://prisma.aqsh.co.jp/
   ```
   - **ドメインは `prisma.aqsh.co.jp`**（`works.aqsh.co.jp` ではない）
   - **URLは投稿本文に絶対に含めない**（Xアルゴリズムがリーチを下げるため）

7. 画像が必要な場合、`generate_image` ツールで画像を生成し、JPEG/PNGとして保存する
   - ファイル名は `{ポストID}_{連番}.jpg` 形式
   - 保存先: `accounts/{account_name}/images/`

8. ユーザーに投稿内容を提示して確認を取る
   - テキスト全文
   - 画像（あれば）
   - 対象アカウント名を明示
   - **記事シェアの場合: `self_reply_text` の内容も明示**

9. ユーザーの指示に従い投稿する

   即時投稿の場合:
```bash
curl -s -X POST http://localhost:8000/api/posts/publish \
  -H "Content-Type: application/json" \
  -d '{"account": "{account_name}", "text": "投稿テキスト", "media": [], "self_reply_text": "リプライテキスト"}' | python3 -m json.tool
```

   予約投稿の場合:
```bash
curl -s -X POST http://localhost:8000/api/posts/schedule \
  -H "Content-Type: application/json" \
  -d '{"account": "{account_name}", "text": "投稿テキスト", "media": [], "scheduled_at": "2026-03-20T12:00:00", "self_reply_text": "リプライテキスト"}' | python3 -m json.tool
```

   ※ `self_reply_text` は記事シェア以外の投稿では省略可（config.json のデフォルトが使われる）

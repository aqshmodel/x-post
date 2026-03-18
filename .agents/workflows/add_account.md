---
description: 新しいXアカウントを追加する
---

# アカウント追加ワークフロー

// turbo-all

## 前提
- X Developer Portal でアプリにOAuthトークンを発行済み

## 手順

1. アカウント名を決める（英数字+アンダースコア、小文字推奨）

2. ディレクトリを作成する
```bash
cd /Users/tsukadatakahiro/Python/app/x_post
mkdir -p accounts/{account_name}/{drafts,scheduled,posted,images,analytics/daily,analytics/monthly,idea_notes,logs}
```

3. `config.json` を作成する
```bash
cat > accounts/{account_name}/config.json << 'EOF'
{
  "account_name": "{account_name}",
  "display_name": "表示名",
  "x_username": "@username",
  "x_user_id": "",
  "active": true,
  "posting_rules": {
    "max_posts_per_day": 10,
    "default_language": "ja",
    "auto_analytics": true,
    "max_char_count": 280
  },
  "created_at": "2026-03-18T09:00:00+09:00"
}
EOF
```

4. `character.md` を作成する（ユーザーと対話しながらキャラ設定を決める）

5. `.env` に環境変数を追加する
```
X_{ACCOUNT_NAME}_ACCESS_TOKEN=xxxxxxxx
X_{ACCOUNT_NAME}_ACCESS_TOKEN_SECRET=xxxxxxxx
X_{ACCOUNT_NAME}_BEARER_TOKEN=xxxxxxxx
```

6. FastAPIサーバーを再起動する
```bash
# 起動中のサーバーを停止し、再起動
```

7. 動作確認
```bash
curl -s http://localhost:8000/api/accounts | python3 -m json.tool
```

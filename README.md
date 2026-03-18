# X投稿管理システム

Antigravity エージェントを使い、ローカル環境からX（旧Twitter）への投稿を効率的に管理・運用するシステム。

## 特徴

- 🤖 **エージェント駆動**: Antigravityとの対話でX運用を完結
- 👥 **マルチアカウント**: 1アプリ × 複数OAuthトークンで安全に管理
- ⏰ **予約投稿**: APSchedulerによるローカル予約投稿
- 📊 **データ分析**: エンゲージメントデータの自動取得・蓄積・改善提案
- 💰 **コスト追跡**: API利用コストの自動記録・月別履歴
- 🌙 **管理UI**: ダークモードの5画面Web UI

## 技術スタック

| 技術 | 用途 |
|---|---|
| Python 3.x | 全体 |
| FastAPI | REST API + 管理UI |
| tweepy v4.x | X API v2 |
| APScheduler | 予約投稿 |
| Jinja2 + Chart.js | 管理UI |
| Pydantic | データモデル |

## セットアップ

```bash
# 依存パッケージ
pip install -r requirements.txt

# 環境変数
cp .env.example .env
# .env にX APIキーを設定

# サーバー起動
python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## アカウント追加

```bash
# ディレクトリ作成
mkdir -p accounts/{name}/{drafts,scheduled,posted,images,analytics/daily,analytics/monthly,idea_notes,logs}

# config.json, character.md を作成
# .env にトークンを追加
# サーバー再起動
```

## ワークフロー

| コマンド | 説明 |
|---|---|
| `/create_post` | 投稿作成（テキスト + 画像） |
| `/schedule_post` | 予約投稿登録 |
| `/add_account` | 新アカウント追加 |
| `/analyze_posts` | 分析データ取得・改善提案 |

## API エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/health` | ヘルスチェック |
| GET | `/api/accounts` | アカウント一覧 |
| POST | `/api/posts/publish` | 即時投稿 |
| POST | `/api/posts/schedule` | 予約投稿 |
| GET | `/api/posts/posted?account={name}` | 投稿履歴 |
| GET | `/api/analytics/{account}` | 分析サマリ |
| GET | `/` | 管理UIダッシュボード |

## ライセンス

Private

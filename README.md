# X投稿管理システム

Antigravity エージェントを使い、ローカル環境からX（旧Twitter）への投稿を効率的に管理・運用するシステム。

## 特徴

- **エージェント駆動**: Antigravityとの対話でX運用を完結
- **マルチアカウント**: 1アプリ x 複数OAuthトークンで安全に管理
- **予約投稿**: APSchedulerによるローカル予約投稿（分単位の精度）
- **自動リプライ**: メンション検知 → セルフリプライ/いいねの自動実行
- **データ分析**: エンゲージメントデータの自動取得・蓄積・改善提案
- **コスト追跡**: API利用コストの自動記録・月別アーカイブ
- **管理UI**: ダークモードの6画面Web UI（ダッシュボード / 予約一覧 / 投稿履歴 / 分析 / コスト / 投稿編集）

## 技術スタック

| 技術 | 用途 |
|---|---|
| Python 3.x | ランタイム |
| FastAPI | REST API + 管理UI |
| tweepy v4.x | X API v2（OAuth 1.0a + Bearer Token） |
| APScheduler | 予約投稿 / 月次アーカイブ / 自動リプライ |
| Jinja2 + Chart.js | 管理UI テンプレート + グラフ描画 |
| Pydantic | データモデル / バリデーション |

## ディレクトリ構成

```
x_post/
├── src/
│   ├── main.py          # FastAPIサーバー / ルーティング
│   ├── x_client.py      # X API クライアント（投稿・メディア・分析・リプライ）
│   ├── scheduler.py     # APScheduler ジョブ管理
│   ├── analytics.py     # 分析データ集計 / 月次アーカイブ
│   ├── auto_reply.py    # 自動リプライ / メンション処理
│   ├── config.py        # 設定 / アカウントローダー
│   ├── models.py        # Pydantic モデル定義
│   └── utils.py         # ユーティリティ（ファイルI/O・ログ・画像変換）
├── templates/           # Jinja2 HTMLテンプレート（7ファイル）
├── static/              # CSS / favicon
├── accounts/            # アカウント別データ（投稿・設定・ログ）
├── docs/                # 仕様書 / ワークフロー / lessons.md
├── .agents/workflows/   # Antigravity ワークフロー定義
├── .env                 # 環境変数（APIキー・トークン）
└── requirements.txt     # 依存パッケージ
```

## セットアップ

```bash
# 依存パッケージ
pip install -r requirements.txt

# 環境変数
cp .env.example .env
# .env にX APIキー・トークンを設定

# サーバー起動
python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## アカウント追加

```bash
# ディレクトリ作成
mkdir -p accounts/{name}/{drafts,scheduled,posted,images,analytics/daily,analytics/monthly,idea_notes,logs}

# config.json, character.md を作成
# .env にトークンを追加（API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET, BEARER_TOKEN）
# サーバー再起動
```

## ワークフロー

| コマンド | 説明 |
|---|---|
| `/create_post` | 投稿作成（テキスト + 画像生成） |
| `/schedule_post` | 予約投稿登録 |
| `/add_account` | 新アカウント追加 |
| `/analyze_posts` | 分析データ取得・改善提案 |

## API エンドポイント

### アカウント

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/health` | ヘルスチェック |
| GET | `/api/accounts` | アカウント一覧 |
| GET | `/api/accounts/{name}` | アカウント詳細 |

### 投稿

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/posts/draft` | 下書き保存 |
| POST | `/api/posts/publish` | 即時投稿 |
| POST | `/api/posts/schedule` | 予約投稿 |
| GET | `/api/posts/drafts` | 下書き一覧 |
| GET | `/api/posts/scheduled` | 予約一覧 |
| GET | `/api/posts/posted` | 投稿履歴 |
| PUT | `/api/posts/{status}/{id}` | 投稿編集 |
| DELETE | `/api/posts/scheduled/{id}` | 予約キャンセル |
| POST | `/api/posts/retry/{id}` | 失敗リトライ |

### 分析 / コスト

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/analytics/{account}` | 月次分析サマリ |
| GET | `/api/analytics/{account}/{post_id}` | 個別投稿メトリクス |
| POST | `/api/analytics/{account}/fetch` | X APIから最新メトリクス取得 |
| GET | `/api/cost-history/{account}` | コスト履歴 |

### 管理UI

| パス | 画面 |
|---|---|
| `/` | ダッシュボード |
| `/ui/scheduled` | 予約一覧 |
| `/ui/history` | 投稿履歴 |
| `/ui/analytics` | 分析 |
| `/ui/cost-history` | コスト履歴 |
| `/ui/post/{status}/{id}` | 投稿編集 |

## ライセンス

Private

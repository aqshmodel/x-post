"""
X投稿システム 設定管理
仕様: docs/仕様/03_アカウント管理.md, 07_API仕様.md
"""

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from src.models import Account

# .env 読み込み
load_dotenv()

# パス定数
BASE_DIR = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = BASE_DIR / "accounts"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def list_accounts() -> list[str]:
    """accounts/ 配下のアカウント名一覧を取得（hidden を除外）"""
    if not ACCOUNTS_DIR.exists():
        return []
    accounts = []
    for d in ACCOUNTS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        # hidden チェック
        config_path = d / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if config.get("hidden", False):
                continue
        accounts.append(d.name)
    return accounts


def load_account(account_name: str) -> Account:
    """アカウントの config.json を読み込み Account モデルを返す"""
    config_path = ACCOUNTS_DIR / account_name / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"アカウント '{account_name}' の config.json が見つかりません: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Account(**data)


def is_account_active(account_name: str) -> bool:
    """アカウントが active かどうか"""
    account = load_account(account_name)
    return account.active


def get_env_credentials(account_name: str) -> dict:
    """
    アカウント名から環境変数名を自動生成し、認証情報を取得
    命名規則: X_{ACCOUNT_NAME(大文字)}_{KEY}
    """
    env_prefix = f"X_{account_name.upper()}"
    credentials = {
        "api_key": os.getenv("X_APP_API_KEY"),
        "api_secret": os.getenv("X_APP_API_SECRET"),
        "access_token": os.getenv(f"{env_prefix}_ACCESS_TOKEN"),
        "access_token_secret": os.getenv(f"{env_prefix}_ACCESS_TOKEN_SECRET"),
        "bearer_token": os.getenv(f"{env_prefix}_BEARER_TOKEN"),
    }

    # 必須キーの検証
    missing = [k for k, v in credentials.items() if v is None and k not in ("bearer_token",)]
    if missing:
        raise ValueError(
            f"アカウント '{account_name}' の認証情報が不足しています。"
            f"環境変数を確認してください: {', '.join(missing)}"
        )

    return credentials


def get_account_dir(account_name: str) -> Path:
    """アカウントのディレクトリパスを取得"""
    account_dir = ACCOUNTS_DIR / account_name
    if not account_dir.exists():
        raise FileNotFoundError(f"アカウントディレクトリが見つかりません: {account_dir}")
    return account_dir


def get_posts_dir(account_name: str, status: str) -> Path:
    """アカウント内のステータス別ディレクトリパスを取得"""
    return get_account_dir(account_name) / status


def ensure_account_dirs(account_name: str) -> Path:
    """アカウントの全サブディレクトリを作成（アカウント追加時）"""
    account_dir = ACCOUNTS_DIR / account_name
    subdirs = [
        "drafts",
        "scheduled",
        "posted",
        "images",
        "analytics/daily",
        "analytics/monthly",
        "idea_notes",
        "logs",
    ]
    for subdir in subdirs:
        (account_dir / subdir).mkdir(parents=True, exist_ok=True)
    return account_dir


def load_character(account_name: str) -> Optional[str]:
    """アカウントの character.md を読み込む"""
    char_path = get_account_dir(account_name) / "character.md"
    if not char_path.exists():
        return None
    with open(char_path, "r", encoding="utf-8") as f:
        return f.read()

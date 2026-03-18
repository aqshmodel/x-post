"""
X投稿システム フォロワー増減トラッキング
日次でフォロワー数を記録し、推移データを提供する。
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.config import get_account_dir
from src.utils import write_log


FOLLOWERS_FILE = "analytics/followers.json"


def _get_followers_path(account_name: str) -> Path:
    """フォロワー記録ファイルのパスを返す"""
    return get_account_dir(account_name) / FOLLOWERS_FILE


def fetch_follower_count(account_name: str) -> Optional[dict]:
    """
    X APIからフォロワー数を取得。
    戻り値: {"followers": int, "following": int} or None
    """
    from src.x_client import get_bearer_client
    from src.config import load_account

    client = get_bearer_client(account_name)
    if client is None:
        write_log(account_name, "フォロワー取得失敗: Bearer Token未設定", level="ERROR")
        return None

    acc = load_account(account_name)
    user_id = acc.x_user_id

    if not user_id:
        write_log(account_name, "フォロワー取得失敗: x_user_id未設定", level="ERROR")
        return None

    try:
        user = client.get_user(
            id=user_id,
            user_fields=["public_metrics"],
        )
        if user.data:
            metrics = user.data.public_metrics
            result = {
                "followers": metrics.get("followers_count", 0),
                "following": metrics.get("following_count", 0),
            }
            write_log(
                account_name,
                f"フォロワー数取得: followers={result['followers']}, following={result['following']}",
            )
            return result
    except Exception as e:
        write_log(account_name, f"フォロワー取得失敗: {e}", level="ERROR")

    return None


def save_follower_snapshot(account_name: str) -> Optional[dict]:
    """
    フォロワー数を取得して日次スナップショットを保存。
    同日のデータがあれば上書き。
    """
    counts = fetch_follower_count(account_name)
    if counts is None:
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = {
        "date": today,
        "followers": counts["followers"],
        "following": counts["following"],
    }

    # 既存データ読み込み
    history = load_follower_history(account_name, days=None)

    # 同日データがあれば上書き
    history = [h for h in history if h.get("date") != today]
    history.append(snapshot)
    history.sort(key=lambda x: x["date"])

    # 保存
    path = _get_followers_path(account_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    write_log(account_name, f"フォロワースナップショット保存: {today}")
    return snapshot


def load_follower_history(
    account_name: str, days: Optional[int] = 30
) -> list[dict]:
    """
    フォロワー履歴を読み込み。
    days=None で全件、days=N で直近N日分。
    """
    try:
        path = _get_followers_path(account_name)
    except FileNotFoundError:
        return []
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        history = json.load(f)

    if days is not None:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        history = [h for h in history if h.get("date", "") >= cutoff]

    return history


def get_follower_summary(account_name: str) -> dict:
    """
    ダッシュボード用のフォロワーサマリを返す。
    {
      "current": 1234,
      "change_1d": +5,
      "change_7d": +30,
      "history_7d": [{"date": "...", "followers": ...}, ...]
    }
    """
    history = load_follower_history(account_name, days=30)
    if not history:
        return {"current": None, "change_1d": 0, "change_7d": 0, "history_7d": []}

    latest = history[-1]
    current = latest.get("followers", 0)

    # 前日比
    change_1d = 0
    if len(history) >= 2:
        change_1d = current - history[-2].get("followers", current)

    # 7日前比
    change_7d = 0
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    for h in history:
        if h["date"] <= seven_days_ago:
            change_7d = current - h.get("followers", current)

    # 直近7日分
    history_7d = history[-7:] if len(history) >= 7 else history

    return {
        "current": current,
        "change_1d": change_1d,
        "change_7d": change_7d,
        "history_7d": history_7d,
    }

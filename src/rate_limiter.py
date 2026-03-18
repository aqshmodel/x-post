"""
X投稿システム API レートリミット監視
tweepy レスポンスヘッダーからレートリミット情報を記録し、
残量チェック・ダッシュボード表示・超過時の自動停止を提供する。
"""

import time
from typing import Optional


# グローバルキャッシュ: { account: { endpoint: { remaining, limit, reset } } }
_rate_limits: dict[str, dict[str, dict]] = {}


class RateLimitError(Exception):
    """レートリミット超過時に発出"""
    pass


def update_rate_limit(
    account_name: str,
    endpoint: str,
    remaining: Optional[int] = None,
    limit: Optional[int] = None,
    reset: Optional[int] = None,
) -> None:
    """レスポンスヘッダー情報からレートリミットを更新"""
    if account_name not in _rate_limits:
        _rate_limits[account_name] = {}

    _rate_limits[account_name][endpoint] = {
        "remaining": remaining,
        "limit": limit,
        "reset": reset,
        "updated_at": int(time.time()),
    }


def update_from_response(account_name: str, endpoint: str, response) -> None:
    """tweepy レスポンスオブジェクトからレートリミットを抽出・更新"""
    if response is None:
        return

    # tweepy.Response にはヘッダーが含まれない場合がある
    # requests.Response のヘッダーを探す
    headers = None
    if hasattr(response, "headers"):
        headers = response.headers
    elif hasattr(response, "response") and hasattr(response.response, "headers"):
        headers = response.response.headers

    if headers is None:
        return

    remaining = headers.get("x-rate-limit-remaining")
    limit = headers.get("x-rate-limit-limit")
    reset = headers.get("x-rate-limit-reset")

    update_rate_limit(
        account_name,
        endpoint,
        remaining=int(remaining) if remaining else None,
        limit=int(limit) if limit else None,
        reset=int(reset) if reset else None,
    )


def check_rate_limit(account_name: str, endpoint: str) -> bool:
    """
    レートリミットをチェック。
    残量0なら RateLimitError を発出。
    残量10%以下なら True (WARNING) を返す。
    """
    info = get_endpoint_status(account_name, endpoint)
    if info is None:
        return False  # 情報なし → 問題なしとみなす

    remaining = info.get("remaining")
    limit = info.get("limit")
    reset = info.get("reset")

    if remaining is not None and remaining <= 0:
        # リセット時刻を過ぎていたら解除
        if reset and int(time.time()) >= reset:
            return False
        reset_in = (reset - int(time.time())) if reset else 0
        raise RateLimitError(
            f"レートリミット超過: {endpoint} "
            f"(リセットまで {reset_in}秒)"
        )

    # 残量10%以下でWARNING
    if remaining is not None and limit is not None and limit > 0:
        if remaining / limit < 0.1:
            return True  # WARNING状態

    return False


def get_endpoint_status(account_name: str, endpoint: str) -> Optional[dict]:
    """特定エンドポイントのレートリミット情報を返す"""
    if account_name not in _rate_limits:
        return None
    return _rate_limits[account_name].get(endpoint)


def get_rate_status(account_name: str) -> dict:
    """
    ダッシュボード用: 全エンドポイントのレートリミット情報を返す。
    各エンドポイントに percentage (残量%) と status (ok/warning/exceeded) を付与。
    """
    if account_name not in _rate_limits:
        return {}

    result = {}
    now = int(time.time())

    for endpoint, info in _rate_limits[account_name].items():
        remaining = info.get("remaining")
        limit = info.get("limit")
        reset = info.get("reset")

        # パーセンテージ計算
        if limit and limit > 0 and remaining is not None:
            pct = round(remaining / limit * 100)
        else:
            pct = 100

        # ステータス判定
        if remaining is not None and remaining <= 0:
            if reset and now >= reset:
                status = "ok"
                pct = 100  # リセット済み
            else:
                status = "exceeded"
        elif pct < 10:
            status = "warning"
        else:
            status = "ok"

        # リセットまでの秒数
        reset_in = max(0, reset - now) if reset else None

        result[endpoint] = {
            "remaining": remaining,
            "limit": limit,
            "percentage": pct,
            "status": status,
            "reset_in": reset_in,
        }

    return result


def reset_all(account_name: str) -> None:
    """アカウントのレートリミットキャッシュをリセット"""
    if account_name in _rate_limits:
        del _rate_limits[account_name]

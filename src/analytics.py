"""
X投稿システム 分析データ管理
仕様: docs/仕様/06_データ分析.md
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.config import get_account_dir
from src.models import (
    Analytics,
    AnalyticsSnapshot,
    ApiCost,
    ApiCostSummary,
    ApiPricing,
    DailySummary,
    MonthlySummary,
    PostingFrequency,
    TopPost,
)
from src.utils import load_post_json, list_posts, save_post_json, write_log


def calculate_engagement_rate(metrics: dict) -> float:
    """engagement_rate = (likes + retweets + replies + quotes) / impressions × 100"""
    impressions = metrics.get("impressions", 0) or metrics.get("impression_count", 0)
    if impressions == 0:
        return 0.0
    engagement = (
        metrics.get("likes", 0)
        + metrics.get("retweets", 0)
        + metrics.get("replies", 0)
        + metrics.get("quotes", 0)
    )
    return round(engagement / impressions * 100, 2)


def fetch_and_update(account_name: str, post_id: str, x_client_module=None) -> dict:
    """
    X APIから分析データを取得し、posted/のJSONを更新
    historyにスナップショットを追加
    """
    # 遅延インポート（循環参照回避）
    if x_client_module is None:
        from src import x_client as x_client_module

    post_data = load_post_json(account_name, "posted", post_id)
    x_post_id = post_data.get("x_post_id")

    if not x_post_id:
        write_log(account_name, f"分析取得スキップ: {post_id} にx_post_idがありません", level="WARN")
        return post_data

    # X APIから取得
    try:
        raw_metrics = x_client_module.fetch_post_metrics(account_name, x_post_id)
    except Exception as e:
        write_log(account_name, f"分析取得失敗: {post_id}, error={e}", level="ERROR")
        return post_data

    if not raw_metrics:
        return post_data

    # メトリクスをマッピング
    metrics = {
        "likes": raw_metrics.get("like_count", 0),
        "retweets": raw_metrics.get("retweet_count", 0),
        "replies": raw_metrics.get("reply_count", 0),
        "quotes": raw_metrics.get("quote_count", 0),
        "impressions": raw_metrics.get("impression_count", 0),
        "bookmarks": raw_metrics.get("bookmark_count", 0),
    }

    now = datetime.now().isoformat()

    # analytics フィールド更新
    analytics = post_data.get("analytics", {})
    analytics.update(metrics)
    analytics["engagement_rate"] = calculate_engagement_rate(metrics)
    analytics["last_fetched_at"] = now

    # history に追加
    history = analytics.get("history", [])
    snapshot = {"fetched_at": now}
    snapshot.update(metrics)
    history.append(snapshot)
    analytics["history"] = history

    post_data["analytics"] = analytics

    # api_cost に分析読み取りコストを加算
    api_cost = post_data.get("api_cost", {})
    api_cost["analytics_reads"] = round(
        api_cost.get("analytics_reads", 0) + ApiPricing.POST_READ, 4
    )
    api_cost["total"] = round(
        api_cost.get("post", 0)
        + api_cost.get("media_upload", 0)
        + api_cost.get("analytics_reads", 0)
        + api_cost.get("deletions", 0),
        4,
    )
    post_data["api_cost"] = api_cost

    # 保存
    save_post_json(account_name, "posted", post_data)
    write_log(
        account_name,
        f"分析更新: {post_id}, likes={metrics['likes']}, imp={metrics['impressions']}",
    )

    return post_data


def update_daily_summary(account_name: str, date: Optional[str] = None) -> DailySummary:
    """日次サマリを生成/更新"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # posted/ から該当日のポストを収集
    all_posts = list_posts(account_name, "posted")
    day_posts = [
        p for p in all_posts
        if str(p.get("posted_at", "")).startswith(date)
    ]

    total_likes = sum(p.get("analytics", {}).get("likes", 0) for p in day_posts)
    total_retweets = sum(p.get("analytics", {}).get("retweets", 0) for p in day_posts)
    total_impressions = sum(p.get("analytics", {}).get("impressions", 0) for p in day_posts)

    # engagement_rate 平均
    rates = [p.get("analytics", {}).get("engagement_rate", 0) for p in day_posts]
    avg_rate = round(sum(rates) / len(rates), 2) if rates else 0.0

    # トップポスト（いいね数最大）
    top = None
    if day_posts:
        best = max(day_posts, key=lambda p: p.get("analytics", {}).get("likes", 0))
        top = TopPost(
            id=best["id"],
            likes=best.get("analytics", {}).get("likes", 0),
            impressions=best.get("analytics", {}).get("impressions", 0),
            engagement_rate=best.get("analytics", {}).get("engagement_rate", 0),
        )

    # APIコスト集計
    api_cost = ApiCost()
    for p in day_posts:
        pc = p.get("api_cost", {})
        api_cost.post += pc.get("post", 0)
        api_cost.media_upload += pc.get("media_upload", 0)
        api_cost.analytics_reads += pc.get("analytics_reads", 0)
        api_cost.deletions += pc.get("deletions", 0)
    api_cost.calculate_total()

    summary = DailySummary(
        date=date,
        account=account_name,
        total_posts=len(day_posts),
        total_impressions=total_impressions,
        total_likes=total_likes,
        total_retweets=total_retweets,
        avg_engagement_rate=avg_rate,
        top_post=top,
        api_cost=api_cost,
    )

    # 保存
    daily_dir = get_account_dir(account_name) / "analytics" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_file = daily_dir / f"{date}.json"
    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(summary.model_dump(), f, ensure_ascii=False, indent=2, default=str)

    return summary


def update_monthly_summary(account_name: str) -> MonthlySummary:
    """当月のサマリを更新"""
    now = datetime.now()
    month_str = now.strftime("%Y-%m")
    month_start = now.strftime("%Y-%m-01")

    all_posts = list_posts(account_name, "posted")
    month_posts = [
        p for p in all_posts
        if str(p.get("posted_at", "")).startswith(month_str)
    ]

    total_likes = sum(p.get("analytics", {}).get("likes", 0) for p in month_posts)
    total_impressions = sum(p.get("analytics", {}).get("impressions", 0) for p in month_posts)
    total_posts = len(month_posts)

    # best_performing_posts: engagement_rate 上位5件
    sorted_posts = sorted(
        month_posts,
        key=lambda p: p.get("analytics", {}).get("engagement_rate", 0),
        reverse=True,
    )[:5]
    best = [
        TopPost(
            id=p["id"],
            likes=p.get("analytics", {}).get("likes", 0),
            impressions=p.get("analytics", {}).get("impressions", 0),
            engagement_rate=p.get("analytics", {}).get("engagement_rate", 0),
        )
        for p in sorted_posts
    ]

    # 曜日別投稿頻度
    freq = {"mon": 0, "tue": 0, "wed": 0, "thu": 0, "fri": 0, "sat": 0, "sun": 0}
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    for p in month_posts:
        posted_at = p.get("posted_at", "")
        if posted_at:
            try:
                dt = datetime.fromisoformat(posted_at) if isinstance(posted_at, str) else posted_at
                freq[day_names[dt.weekday()]] += 1
            except (ValueError, TypeError):
                pass

    # APIコスト集計
    cost_summary = ApiCostSummary()
    cost_breakdown = ApiCost()
    for p in month_posts:
        pc = p.get("api_cost", {})
        cost_breakdown.post += pc.get("post", 0)
        cost_breakdown.media_upload += pc.get("media_upload", 0)
        cost_breakdown.analytics_reads += pc.get("analytics_reads", 0)
        cost_breakdown.deletions += pc.get("deletions", 0)
    cost_breakdown.calculate_total()
    cost_summary.total_usd = cost_breakdown.total
    cost_summary.breakdown = cost_breakdown
    cost_summary.update_jpy()

    summary = MonthlySummary(
        month=month_str,
        account=account_name,
        period={"from": month_start, "to": now.strftime("%Y-%m-%d")},
        total_posts=total_posts,
        total_impressions=total_impressions,
        total_likes=total_likes,
        avg_likes_per_post=round(total_likes / total_posts, 1) if total_posts else 0,
        avg_impressions_per_post=round(total_impressions / total_posts, 1) if total_posts else 0,
        avg_engagement_rate=round(
            sum(p.get("analytics", {}).get("engagement_rate", 0) for p in month_posts) / total_posts, 2
        ) if total_posts else 0.0,
        best_performing_posts=best,
        posting_frequency=PostingFrequency(**freq),
        api_cost=cost_summary,
        last_updated_at=now,
    )

    # summary.json に保存
    analytics_dir = get_account_dir(account_name) / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    summary_file = analytics_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary.model_dump(), f, ensure_ascii=False, indent=2, default=str)

    return summary


def archive_month(account_name: str, month: Optional[str] = None) -> Optional[Path]:
    """
    月替わり処理:
    1. summary.json を monthly/{YYYY-MM}.json にコピー
    2. summary.json をリセット
    """
    analytics_dir = get_account_dir(account_name) / "analytics"
    summary_file = analytics_dir / "summary.json"

    if not summary_file.exists():
        return None

    with open(summary_file, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    # 月を特定
    if month is None:
        month = summary_data.get("month")
    if not month:
        return None

    # アーカイブ先
    monthly_dir = analytics_dir / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)
    archive_file = monthly_dir / f"{month}.json"

    # アーカイブ済みならスキップ
    if archive_file.exists():
        write_log(account_name, f"月次アーカイブ済み: {month}", level="WARN")
        return archive_file

    # archived_at を追加してコピー
    summary_data["archived_at"] = datetime.now().isoformat()
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2, default=str)

    write_log(account_name, f"月次アーカイブ完了: {month} → {archive_file}")

    return archive_file


def load_monthly_archive(account_name: str, month: str) -> Optional[dict]:
    """月次アーカイブを読み込み"""
    archive_file = get_account_dir(account_name) / "analytics" / "monthly" / f"{month}.json"
    if not archive_file.exists():
        return None
    with open(archive_file, "r", encoding="utf-8") as f:
        return json.load(f)


def list_monthly_archives(account_name: str) -> list[str]:
    """利用可能な月次アーカイブの月一覧を返す"""
    monthly_dir = get_account_dir(account_name) / "analytics" / "monthly"
    if not monthly_dir.exists():
        return []
    return sorted(
        [f.stem for f in monthly_dir.glob("*.json")],
        reverse=True,
    )

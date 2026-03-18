"""
X投稿システム 週次/月次レポート自動生成
分析データをMarkdownレポートに整形し、accounts/{name}/reports/ に保存。
"""


from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.config import get_account_dir
from src.utils import list_posts, write_log


def _get_reports_dir(account_name: str) -> Path:
    """レポート保存ディレクトリ"""
    d = get_account_dir(account_name) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_week_range(week_str: Optional[str] = None) -> tuple[str, str, str]:
    """
    ISO週番号からレポート対象の開始日・終了日を返す。
    week_str: "2026-W12" 形式。Noneなら先週。
    戻り値: (week_str, start_date, end_date)
    """
    if week_str is None:
        today = datetime.now()
        last_week = today - timedelta(days=7)
        year, week_num, _ = last_week.isocalendar()
        week_str = f"{year}-W{week_num:02d}"

    # ISO週から月曜起算で日付を求める
    parts = week_str.split("-W")
    year = int(parts[0])
    week = int(parts[1])
    # ISO週の月曜日
    jan4 = datetime(year, 1, 4)
    start = jan4 + timedelta(weeks=week - 1, days=-jan4.weekday())
    end = start + timedelta(days=6)
    return week_str, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _get_month_range(month_str: Optional[str] = None) -> tuple[str, str, str]:
    """
    月文字列からレポート対象の開始日・終了日を返す。
    month_str: "2026-03" 形式。Noneなら先月。
    """
    if month_str is None:
        today = datetime.now()
        first = today.replace(day=1)
        last_month_end = first - timedelta(days=1)
        month_str = last_month_end.strftime("%Y-%m")

    year, month = int(month_str[:4]), int(month_str[5:7])
    start = f"{year}-{month:02d}-01"
    # 翌月初日 - 1日
    if month == 12:
        end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1) - timedelta(days=1)
    end = end_date.strftime("%Y-%m-%d")
    return month_str, start, end


def _collect_posts_in_range(
    account_name: str, start_date: str, end_date: str
) -> list[dict]:
    """指定期間のposted投稿を収集"""
    return [
        p for p in list_posts(account_name, "posted")
        if start_date <= (p.get("posted_at") or "")[:10] <= end_date
    ]


def _format_number(n: int) -> str:
    """数値を桁区切りでフォーマット"""
    return f"{n:,}"


def _get_analytics(post: dict) -> dict:
    """投稿のanalyticsを安全に取得"""
    return post.get("analytics") or {}


def _load_follower_data(account_name: str) -> Optional[dict]:
    """フォロワーサマリを安全に取得"""
    try:
        from src.followers import get_follower_summary
        return get_follower_summary(account_name)
    except Exception:
        return None


def _save_report(account_name: str, filename: str, content: str, log_msg: str) -> str:
    """レポートを保存しログに記録"""
    path = _get_reports_dir(account_name) / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    write_log(account_name, log_msg)
    return str(path)


def _generate_report_md(
    title: str,
    period_label: str,
    posts: list[dict],
    prev_posts: list[dict],
    follower_data: Optional[dict] = None,
) -> str:
    """レポート本文をMarkdownで生成"""
    # 集計
    total = len(posts)
    impressions = sum(_get_analytics(p).get("impressions", 0) for p in posts)
    likes = sum(_get_analytics(p).get("likes", 0) for p in posts)
    retweets = sum(_get_analytics(p).get("retweets", 0) for p in posts)

    # ER平均
    er_list = [
        _get_analytics(p).get("engagement_rate", 0) for p in posts
        if _get_analytics(p).get("impressions", 0) > 0
    ]
    avg_er = round(sum(er_list) / len(er_list), 2) if er_list else 0

    # 前期比
    prev_total = len(prev_posts)
    prev_imp = sum(_get_analytics(p).get("impressions", 0) for p in prev_posts)
    prev_likes = sum(_get_analytics(p).get("likes", 0) for p in prev_posts)

    def _change(curr, prev):
        if prev == 0:
            return "-"
        pct = round((curr - prev) / prev * 100)
        return f"+{pct}%" if pct >= 0 else f"{pct}%"

    # APIコスト合計
    total_cost = sum(
        (p.get("api_cost") or {}).get("total", 0) for p in posts
    )
    cost_jpy = int(total_cost * 160)

    # TOP 3 投稿
    ranked = sorted(
        [p for p in posts if _get_analytics(p).get("impressions", 0) > 0],
        key=lambda p: _get_analytics(p).get("engagement_rate", 0),
        reverse=True,
    )[:3]

    # Markdown生成
    lines = [
        f"# {title}",
        f"",
        f"期間: {period_label}",
        f"生成日: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## サマリ",
        f"",
        f"| 指標 | 今期 | 前期 | 増減 |",
        f"|---|---|---|---|",
        f"| 投稿数 | {total} | {prev_total} | {_change(total, prev_total)} |",
        f"| インプレッション | {_format_number(impressions)} | {_format_number(prev_imp)} | {_change(impressions, prev_imp)} |",
        f"| いいね | {_format_number(likes)} | {_format_number(prev_likes)} | {_change(likes, prev_likes)} |",
        f"| RT | {_format_number(retweets)} | - | - |",
        f"| ER平均 | {avg_er}% | - | - |",
    ]

    # フォロワー情報
    if follower_data and follower_data.get("current"):
        lines.append(
            f"| フォロワー | {_format_number(follower_data['current'])} | - | "
            f"{'+' if follower_data.get('change_7d', 0) >= 0 else ''}"
            f"{follower_data.get('change_7d', 0)} (7日間) |"
        )

    lines += [
        f"",
        f"## TOP 投稿 (ER順)",
        f"",
    ]

    for i, p in enumerate(ranked, 1):
        er = _get_analytics(p).get("engagement_rate", 0)
        text = (p.get("text") or "")[:60].replace("\n", " ")
        lines.append(f"{i}. [ER {er}%] \"{text}...\"")

    lines += [
        f"",
        f"## APIコスト",
        f"",
        f"合計: ${total_cost:.3f} (約{cost_jpy}円)",
        f"",
    ]

    return "\n".join(lines)


def generate_weekly_report(
    account_name: str, week_str: Optional[str] = None
) -> str:
    """週次レポートを生成して保存"""
    week, start, end = _get_week_range(week_str)
    posts = _collect_posts_in_range(account_name, start, end)

    # 前週
    prev_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_end = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_posts = _collect_posts_in_range(account_name, prev_start, prev_end)

    follower_data = _load_follower_data(account_name)
    title = f"週次レポート {week} ({start[5:]} - {end[5:]})"
    md = _generate_report_md(title, f"{start} ~ {end}", posts, prev_posts, follower_data)
    return _save_report(account_name, f"weekly_{week}.md", md, f"週次レポート生成: {week}")


def generate_monthly_report(
    account_name: str, month_str: Optional[str] = None
) -> str:
    """月次レポートを生成して保存"""
    month, start, end = _get_month_range(month_str)
    posts = _collect_posts_in_range(account_name, start, end)

    # 前月
    prev_month_dt = datetime.strptime(start, "%Y-%m-%d") - timedelta(days=1)
    prev_month_str = prev_month_dt.strftime("%Y-%m")
    _, prev_start, prev_end = _get_month_range(prev_month_str)
    prev_posts = _collect_posts_in_range(account_name, prev_start, prev_end)

    follower_data = _load_follower_data(account_name)
    title = f"月次レポート {month}"
    md = _generate_report_md(title, f"{start} ~ {end}", posts, prev_posts, follower_data)
    return _save_report(account_name, f"monthly_{month}.md", md, f"月次レポート生成: {month}")


def list_reports(account_name: str) -> list[dict]:
    """レポート一覧を返す"""
    reports_dir = _get_reports_dir(account_name)
    result = []
    for f in sorted(reports_dir.glob("*.md"), reverse=True):
        result.append({
            "filename": f.name,
            "type": "weekly" if f.name.startswith("weekly") else "monthly",
            "size": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return result

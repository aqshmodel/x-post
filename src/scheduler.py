"""
X投稿システム 予約投稿スケジューラ
仕様: docs/仕様/05_予約投稿.md
"""

from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import get_account_dir, is_account_active, list_accounts
from src.models import Post, PostStatus
from src.utils import list_posts, load_post_json, move_post, save_post_json, write_log

# グローバルスケジューラインスタンス
scheduler: Optional[BackgroundScheduler] = None

# 過去ジョブ許容時間（1時間）
PAST_JOB_TOLERANCE_HOURS = 1


def init_scheduler() -> BackgroundScheduler:
    """スケジューラを初期化"""
    global scheduler
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")
    scheduler.start()
    return scheduler


def get_scheduler() -> BackgroundScheduler:
    """スケジューラインスタンスを取得"""
    global scheduler
    if scheduler is None:
        scheduler = init_scheduler()
    return scheduler


def _execute_post(account_name: str, post_id: str) -> None:
    """予約時刻に実行される投稿ジョブ"""
    from src.x_client import publish_post, get_client
    from src.config import load_account, get_account_dir as _get_dir
    import json

    try:
        post_data = load_post_json(account_name, "scheduled", post_id)
        post = Post(**post_data)

        # active チェック
        if not is_account_active(account_name):
            post.status = PostStatus.FAILED
            post.error = "アカウントが無効化されています (active: false)"
            save_post_json(account_name, "scheduled", post.model_dump())
            write_log(account_name, f"予約投稿スキップ (inactive): {post_id}", level="WARN")
            return

        result = publish_post(account_name, post)
        # scheduled/ のファイルを削除
        scheduled_file = get_account_dir(account_name) / "scheduled" / f"{post_id}.json"
        if scheduled_file.exists():
            scheduled_file.unlink()

        # セルフリプライ（投稿固有 > config.json のフォールバック）
        if result.x_post_id:
            # 投稿JSONに self_reply_text があればそれを優先
            reply_text = post_data.get("self_reply_text") if post_data else None
            if not reply_text:
                config_path = _get_dir(account_name) / "config.json"
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                reply_text = config.get("self_reply_text")
            if reply_text:
                try:
                    client = get_client(account_name)
                    client.create_tweet(text=reply_text, in_reply_to_tweet_id=result.x_post_id)
                    write_log(account_name, f"セルフリプライ投稿: {post_id}")
                except Exception as re:
                    write_log(account_name, f"セルフリプライ失敗: {post_id}, error={re}", level="ERROR")

    except Exception as e:
        write_log(account_name, f"予約投稿失敗: {post_id}, error={e}", level="ERROR")


def _execute_thread(account_name: str, post_ids: list[str]) -> None:
    """予約時刻に実行されるスレッド投稿ジョブ"""
    from src.x_client import publish_thread

    try:
        posts = []
        for pid in post_ids:
            data = load_post_json(account_name, "scheduled", pid)
            posts.append(Post(**data))

        if not is_account_active(account_name):
            for post in posts:
                post.status = PostStatus.FAILED
                post.error = "アカウントが無効化されています (active: false)"
                save_post_json(account_name, "scheduled", post.model_dump())
            write_log(account_name, f"スレッド予約スキップ (inactive)", level="WARN")
            return

        publish_thread(account_name, posts)
        # 投稿成功したものの scheduled/ ファイルを削除
        for pid in post_ids:
            scheduled_file = get_account_dir(account_name) / "scheduled" / f"{pid}.json"
            if scheduled_file.exists():
                scheduled_file.unlink()

    except Exception as e:
        write_log(account_name, f"スレッド予約投稿失敗: error={e}", level="ERROR")


def schedule_post(account_name: str, post: Post) -> str:
    """予約投稿をスケジューラに登録"""
    sched = get_scheduler()
    job_id = f"post_{account_name}_{post.id}"

    sched.add_job(
        _execute_post,
        "date",
        run_date=post.scheduled_at,
        args=[account_name, post.id],
        id=job_id,
        replace_existing=True,
    )

    write_log(account_name, f"予約登録: {post.id} → {post.scheduled_at}")
    return job_id


def cancel_scheduled_post(account_name: str, post_id: str) -> None:
    """予約をキャンセルし draft に戻す"""
    sched = get_scheduler()
    job_id = f"post_{account_name}_{post_id}"

    # スケジューラからジョブ削除
    try:
        sched.remove_job(job_id)
    except Exception:
        pass  # ジョブが存在しない場合は無視

    # ステータスを draft に戻す
    post_data = load_post_json(account_name, "scheduled", post_id)
    post_data["status"] = PostStatus.DRAFT.value
    post_data["scheduled_at"] = None
    post_data["updated_at"] = datetime.now().isoformat()
    save_post_json(account_name, "drafts", post_data)

    # scheduled/ のファイルを削除
    scheduled_file = get_account_dir(account_name) / "scheduled" / f"{post_id}.json"
    if scheduled_file.exists():
        scheduled_file.unlink()

    write_log(account_name, f"予約キャンセル → draft: {post_id}")


def retry_failed_post(account_name: str, post_id: str, new_time: Optional[datetime] = None) -> str:
    """失敗した投稿をリトライ予約"""
    post_data = load_post_json(account_name, "scheduled", post_id)
    post_data["status"] = PostStatus.SCHEDULED.value
    post_data["error"] = None

    if new_time:
        post_data["scheduled_at"] = new_time.isoformat()

    post_data["updated_at"] = datetime.now().isoformat()
    save_post_json(account_name, "scheduled", post_data)

    post = Post(**post_data)
    return schedule_post(account_name, post)


def recover_jobs() -> dict:
    """
    サーバー起動時に scheduled/ をスキャンし、ジョブを復旧
    過去ジョブポリシー:
    - 未来: 通常通り登録
    - 1時間以内: 即座に実行（遅延投稿）
    - 1時間超過: failed にマーク
    - active: false のアカウント: failed にマーク
    """
    results = {"registered": 0, "executed": 0, "failed": 0}
    now = datetime.now()
    tolerance = now - timedelta(hours=PAST_JOB_TOLERANCE_HOURS)

    for account_name in list_accounts():
        # active チェック
        account_active = is_account_active(account_name)

        scheduled_posts = list_posts(account_name, "scheduled")
        for post_data in scheduled_posts:
            post = Post(**post_data)

            if post.status != PostStatus.SCHEDULED:
                continue

            # inactive アカウントのジョブは failed にマーク
            if not account_active:
                post.status = PostStatus.FAILED
                post.error = "アカウントが無効化されています (active: false)"
                save_post_json(account_name, "scheduled", post.model_dump())
                results["failed"] += 1
                write_log(account_name, f"起動時ジョブ失敗 (inactive): {post.id}", level="WARN")
                continue

            if post.scheduled_at is None:
                continue

            scheduled_time = post.scheduled_at
            if isinstance(scheduled_time, str):
                scheduled_time = datetime.fromisoformat(scheduled_time)

            # タイムゾーン統一（offset-aware vs offset-naive の比較エラー回避）
            if scheduled_time.tzinfo is not None:
                from datetime import timezone
                now_cmp = datetime.now(scheduled_time.tzinfo)
                tolerance_cmp = now_cmp - timedelta(hours=PAST_JOB_TOLERANCE_HOURS)
            else:
                now_cmp = now
                tolerance_cmp = tolerance

            if scheduled_time > now_cmp:
                # 未来: 通常登録
                schedule_post(account_name, post)
                results["registered"] += 1
            elif scheduled_time >= tolerance_cmp:
                # 1時間以内: 即座に実行
                write_log(account_name, f"遅延投稿実行: {post.id} (予約: {scheduled_time})")
                _execute_post(account_name, post.id)
                results["executed"] += 1
            else:
                # 1時間超過: failed
                post.status = PostStatus.FAILED
                post.error = f"予約時刻を1時間以上超過 (予約: {scheduled_time})"
                save_post_json(account_name, "scheduled", post.model_dump())
                results["failed"] += 1
                write_log(account_name, f"起動時ジョブ失敗 (超過): {post.id}", level="WARN")

    return results


def schedule_analytics_fetch(account_name: str, post_id: str) -> None:
    """投稿後24h/48h/7dの分析取得をスケジュール"""
    sched = get_scheduler()
    now = datetime.now()

    delays = [
        ("24h", timedelta(hours=24)),
        ("48h", timedelta(hours=48)),
        ("7d", timedelta(days=7)),
    ]

    for label, delta in delays:
        job_id = f"analytics_{account_name}_{post_id}_{label}"
        sched.add_job(
            _fetch_analytics_job,
            "date",
            run_date=now + delta,
            args=[account_name, post_id],
            id=job_id,
            replace_existing=True,
        )


def _fetch_analytics_job(account_name: str, post_id: str) -> None:
    """分析取得ジョブの実行"""
    from src.analytics import fetch_and_update
    try:
        fetch_and_update(account_name, post_id)
    except Exception as e:
        write_log(account_name, f"分析取得ジョブ失敗: {post_id}, error={e}", level="ERROR")


def schedule_monthly_archive() -> None:
    """毎月1日 00:05 に月替わりアーカイブを実行"""
    sched = get_scheduler()
    sched.add_job(
        _monthly_archive_job,
        "cron",
        day=1,
        hour=0,
        minute=5,
        id="monthly_archive",
        replace_existing=True,
    )


def _monthly_archive_job() -> None:
    """月替わりアーカイブジョブの実行"""
    from src.analytics import archive_month, update_monthly_summary

    for account_name in list_accounts():
        try:
            archive_month(account_name)
            update_monthly_summary(account_name)
            write_log(account_name, "月替わりアーカイブ完了")
        except Exception as e:
            write_log(account_name, f"月替わりアーカイブ失敗: error={e}", level="ERROR")


def schedule_auto_reply() -> None:
    """自動リプライの定期実行ジョブを登録（60分間隔、7:00-23:00）"""
    from src.auto_reply import run_auto_reply_job

    sched = get_scheduler()
    sched.add_job(
        run_auto_reply_job,
        "cron",
        minute=0,  # 毎時0分に実行
        hour="7-22",  # 7:00〜22:00（23時台は22:00のジョブが最後）
        id="auto_reply",
        replace_existing=True,
    )
    print("[AutoReply] 自動リプライジョブ登録: 60分間隔 (7:00-22:00)")


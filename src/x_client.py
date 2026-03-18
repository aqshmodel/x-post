"""
X投稿システム X APIクライアント
仕様: docs/仕様/07_API仕様.md
"""

import os
import time
from datetime import datetime
from typing import Optional

import tweepy

from src.config import get_env_credentials, is_account_active, get_account_dir
from src.models import ApiCost, ApiPricing, Post, PostStatus
from src.utils import (
    convert_to_jpeg,
    generate_image_filename,
    load_post_json,
    move_post,
    save_post_json,
    write_log,
)


def get_client(account_name: str) -> tweepy.Client:
    """アカウントごとに独立した tweepy.Client を生成（取り違え防止）"""
    creds = get_env_credentials(account_name)
    return tweepy.Client(
        consumer_key=creds["api_key"],
        consumer_secret=creds["api_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_token_secret"],
    )


def get_api(account_name: str) -> tweepy.API:
    """メディアアップロード用の tweepy.API を生成（v1.1互換）"""
    creds = get_env_credentials(account_name)
    auth = tweepy.OAuthHandler(creds["api_key"], creds["api_secret"])
    auth.set_access_token(creds["access_token"], creds["access_token_secret"])
    return tweepy.API(auth)


def _check_active(account_name: str) -> None:
    """アカウントの active チェック"""
    if not is_account_active(account_name):
        raise PermissionError(f"アカウント '{account_name}' は無効化されています (active: false)")


def upload_media(account_name: str, file_paths: list[str]) -> list[str]:
    """
    画像ファイルをアップロードし media_ids を返す
    WebPの場合はJPEGに自動変換
    """
    _check_active(account_name)
    api = get_api(account_name)
    media_ids = []

    for path in file_paths:
        # WebP → JPEG 変換
        if path.lower().endswith(".webp"):
            jpeg_path = path.rsplit(".", 1)[0] + ".jpg"
            convert_to_jpeg(path, jpeg_path)
            path = jpeg_path

        media = api.media_upload(path)
        media_ids.append(str(media.media_id))
        write_log(account_name, f"メディアアップロード完了: {path} → media_id={media.media_id}")

    return media_ids


def _calculate_api_cost(has_media: int) -> ApiCost:
    """投稿のAPIコストを計算"""
    cost = ApiCost(
        post=ApiPricing.POST_CREATE,
        media_upload=round(ApiPricing.MEDIA_UPLOAD * has_media, 4),
    )
    cost.calculate_total()
    return cost


def publish_post(account_name: str, post: Post) -> Post:
    """
    ポストを即時投稿する
    1. active チェック
    2. メディアアップロード（あれば）
    3. create_tweet 実行
    4. api_cost 計算・記録
    5. posted/ に移動 + ログ記録
    """
    _check_active(account_name)
    client = get_client(account_name)

    # メディアアップロード
    media_ids = None
    if post.media:
        account_dir = get_account_dir(account_name)
        full_paths = [str(account_dir / m) for m in post.media]
        uploaded_ids = upload_media(account_name, full_paths)
        post.media_ids = uploaded_ids
        media_ids = [int(mid) for mid in uploaded_ids]

    # 投稿実行
    try:
        response = client.create_tweet(
            text=post.text,
            media_ids=media_ids,
        )
        post.x_post_id = str(response.data["id"])
        post.status = PostStatus.POSTED
        post.posted_at = datetime.now()
        post.api_cost = _calculate_api_cost(len(post.media))
        post.error = None

        write_log(
            account_name,
            f"投稿成功: post_id={post.id}, x_post_id={post.x_post_id}, "
            f"cost=${post.api_cost.total}",
        )

    except tweepy.TweepyException as e:
        post.status = PostStatus.FAILED
        post.error = str(e)
        write_log(account_name, f"投稿失敗: post_id={post.id}, error={e}", level="ERROR")
        # 失敗時は drafts/ に保存（呼び出し元がscheduledでもdraftでも安全）
        save_post_json(account_name, "drafts", post.model_dump())
        raise

    # posted/ に保存
    save_post_json(account_name, "posted", post.model_dump())
    return post


def publish_thread(account_name: str, posts: list[Post]) -> list[Post]:
    """
    スレッド（連続ツイート）を投稿
    各投稿間に3秒のインターバルを設ける
    途中失敗時: 投稿済み → posted/, 未投稿 → failed
    """
    _check_active(account_name)
    client = get_client(account_name)
    previous_id: Optional[str] = None
    published: list[Post] = []

    for i, post in enumerate(posts):
        try:
            # メディアアップロード
            media_ids = None
            if post.media:
                account_dir = get_account_dir(account_name)
                full_paths = [str(account_dir / m) for m in post.media]
                uploaded_ids = upload_media(account_name, full_paths)
                post.media_ids = uploaded_ids
                media_ids = [int(mid) for mid in uploaded_ids]

            # 投稿（2本目以降は in_reply_to_tweet_id を指定）
            kwargs = {"text": post.text}
            if media_ids:
                kwargs["media_ids"] = media_ids
            if previous_id:
                kwargs["in_reply_to_tweet_id"] = previous_id

            response = client.create_tweet(**kwargs)
            post.x_post_id = str(response.data["id"])
            post.status = PostStatus.POSTED
            post.posted_at = datetime.now()
            post.api_cost = _calculate_api_cost(len(post.media))
            previous_id = post.x_post_id
            published.append(post)

            save_post_json(account_name, "posted", post.model_dump())
            write_log(
                account_name,
                f"スレッド投稿成功: {i + 1}/{len(posts)}, x_post_id={post.x_post_id}",
            )

            # 次の投稿まで3秒待機
            if i < len(posts) - 1:
                time.sleep(3)

        except tweepy.TweepyException as e:
            # 残りを全て failed にマーク
            for remaining in posts[i:]:
                remaining.status = PostStatus.FAILED
                remaining.error = str(e)
                save_post_json(account_name, "scheduled", remaining.model_dump())
            write_log(
                account_name,
                f"スレッド投稿失敗: {i + 1}/{len(posts)}, error={e}",
                level="ERROR",
            )
            raise

    return published


def delete_post(account_name: str, x_post_id: str) -> None:
    """投稿を削除"""
    _check_active(account_name)
    client = get_client(account_name)
    client.delete_tweet(x_post_id)
    write_log(account_name, f"投稿削除: x_post_id={x_post_id}")


def fetch_post_metrics(account_name: str, x_post_id: str) -> dict:
    """ポストの public_metrics を取得"""
    client = get_client(account_name)
    response = client.get_tweet(
        x_post_id,
        tweet_fields=["public_metrics", "created_at"],
    )
    if response.data and response.data.public_metrics:
        return response.data.public_metrics
    return {}

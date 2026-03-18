"""
X投稿システム データモデル定義
仕様: docs/仕様/02_ディレクトリ構成.md, 06_データ分析.md
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PostStatus(str, Enum):
    """ポストのステータス"""
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    POSTED = "posted"
    FAILED = "failed"


class ApiCost(BaseModel):
    """API利用コスト内訳"""
    post: float = 0.0
    media_upload: float = 0.0
    analytics_reads: float = 0.0
    deletions: float = 0.0
    auto_reply: float = 0.0
    total: float = 0.0

    def calculate_total(self) -> None:
        self.total = round(
            self.post + self.media_upload + self.analytics_reads
            + self.deletions + self.auto_reply, 4
        )


class ApiCostSummary(BaseModel):
    """月次APIコスト集計"""
    total_usd: float = 0.0
    total_jpy_approx: int = 0
    breakdown: ApiCost = Field(default_factory=ApiCost)

    def update_jpy(self, rate: float = 160.0) -> None:
        self.total_jpy_approx = int(self.total_usd * rate)


class AnalyticsSnapshot(BaseModel):
    """分析データのスナップショット（履歴用）"""
    fetched_at: datetime
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    quotes: int = 0
    impressions: int = 0
    bookmarks: int = 0


class Analytics(BaseModel):
    """ポスト別分析データ"""
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    quotes: int = 0
    impressions: int = 0
    bookmarks: int = 0
    engagement_rate: float = 0.0
    last_fetched_at: Optional[datetime] = None
    history: list[AnalyticsSnapshot] = Field(default_factory=list)

    def calculate_engagement_rate(self) -> None:
        """engagement_rate = (likes + retweets + replies + quotes) / impressions × 100"""
        if self.impressions > 0:
            self.engagement_rate = round(
                (self.likes + self.retweets + self.replies + self.quotes) / self.impressions * 100,
                2,
            )
        else:
            self.engagement_rate = 0.0


class Post(BaseModel):
    """投稿データ（02_ディレクトリ構成.md のJSON構造に準拠）"""
    id: str
    account: str
    text: str
    media: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)
    thread: list[str] = Field(default_factory=list)
    thread_position: Optional[int] = None
    scheduled_at: Optional[datetime] = None
    status: PostStatus = PostStatus.DRAFT
    x_post_id: Optional[str] = None
    posted_at: Optional[datetime] = None
    error: Optional[str] = None
    api_cost: ApiCost = Field(default_factory=ApiCost)
    analytics: Analytics = Field(default_factory=Analytics)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class PostingRules(BaseModel):
    """投稿ルール"""
    max_posts_per_day: int = 10
    default_language: str = "ja"
    auto_analytics: bool = True
    max_char_count: int = 280


class Account(BaseModel):
    """アカウント設定（03_アカウント管理.md の config.json に準拠）"""
    account_name: str
    display_name: str = ""
    x_username: str = ""
    x_user_id: str = ""
    active: bool = True
    posting_rules: PostingRules = Field(default_factory=PostingRules)
    created_at: datetime = Field(default_factory=datetime.now)


class TopPost(BaseModel):
    """トップポスト（サマリ用）"""
    id: str
    likes: int = 0
    impressions: int = 0
    engagement_rate: float = 0.0


class DailySummary(BaseModel):
    """日次サマリ"""
    date: str
    account: str
    total_posts: int = 0
    total_impressions: int = 0
    total_likes: int = 0
    total_retweets: int = 0
    avg_engagement_rate: float = 0.0
    top_post: Optional[TopPost] = None
    api_cost: ApiCost = Field(default_factory=ApiCost)


class PostingFrequency(BaseModel):
    """曜日別投稿頻度"""
    mon: int = 0
    tue: int = 0
    wed: int = 0
    thu: int = 0
    fri: int = 0
    sat: int = 0
    sun: int = 0


class MonthlySummary(BaseModel):
    """月次サマリ / アカウントサマリ"""
    month: Optional[str] = None
    account: str
    period: Optional[dict] = None
    total_posts: int = 0
    total_impressions: int = 0
    total_likes: int = 0
    avg_likes_per_post: float = 0.0
    avg_impressions_per_post: float = 0.0
    avg_engagement_rate: float = 0.0
    best_performing_posts: list[TopPost] = Field(default_factory=list)
    posting_frequency: PostingFrequency = Field(default_factory=PostingFrequency)
    api_cost: ApiCostSummary = Field(default_factory=ApiCostSummary)
    last_updated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None


# --- APIリクエスト/レスポンス用 ---

class PublishRequest(BaseModel):
    """即時投稿リクエスト"""
    account: str
    text: str
    media: list[str] = Field(default_factory=list)


class ScheduleRequest(BaseModel):
    """予約投稿リクエスト"""
    account: str
    text: str
    media: list[str] = Field(default_factory=list)
    scheduled_at: datetime


class ThreadRequest(BaseModel):
    """スレッド投稿リクエスト"""
    account: str
    texts: list[str]
    media: list[list[str]] = Field(default_factory=list)
    scheduled_at: Optional[datetime] = None


# --- API単価定数 ---

class ApiPricing:
    """X API 操作別単価（USD）"""
    POST_CREATE = 0.010
    MEDIA_UPLOAD = 0.005
    POST_READ = 0.005
    POST_DELETE = 0.005
    # 自動リプライ関連
    MENTION_READ = 0.001
    TWEET_READ = 0.001
    LIKE = 0.001
    REPLY = 0.010  # POST_CREATEと同じ

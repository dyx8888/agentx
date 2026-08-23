"""Normalization rule metadata for browser connector captures.

The connector only stores sanitized response payloads. These rules document the
first supported platform-shaped response families and keep business modules from
depending on raw platform JSON structures.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.browser_connector_schemas import BrowserConnectorRecordKind


CREATOR_NAME_KEYS = ("name", "nickname", "display_name", "author_name", "creator_name", "kol_name")
CREATOR_UID_KEYS = ("platform_uid", "uid", "user_id", "author_id", "creator_id", "kol_id", "sec_uid")
FOLLOWER_KEYS = ("followers", "follower_count", "fans", "fans_count", "fan_count")
ENGAGEMENT_KEYS = ("engagement_rate", "interaction_rate", "engagement", "interact_rate")
AVG_VIEW_KEYS = ("avg_views", "average_views", "avg_play_count", "avg_video_views")
AVG_LIKE_KEYS = ("avg_likes", "average_likes", "likes", "like_count")
AVG_COMMENT_KEYS = ("avg_comments", "average_comments", "comments", "comment_count")
AVG_SHARE_KEYS = ("avg_shares", "average_shares", "shares", "share_count")
CATEGORY_KEYS = ("category", "cate_name", "industry", "vertical", "content_category")
LOCATION_KEYS = ("location", "city", "province", "region")
VERIFIED_KEYS = ("verified", "is_verified", "certified")

CAMPAIGN_ID_KEYS = ("campaign_id", "campaignId", "plan_id", "ad_id", "promotion_id")
CAMPAIGN_NAME_KEYS = ("campaign_name", "campaignName", "plan_name", "ad_name", "name")
IMPRESSION_KEYS = ("impressions", "show_count", "exposure", "pv")
CLICK_KEYS = ("clicks", "click_count", "click")
CONVERSION_KEYS = ("conversions", "conversion_count", "orders", "order_count")
SPEND_KEYS = ("spend", "cost", "consume", "ad_spend")
REVENUE_KEYS = ("revenue", "gmv", "sales", "amount")
CTR_KEYS = ("ctr", "click_rate")
CPA_KEYS = ("cpa", "cost_per_action", "cost_per_order")
ROI_KEYS = ("roi", "roas")

KNOWLEDGE_CONTAINER_KEYS = {"knowledge", "observations", "insights", "notes", "summaries"}
KNOWLEDGE_TEXT_KEYS = ("content", "summary", "text", "note", "insight", "description")


@dataclass(frozen=True)
class BrowserConnectorNormalizationRule:
    """Document one supported sanitized platform response family."""

    name: str
    kind: BrowserConnectorRecordKind
    matched_rule: str
    platform: str
    fixture_name: str
    description: str


BROWSER_CONNECTOR_NORMALIZATION_RULES = (
    BrowserConnectorNormalizationRule(
        name="buyin_creator_search",
        kind=BrowserConnectorRecordKind.CREATOR_PROFILE,
        matched_rule="buyin-api",
        platform="douyin",
        fixture_name="buyin_creator_search_sanitized.json",
        description="Creator search/list payloads with author identity, follower, category, and engagement fields.",
    ),
    BrowserConnectorNormalizationRule(
        name="oceanengine_campaign_snapshot",
        kind=BrowserConnectorRecordKind.CAMPAIGN_METRICS,
        matched_rule="oceanengine-api",
        platform="oceanengine",
        fixture_name="oceanengine_campaign_snapshot_sanitized.json",
        description="Read-only campaign performance snapshots with spend, GMV, click, and conversion metrics.",
    ),
    BrowserConnectorNormalizationRule(
        name="buyin_activity_insight",
        kind=BrowserConnectorRecordKind.KNOWLEDGE_OBSERVATION,
        matched_rule="buyin-api",
        platform="douyin",
        fixture_name="buyin_activity_insight_sanitized.json",
        description="Operational insight or platform-rule snippets suitable for human-reviewed knowledge ingestion.",
    ),
)


def list_browser_connector_normalization_rules() -> tuple[BrowserConnectorNormalizationRule, ...]:
    """Return all active connector normalization rule metadata."""
    return BROWSER_CONNECTOR_NORMALIZATION_RULES

"""
小红书平台适配器
对接小红书开放平台: 笔记管理、数据统计、私信、店铺
"""

from typing import Any

from app.core.logging import get_logger
from app.platforms.base import PlatformAdapter

logger = get_logger(__name__)


class XiaohongshuAdapter(PlatformAdapter):
    def __init__(self, app_id: str = None, app_secret: str = None):
        self._app_id = app_id
        self._app_secret = app_secret
        self._available = bool(app_id and app_secret)

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {"name": "小红书", "code": "xiaohongshu", "icon": "📕"}

    def get_note_list(self, page: int = 1, size: int = 20) -> list[dict]:
        if not self._available:
            self._require_available("get_note_list")
        self._raise_external_api_unavailable(
            "get_note_list",
            RuntimeError("live note list API is not implemented"),
            fallback_attempted=True,
        )
        return [
            {
                "note_id": f"xhs_note_{page}_{i}",
                "title": f"种草笔记-{['夏季护肤','穿搭分享','租房改造'][i%3]}",
                "type": "图文",
                "likes": 3200 - i * 200,
                "saves": 1500 - i * 100,
                "comments": 280 - i * 20,
                "published": "2026-05-28",
                "tags": ["护肤", "好物推荐", "国货"],
            }
            for i in range(min(size, 5))
        ]

    def get_note_detail(self, note_id: str) -> dict:
        if not self._available:
            self._require_available("get_note_detail")
        self._raise_external_api_unavailable(
            "get_note_detail",
            RuntimeError("live note detail API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "note_id": note_id,
            "title": "种草笔记详情",
            "content": "正文内容略...",
            "images": [f"https://ci.xiaohongshu.com/{i}.jpg" for i in range(3)],
            "views": 58000,
            "likes": 3200,
            "saves": 1500,
            "comments": 280,
            "shares": 450,
        }

    def get_private_messages(self, page: int = 1, limit: int = 20,
                               unread_only: bool = True) -> list[dict]:
        if not self._available:
            self._require_available("get_private_messages")
        self._raise_external_api_unavailable(
            "get_private_messages",
            RuntimeError("live private message API is not implemented"),
            fallback_attempted=True,
        )
        return [
            {
                "msg_id": f"msg_{page}_{i}",
                "from_user": f"用户_{i}",
                "content": ["请问这个产品还补货吗？", "已下单，什么时候发货？",
                            "能便宜点吗？"][i % 3],
                "time": "2026-05-27 14:30",
                "unread": unread_only,
            }
            for i in range(min(limit, 3))
        ]

    def post_note(self, title: str, content: str, images: list[str] = None,
                    tags: list[str] = None, is_draft: bool = False) -> dict:
        if not self._available:
            self._require_available("post_note")
        self._raise_external_api_unavailable(
            "post_note",
            RuntimeError("live note publishing API is not implemented"),
            fallback_attempted=True,
        )
        logger.info("xiaohongshu_note_queued", title=title[:50])
        return {
            "status": "draft" if is_draft else "published",
            "note_id": f"xhs_{hash(title) % 100000:05d}",
            "title": title,
            "publish_time": "2026-05-28 10:00",
        }

    def search_creators(self, category: str, count: int = 10) -> list[dict]:
        if not self._available:
            self._require_available("search_creators")
        self._raise_external_api_unavailable(
            "search_creators",
            RuntimeError("creator search is not supported by xiaohongshu adapter"),
            fallback_attempted=True,
        )
        return [{"platform": "xiaohongshu", "category": category,
                 "note": "小红书达人搜索通过蒲公英平台"}]

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict | None:
        if not self._available:
            self._require_available("get_campaign_report")
        self._raise_external_api_unavailable(
            "get_campaign_report",
            RuntimeError("campaign report is not supported by xiaohongshu adapter"),
            fallback_attempted=True,
        )

    def get_shop_data(self, shop_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        if not self._available:
            self._require_available("get_shop_data")
        self._raise_external_api_unavailable(
            "get_shop_data",
            RuntimeError("live shop data API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "shop_id": shop_id,
            "platform": "xiaohongshu",
            "shop_name": f"小红书店铺_{shop_id[:8]}",
            "gmv_30d": 280000,
            "gmv_growth": 22.5,
            "uv_30d": 65000,
            "conversion_rate": 5.8,
            "avg_price": 158.0,
            "note_count_30d": 320,
            "avg_note_engagement": 4.2,
            "top_products": [
                {"name": "种草好物A", "sales_30d": 1800, "revenue": 72000},
                {"name": "种草好物B", "sales_30d": 1200, "revenue": 48000},
            ],
        }

    def get_portfolio_stats(self, date_range: str = "7d") -> dict:
        if not self._available:
            self._require_available("get_portfolio_stats")
        self._raise_external_api_unavailable(
            "get_portfolio_stats",
            RuntimeError("live portfolio stats API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "period": date_range,
            "total_notes": 45,
            "total_views": 285000,
            "total_likes": 12000,
            "total_saves": 8500,
            "total_comments": 3200,
            "total_followers": 32500,
            "follower_growth": 1200,
        }

"""
蝉妈妈平台适配器 (taobao Competitor Intelligence)
提供抖音电商竞品数据: 达人排行、商品趋势、直播数据、短视频分析
"""

from typing import Any

from app.core.logging import get_logger
from app.platforms.base import PlatformAdapter

logger = get_logger(__name__)


class ChanMamaAdapter(PlatformAdapter):
    def __init__(self, api_key: str = None):
        self._api_key = api_key
        self._available = bool(api_key)

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {"name": "蝉妈妈", "code": "chanmama", "type": "competitive_intelligence"}

    def search_kols(self, category: str, platform: str = "douyin",
                      min_followers: int = 10000, max_followers: int = 10000000,
                      limit: int = 10) -> list[dict]:
        if not self._available:
            self._require_available("search_kols")
        self._raise_external_api_unavailable(
            "search_kols",
            RuntimeError("live KOL search API is not implemented"),
            fallback_attempted=True,
        )
        return self._mock_kol_search(category, min_followers, max_followers, limit)

    def get_kol_detail(self, kol_id: str) -> dict:
        if not self._available:
            self._require_available("get_kol_detail")
        self._raise_external_api_unavailable(
            "get_kol_detail",
            RuntimeError("live KOL detail API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "kol_id": kol_id,
            "name": f"达人_{kol_id[:6]}",
            "followers": 520000,
            "avg_views": 85000,
            "avg_likes": 3200,
            "avg_comments": 450,
            "engagement_rate": 3.8,
            "category": "美妆护肤",
            "gender_ratio": {"male": 22.5, "female": 77.5},
            "age_distribution": {"18-24": 35, "25-30": 40, "31-40": 20, "40+": 5},
            "recent_videos": [
                {"title": "夏日护肤好物推荐", "views": 120000, "likes": 8500},
                {"title": "平价vs大牌测评", "views": 95000, "likes": 7200},
            ],
            "live_avg_gmv": 45000,
            "live_avg_uv": 28000,
        }

    def get_hot_products(self, category: str = None, limit: int = 10) -> list[dict]:
        if not self._available:
            self._require_available("get_hot_products")
        self._raise_external_api_unavailable(
            "get_hot_products",
            RuntimeError("live hot products API is not implemented"),
            fallback_attempted=True,
        )
        return self._mock_hot_products(category, limit)

    def get_live_room_ranking(self, category: str = None,
                                sort_by: str = "gmv", limit: int = 10) -> list[dict]:
        if not self._available:
            self._require_available("get_live_room_ranking")
        self._raise_external_api_unavailable(
            "get_live_room_ranking",
            RuntimeError("live room ranking API is not implemented"),
            fallback_attempted=True,
        )
        return [
            {
                "rank": i + 1,
                "room_name": f"直播间{i + 1}",
                "host": f"主播_{i}",
                "gmv": 120000 - i * 5000,
                "uv": 45000 - i * 2000,
                "category": category or "综合",
            }
            for i in range(min(limit, 5))
        ]

    def search_creators(self, category: str, count: int = 10) -> list[dict]:
        return self.search_kols(category, limit=count)

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict | None:
        if not self._available:
            self._require_available("get_campaign_report")
        self._raise_external_api_unavailable(
            "get_campaign_report",
            RuntimeError("live campaign report API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "kol_id": kol_id,
            "campaign_id": campaign_id,
            "gmv": 85000,
            "roi": 3.2,
            "impressions": 520000,
            "clicks": 18000,
            "conversions": 1200,
            "conversion_rate": 6.67,
            "cpa": 28.5,
        }

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
            "platform": "chanmama",
            "shop_name": f"店铺_{shop_id[:8]}",
            "gmv_30d": 520000,
            "gmv_growth": 8.3,
            "uv_30d": 95000,
            "conversion_rate": 4.1,
            "avg_price": 128.5,
            "category_ranking": 12,
            "competitor_count": 45,
            "market_share": 2.3,
            "top_products": [
                {"name": "热销品A", "sales_30d": 4500, "market_share": 1.2},
                {"name": "热销品B", "sales_30d": 3200, "market_share": 0.8},
            ],
        }

    def _mock_kol_search(self, category: str, min_fans: int, max_fans: int,
                           limit: int) -> list[dict]:
        categories = {
            "美妆": ["李佳琦Austin", "程十安an", "仙姆SamChak"],
            "服饰": ["胡楚靓", "阿油", "小詹morning"],
            "美食": ["麻辣德子", "日食记", "办公室小野"],
            "数码": ["钟文泽", "李大锤同学", "小白测评"],
            "母婴": ["年糕妈妈", "小刚几", "小小包麻麻"],
        }
        names = categories.get(category, ["达人A", "达人B", "达人C"])
        return [
            {
                "id": f"kol_{category}_{i}",
                "name": names[i % len(names)],
                "followers": 150000 + i * 100000,
                "avg_views": 25000 + i * 5000,
                "engagement_rate": 3.2 + i * 0.3,
                "category": category,
                "verified": True,
                "mcn": f"MCN机构{i % 3 + 1}",
            }
            for i in range(min(limit, len(names)))
        ]

    def _mock_hot_products(self, category: str, limit: int) -> list[dict]:
        return [
            {
                "product_id": f"hot_{i}",
                "name": f"爆款商品_{['防晒喷雾','美白精华','补水仪'][i%3]}",
                "price": 99 + i * 20,
                "sales_7d": 5000 - i * 300,
                "trend": ["上升", "平稳", "下降"][i % 3],
                "category": category or "美妆",
            }
            for i in range(min(limit, 5))
        ]

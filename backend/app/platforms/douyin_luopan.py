"""
抖音罗盘平台适配器 (taobao E-commerce Data Compass)
提供抖音电商经营数据分析: 店铺总览、商品分析、直播分析、短视频分析、人群洞察、竞争分析
"""

from typing import Any

from app.core.logging import get_logger
from app.platforms.base import PlatformAdapter

logger = get_logger(__name__)


class DouyinLuopanAdapter(PlatformAdapter):
    """抖音电商数据罗盘适配器 (Douyin E-Commerce Data Compass)"""

    def __init__(self, app_id: str = None, app_secret: str = None,
                   shop_id: str = None):
        self._app_id = app_id
        self._app_secret = app_secret
        self._shop_id = shop_id
        self._available = bool(app_id and app_secret and shop_id)
        self._base_url = "https://open.douyin.com/compass/api"

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {
            "name": "抖音罗盘",
            "display_name": "抖音电商数据罗盘",
            "code": "douyin_luopan",
            "type": "data_analytics",
            "version": "v2.0",
            "capabilities": [
                "shop_overview",
                "product_analytics",
                "live_analytics",
                "video_analytics",
                "audience_insights",
                "competitive_analysis",
                "real_time_dashboard",
            ],
        }

    def get_shop_overview(self, date_range: str = "7d") -> dict[str, Any]:
        return {
            "shop_id": self._shop_id,
            "period": date_range,
            "gmv": 425000.00,
            "gmv_growth": 18.9,
            "gmv_target_completion": 85.2,
            "order_count": 5200,
            "avg_order_value": 81.73,
            "conversion_rate": 3.8,
            "uv": 138000,
            "pv": 580000,
            "refund_rate": 4.2,
            "dsr_score": 4.85,
            "traffic_sources": {
                "live_streaming": 42.5,
                "short_video": 28.3,
                "search": 15.2,
                "recommendation": 10.5,
                "other": 3.5,
            },
            "real_time": {
                "current_uv": 320,
                "current_gmv": 8500.00,
                "peak_hour": "20:00-21:00",
            },
        }

    def get_product_analytics(self, product_id: str = None,
                                sort_by: str = "gmv",
                                limit: int = 10) -> list[dict]:
        return [
            {
                "product_id": f"P{25052800 + i}",
                "name": f"热卖商品_{['A防晒套装','B真丝枕套','C咖啡礼盒'][i%3]}",
                "price": 89.00 + i * 30,
                "gmv_30d": 128000 - i * 15000,
                "sales_30d": 1450 - i * 150,
                "conversion_rate": 4.2 - i * 0.3,
                "gmv_growth": 12.5 - i * 2.1,
                "stock_status": "充足" if i < 3 else "紧张",
                "traffic_from_live": 55 - i * 4,
                "traffic_from_video": 30 + i * 2,
                "traffic_from_search": 15 - i * 1,
            }
            for i in range(min(limit, 5))
        ]

    def get_live_analytics(self, room_id: str = None,
                             date_range: str = "7d") -> dict[str, Any]:
        return {
            "shop_id": self._shop_id,
            "period": date_range,
            "total_live_sessions": 28,
            "total_duration_hours": 98.5,
            "total_gmv": 285000.00,
            "avg_online_users": 1850,
            "peak_online_users": 5200,
            "avg_watch_duration_sec": 320,
            "interaction_rate": 4.8,
            "conversion_rate": 5.2,
            "top_products_in_live": [
                {"name": "主推款A", "gmv": 85000, "conversion": 6.2},
                {"name": "引流款B", "gmv": 42000, "conversion": 8.5},
            ],
            "best_time_slot": {"day": "周五", "time": "20:00-22:00", "avg_gmv": 18000},
            "anchor_performance": [
                {"name": "主播A", "avg_gmv_per_hour": 3200, "retention": 65},
                {"name": "主播B", "avg_gmv_per_hour": 2800, "retention": 58},
            ],
        }

    def get_video_analytics(self, video_id: str = None,
                              date_range: str = "7d") -> dict[str, Any]:
        return {
            "shop_id": self._shop_id,
            "period": date_range,
            "total_videos": 42,
            "total_views": 850000,
            "total_likes": 52000,
            "total_comments": 8200,
            "total_shares": 3800,
            "avg_engagement_rate": 4.5,
            "video_gmv": 140000.00,
            "gmv_per_video": 3333.33,
            "top_videos": [
                {
                    "video_id": "V20260528001",
                    "title": "夏日护肤routine #护肤 #防晒",
                    "views": 85000,
                    "likes": 6200,
                    "comments": 850,
                    "gmv": 28000,
                    "publish_time": "2026-05-25T18:30:00",
                },
                {
                    "video_id": "V20260527002",
                    "title": "开箱测评：这款防晒好用吗？",
                    "views": 72000,
                    "likes": 5100,
                    "comments": 720,
                    "gmv": 21000,
                    "publish_time": "2026-05-27T12:00:00",
                },
            ],
            "best_publish_time": "18:00-20:00",
            "best_content_type": "教程/测评",
        }

    def get_audience_insights(self) -> dict[str, Any]:
        return {
            "shop_id": self._shop_id,
            "total_fans": 285000,
            "new_fans_30d": 12500,
            "gender_ratio": {"male": 22.8, "female": 77.2},
            "age_distribution": {
                "18-24": 32.5,
                "25-30": 38.2,
                "31-35": 18.5,
                "36-40": 7.3,
                "40+": 3.5,
            },
            "top_regions": ["广东", "浙江", "江苏", "上海", "北京"],
            "city_tier": {"一线": 35, "新一线": 28, "二线": 22, "三线及以下": 15},
            "interests": ["美妆护肤", "穿搭时尚", "生活家居", "美食", "母婴"],
            "device": {"ios": 42, "android": 58},
            "active_hours": {
                "morning_8-12": 18,
                "afternoon_12-18": 28,
                "evening_18-22": 38,
                "night_22-8": 16,
            },
        }

    def get_competitive_analysis(self, category: str = None) -> dict[str, Any]:
        return {
            "shop_id": self._shop_id,
            "category": category or "美妆护肤",
            "market_ranking": 15,
            "market_share": 2.8,
            "competitors": [
                {
                    "name": "竞品店铺A",
                    "gmv_30d": 580000,
                    "followers": 420000,
                    "avg_price": 95.00,
                    "strength": "直播运营",
                },
                {
                    "name": "竞品店铺B",
                    "gmv_30d": 380000,
                    "followers": 310000,
                    "avg_price": 72.00,
                    "strength": "短视频内容",
                },
                {
                    "name": "竞品店铺C",
                    "gmv_30d": 720000,
                    "followers": 580000,
                    "avg_price": 120.00,
                    "strength": "达人合作",
                },
            ],
            "competitive_advantage": ["产品差异化", "价格优势", "直播频次高"],
            "competitive_gap": ["达人矩阵较弱", "品牌知名度待提升"],
            "category_trend": {
                "gmv_trend": "上升",
                "search_trend": "上升",
                "competition_intensity": "高",
            },
        }

    def get_real_time_dashboard(self) -> dict[str, Any]:
        return {
            "timestamp": "2026-05-29T14:30:00",
            "today": {
                "gmv": 12500.00,
                "gmv_vs_yesterday": 8.5,
                "order_count": 158,
                "uv": 4200,
                "conversion_rate": 3.76,
                "top_product": "防晒套装A",
                "live_status": "直播中",
                "live_uv": 850,
                "live_gmv": 3200,
            },
            "alerts": [
                {"type": "warning", "message": "退款率较昨日上升1.2%"},
                {"type": "info", "message": "直播间流量高峰时段已到"},
            ],
        }

    def search_creators(self, category: str, count: int = 10) -> list[dict[str, Any]]:
        return []

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict[str, Any] | None:
        return {
            "kol_id": kol_id,
            "campaign_id": campaign_id,
            "platform": "douyin_luopan",
            "gmv": 45000,
            "roi": 2.8,
            "impressions": 420000,
            "clicks": 18000,
            "conversions": 450,
            "live_gmv": 32000,
            "video_gmv": 13000,
        }

    def get_shop_data(self, shop_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        overview = self.get_shop_overview()
        overview["shop_id"] = shop_id
        overview["platform"] = "douyin_luopan"
        if metrics:
            return {k: v for k, v in overview.items() if k in metrics or k in ("shop_id", "platform")}
        return overview

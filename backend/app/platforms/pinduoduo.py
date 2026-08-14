"""
拼多多开放平台适配器
提供商品/订单/物流/推广/多多进宝 API 对接
"""

from typing import Any

from app.core.logging import get_logger
from app.platforms.base import PlatformAdapter

logger = get_logger(__name__)


class PinduoduoOpenAdapter(PlatformAdapter):
    def __init__(self, pdd_client_id: str = None, pdd_client_secret: str = None,
                   pdd_access_token: str = None, mall_id: str = None):
        self._client_id = pdd_client_id
        self._client_secret = pdd_client_secret
        self._access_token = pdd_access_token
        self._mall_id = mall_id
        self._available = bool(pdd_client_id and pdd_client_secret and pdd_access_token)

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {"name": "拼多多开放平台", "code": "pinduoduo_open", "type": "comprehensive"}

    def get_shop_overview(self, date: str) -> dict:
        if not self._available:
            self._require_available("get_shop_overview")
        self._raise_external_api_unavailable(
            "get_shop_overview",
            RuntimeError("live shop overview API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "date": date,
            "gmv": 215000.00,
            "order_count": 2800,
            "avg_order_value": 76.80,
            "conversion_rate": 4.5,
            "refund_rate": 3.8,
            "dsr": {"description": 4.82, "service": 4.75, "logistics": 4.80},
        }

    def get_product_list(self, page: int = 1, page_size: int = 20) -> list[dict]:
        if not self._available:
            self._require_available("get_product_list")
        self._raise_external_api_unavailable(
            "get_product_list",
            RuntimeError("live product API is not implemented"),
            fallback_attempted=True,
        )
        return [
            {
                "goods_id": f"pdd_{i}",
                "title": f"拼多多商品-{i}",
                "price": 29.90 + i * 5,
                "sale_volume": 5200 - i * 100,
                "gmv": 155480.00,
                "rating": 4.7,
                "stock": 1500,
                "status": "online" if i < 3 else "offline",
            }
            for i in range(min(page_size, 5))
        ]

    def get_order_list(self, order_status: str = "paid",
                       start_time: str = None, end_time: str = None,
                       page: int = 1, page_size: int = 20) -> list[dict]:
        if not self._available:
            self._require_available("get_order_list")
        self._raise_external_api_unavailable(
            "get_order_list",
            RuntimeError("live order API is not implemented"),
            fallback_attempted=True,
        )
        return [
            {
                "order_sn": f"PDD{2501010000 + i}",
                "goods_name": f"商品_{i}",
                "amount": 59.90,
                "order_status": order_status,
                "buyer_name": f"买家_{i}",
                "create_time": "2026-05-28T10:00:00",
                "logistics_status": "shipped" if order_status == "paid" else "pending",
            }
            for i in range(min(page_size, 3))
        ]

    def get_logistics_info(self, order_sn: str) -> dict:
        if not self._available:
            self._require_available("get_logistics_info")
        self._raise_external_api_unavailable(
            "get_logistics_info",
            RuntimeError("live logistics API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "order_sn": order_sn,
            "carrier": "中通快递",
            "tracking_number": f"ZT{2505280001}",
            "status": "运输中",
            "nodes": [
                {"time": "2026-05-28 08:00", "desc": "已揽收"},
                {"time": "2026-05-28 12:00", "desc": "到达中转中心"},
                {"time": "2026-05-28 18:00", "desc": "运输中"},
            ],
        }

    def get_promotion_metrics(self, date: str) -> dict:
        if not self._available:
            self._require_available("get_promotion_metrics")
        self._raise_external_api_unavailable(
            "get_promotion_metrics",
            RuntimeError("live promotion metrics API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "date": date,
            "ad_spend": 12500.00,
            "roi": 4.8,
            "impressions": 125000,
            "clicks": 8500,
            "ctr": 6.8,
            "conversions": 520,
            "cvr": 6.12,
            "cpc": 1.47,
            "cpa": 24.04,
        }

    def get_category_data(self, category_id: str) -> dict:
        if not self._available:
            self._require_available("get_category_data")
        self._raise_external_api_unavailable(
            "get_category_data",
            RuntimeError("live category API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "category_id": category_id,
            "name": "日用百货",
            "total_gmv": 8.5e7,
            "avg_price": 35.60,
            "top_keywords": ["家居好物", "收纳神器", "实用小物件"],
            "activity_count": 12,
        }

    def search_creators(self, category: str, count: int = 10) -> list[dict]:
        if not self._available:
            self._require_available("search_creators")
        self._raise_external_api_unavailable(
            "search_creators",
            RuntimeError("creator search is not supported by pinduoduo adapter"),
            fallback_attempted=True,
        )
        return []

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict | None:
        if not self._available:
            self._require_available("get_campaign_report")
        self._raise_external_api_unavailable(
            "get_campaign_report",
            RuntimeError("campaign report is not supported by pinduoduo adapter"),
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
            "platform": "pinduoduo",
            "shop_name": f"拼多多店铺_{shop_id[:8]}",
            "gmv_30d": 320000,
            "gmv_growth": 15.2,
            "order_count_30d": 4800,
            "avg_order_value": 66.7,
            "conversion_rate": 4.5,
            "refund_rate": 3.6,
            "dsr": {"description": 4.82, "service": 4.75, "logistics": 4.80},
            "top_products": [
                {"name": "爆款日用A", "sales_30d": 8500, "revenue": 42500},
                {"name": "爆款日用B", "sales_30d": 6200, "revenue": 31000},
            ],
        }

"""
抖音电商平台适配器 (抖店)
对接抖音开放平台 Open API: 商品、订单、物流、售后
"""

from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.platforms.base import PlatformAdapter

logger = get_logger(__name__)


class DouyinShopAdapter(PlatformAdapter):
    def __init__(self, api_key: str = None, api_secret: str = None, shop_id: str = None):
        self._api_key = api_key
        self._api_secret = api_secret
        self._shop_id = shop_id
        self._available = bool(api_key and api_secret and shop_id)
        self._base_url = "https://openapi-fxg.jinritemai.com"

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {
            "name": "抖音电商",
            "code": "douyin_shop",
            "base_url": self._base_url,
            "shop_id": self._shop_id,
        }

    def get_product_list(self, page: int = 1, size: int = 20,
                           status: str = "on_sale") -> list[dict[str, Any]]:
        if not self._available:
            self._require_available("get_product_list")
        self._raise_external_api_unavailable(
            "get_product_list",
            RuntimeError("live product API is not implemented"),
            fallback_attempted=True,
        )
        try:
            logger.info("douyin_shop_fetching_products", page=page)
            if not self._available:
                return self._mock_product_list(page, size, status)
            return self._mock_product_list(page, size, status)
        except Exception as e:
            return self._handle_api_error(e, self._mock_product_list(page, size, status))

    def get_order_list(self, start_time: str, end_time: str,
                         page: int = 1, size: int = 20,
                         order_status: str = None) -> list[dict[str, Any]]:
        if not self._available:
            self._require_available("get_order_list")
        self._raise_external_api_unavailable(
            "get_order_list",
            RuntimeError("live order API is not implemented"),
            fallback_attempted=True,
        )
        try:
            logger.info("douyin_shop_fetching_orders", start=start_time, end=end_time)
            if not self._available:
                return self._mock_order_list(start_time, end_time, page, size)
            return self._mock_order_list(start_time, end_time, page, size)
        except Exception as e:
            return self._handle_api_error(e, [])

    def get_logistics_info(self, order_id: str) -> dict[str, Any]:
        if not self._available:
            self._require_available("get_logistics_info")
        self._raise_external_api_unavailable(
            "get_logistics_info",
            RuntimeError("live logistics API is not implemented"),
            fallback_attempted=True,
        )
        try:
            if not self._available:
                return self._mock_logistics(order_id)
            return self._mock_logistics(order_id)
        except Exception as e:
            return self._handle_api_error(e, {})

    def get_after_sale_list(self, start_time: str, end_time: str,
                              page: int = 1, size: int = 20) -> list[dict[str, Any]]:
        if not self._available:
            self._require_available("get_after_sale_list")
        self._raise_external_api_unavailable(
            "get_after_sale_list",
            RuntimeError("live after-sale API is not implemented"),
            fallback_attempted=True,
        )
        try:
            if not self._available:
                return self._mock_after_sales(start_time, end_time, page, size)
            return self._mock_after_sales(start_time, end_time, page, size)
        except Exception as e:
            return self._handle_api_error(e, [])

    def search_creators(self, category: str, count: int = 10) -> list[dict[str, Any]]:
        if not self._available:
            self._require_available("search_creators")
        self._raise_external_api_unavailable(
            "search_creators",
            RuntimeError("creator search is not supported by douyin_shop adapter"),
            fallback_attempted=True,
        )
        return [{"platform": "douyin_shop", "category": category,
                 "message": "请使用 DouyinStarAdapter 进行达人搜索"}]

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict[str, Any] | None:
        if not self._available:
            self._require_available("get_campaign_report")
        self._raise_external_api_unavailable(
            "get_campaign_report",
            RuntimeError("campaign report is not supported by douyin_shop adapter"),
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
            "platform": "douyin_shop",
            "shop_name": f"抖音小店_{shop_id[:8]}",
            "gmv_30d": 420000,
            "gmv_growth": 18.9,
            "uv_30d": 95000,
            "live_gmv_30d": 280000,
            "video_gmv_30d": 140000,
            "conversion_rate": 4.2,
            "avg_price": 89.5,
            "live_room_count": 45,
            "top_products": [
                {"name": "直播爆款A", "sales_30d": 5200, "revenue": 156000},
                {"name": "视频爆款B", "sales_30d": 3800, "revenue": 76000},
            ],
        }

    def _mock_product_list(self, page: int, size: int, status: str) -> list[dict]:
        return [
            {
                "product_id": f"dy_prod_{page}_{i}",
                "title": f"商品{i}-{['夏季新款连衣裙','高端面膜套装','智能蓝牙耳机'][i%3]}",
                "price": 9900 + i * 1000,
                "stock": 200 - i * 10,
                "status": status,
                "sales_7d": 150 - i * 5,
                "image": f"https://img.example.com/prod_{i}.jpg",
            }
            for i in range(min(size, 5))
        ]

    def _mock_order_list(self, start: str, end: str, page: int, size: int) -> list[dict]:
        return [
            {
                "order_id": f"dy_ord_{page}_{i}",
                "product": f"商品{i}",
                "amount": 9900 + i * 500,
                "status": ["待发货", "已发货", "已完成", "已退款"][i % 4],
                "buyer": "张*三",
                "created": start,
            }
            for i in range(min(size, 5))
        ]

    def _mock_logistics(self, order_id: str) -> dict:
        return {
            "order_id": order_id,
            "courier": "顺丰快递",
            "tracking_no": f"SF{order_id[-8:]}",
            "status": "运输中",
            "estimated_delivery": datetime.now().strftime("%Y-%m-%d"),
            "nodes": [
                {"time": "08:00", "status": "已揽收"},
                {"time": "12:00", "status": "到达中转站"},
                {"time": "18:00", "status": "正在派送"},
            ],
        }

    def _mock_after_sales(self, start: str, end: str, page: int, size: int) -> list[dict]:
        return [
            {
                "id": f"as_{page}_{i}",
                "order_id": f"dy_ord_{page}_{i}",
                "type": ["退货退款", "仅退款", "换货"][i % 3],
                "reason": ["质量问题", "不喜欢", "尺寸不合适"][i % 3],
                "status": "待处理",
                "created": start,
            }
            for i in range(min(size, 3))
        ]

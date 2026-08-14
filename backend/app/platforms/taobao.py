"""
淘宝/天猫平台适配器
对接淘宝开放平台(Taobao Open Platform): 生意参谋、商品、订单、退款
"""

from typing import Any

from app.core.logging import get_logger
from app.platforms.base import PlatformAdapter

logger = get_logger(__name__)


class TaobaoAdapter(PlatformAdapter):
    def __init__(self, app_key: str = None, app_secret: str = None,
                   session_key: str = None):
        self._app_key = app_key
        self._app_secret = app_secret
        self._session_key = session_key
        self._available = bool(app_key and app_secret and session_key)
        self._base_url = "https://eco.taobao.com/router/rest"

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {
            "name": "淘宝/天猫",
            "code": "taobao",
            "base_url": self._base_url,
        }

    def get_shop_metrics(self, date: str) -> dict:
        if not self._available:
            self._require_available("get_shop_metrics")
        self._raise_external_api_unavailable(
            "get_shop_metrics",
            RuntimeError("live shop metrics API is not implemented"),
            fallback_attempted=True,
        )
        try:
            return self._mock_shop_metrics(date)
        except Exception as e:
            return self._handle_api_error(e, {})

    def get_item_list(self, page: int = 1, size: int = 20,
                        status: str = "onsale") -> list[dict]:
        if not self._available:
            self._require_available("get_item_list")
        self._raise_external_api_unavailable(
            "get_item_list",
            RuntimeError("live item API is not implemented"),
            fallback_attempted=True,
        )
        try:
            return self._mock_item_list(page, size, status)
        except Exception as e:
            return self._handle_api_error(e, [])

    def get_order_list(self, start: str, end: str,
                         page: int = 1, size: int = 20) -> list[dict]:
        if not self._available:
            self._require_available("get_order_list")
        self._raise_external_api_unavailable(
            "get_order_list",
            RuntimeError("live order API is not implemented"),
            fallback_attempted=True,
        )
        try:
            return self._mock_order_list(start, end, page, size)
        except Exception as e:
            return self._handle_api_error(e, [])

    def search_creators(self, category: str, count: int = 10) -> list[dict]:
        if not self._available:
            self._require_available("search_creators")
        self._raise_external_api_unavailable(
            "search_creators",
            RuntimeError("creator search is not supported by taobao adapter"),
            fallback_attempted=True,
        )
        return [{"platform": "taobao", "note": "淘宝达人搜索可通过淘宝联盟API"}]

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict | None:
        if not self._available:
            self._require_available("get_campaign_report")
        self._raise_external_api_unavailable(
            "get_campaign_report",
            RuntimeError("campaign report is not supported by taobao adapter"),
            fallback_attempted=True,
        )
        return None

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
            "platform": "taobao",
            "shop_name": f"天猫店铺_{shop_id[:8]}",
            "gmv_30d": 680000,
            "gmv_growth": 5.8,
            "uv_30d": 120000,
            "pv_30d": 480000,
            "conversion_rate": 3.2,
            "avg_order_value": 185.5,
            "refund_rate": 4.1,
            "top_products": [
                {"name": "热卖款A", "sales_30d": 5200, "revenue": 260000},
                {"name": "热卖款B", "sales_30d": 3800, "revenue": 152000},
            ],
        }

    def _mock_shop_metrics(self, date: str) -> dict:
        return {
            "date": date,
            "uv": 52800,
            "pv": 215000,
            "gmv": 324500.00,
            "pay_order_count": 1850,
            "pay_buyer_count": 1620,
            "conversion_rate": 3.51,
            "avg_order_value": 175.40,
            "refund_rate": 4.2,
        }

    def _mock_item_list(self, page: int, size: int, status: str) -> list[dict]:
        return [
            {
                "num_iid": f"tb_item_{page}_{i}",
                "title": f"天猫商品-{['防晒霜套装','真丝围巾','进口咖啡机'][i%3]}",
                "price": 12800 + i * 500,
                "quantity": 500 - i * 20,
                "status": status,
            }
            for i in range(min(size, 5))
        ]

    def _mock_order_list(self, start: str, end: str, page: int, size: int) -> list[dict]:
        return [
            {
                "tid": f"tb_ord_{page}_{i}",
                "title": f"订单商品{i}",
                "payment": 128.00 + i * 25,
                "status": ["WAIT_SELLER_SEND_GOODS", "WAIT_BUYER_CONFIRM_GOODS",
                            "TRADE_FINISHED", "TRADE_CLOSED"][i % 4],
                "buyer_nick": "李**",
                "created": start,
            }
            for i in range(min(size, 5))
        ]

"""
投流平台适配器聚合模块
统一管理千川(抖音)/巨量引擎/万相台(淘宝)投放平台 API 对接
"""

from typing import Any

from app.core.logging import get_logger
from app.platforms.base import PlatformAdapter

logger = get_logger(__name__)


class QanchuanAdapter(PlatformAdapter):
    """千川投放平台适配器 (抖音电商广告)"""

    def __init__(self, advertiser_id: str = None, access_token: str = None,
                   app_id: str = None, secret: str = None):
        self._advertiser_id = advertiser_id
        self._access_token = access_token
        self._app_id = app_id
        self._secret = secret
        self._available = bool(advertiser_id and access_token)

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {"name": "千川投放", "code": "qianchuan", "type": "advertising"}

    def _fail_closed(self, operation: str) -> None:
        self._require_available(operation)
        self._raise_external_api_unavailable(
            operation,
            RuntimeError("live qianchuan API is not implemented"),
            fallback_attempted=True,
        )

    def create_campaign(self, name: str, budget: float, target: str,
                        creative_ids: list[str], targeting: dict = None) -> dict:
        self._fail_closed("create_campaign")
        return {
            "campaign_id": f"QC{2505280001}",
            "name": name,
            "status": "created",
            "daily_budget": budget,
            "target": target,
            "creative_ids": creative_ids,
            "targeting": targeting or {},
        }

    def get_campaign_status(self, campaign_id: str) -> dict:
        self._fail_closed("get_campaign_status")
        return {
            "campaign_id": campaign_id,
            "status": "running",
            "spend_today": 3850.00,
            "impressions": 58000,
            "clicks": 3200,
            "ctr": 5.52,
            "conversions": 156,
            "cvr": 4.88,
            "cpc": 1.20,
            "roi": 3.2,
            "cpa": 24.68,
            "budget_remaining": 6150.00,
        }

    def update_budget(self, campaign_id: str, new_budget: float) -> dict:
        self._fail_closed("update_budget")
        return {"campaign_id": campaign_id, "new_budget": new_budget, "status": "updated"}

    def pause_campaign(self, campaign_id: str) -> dict:
        self._fail_closed("pause_campaign")
        return {"campaign_id": campaign_id, "status": "paused"}

    def resume_campaign(self, campaign_id: str) -> dict:
        self._fail_closed("resume_campaign")
        return {"campaign_id": campaign_id, "status": "running"}

    def get_campaign_list(self, status: str = None) -> list[dict]:
        self._fail_closed("get_campaign_list")
        return [
            {"campaign_id": f"QC{2505280001+i}", "name": f"计划_{i+1}",
             "status": "running" if i < 2 else "paused",
             "daily_budget": 10000.00, "roi": 3.5 - i * 0.3}
            for i in range(3)
        ]

    def search_creators(self, category: str, count: int = 10) -> list[dict]:
        self._fail_closed("search_creators")
        return []

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict | None:
        self._fail_closed("get_campaign_report")
        return None

    def get_shop_data(self, shop_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        self._fail_closed("get_shop_data")
        return {
            "shop_id": shop_id,
            "platform": "qianchuan",
            "ad_spend_30d": 85000,
            "ad_roi": 3.5,
            "ad_impressions": 2800000,
            "ad_clicks": 155000,
            "ad_conversions": 8200,
            "ctr": 5.5,
            "cvr": 5.3,
            "cpc": 0.55,
            "note": "千川投放平台侧重广告数据，店铺GMV请通过抖音小店获取",
        }


class OceanEngineAdapter(PlatformAdapter):
    """巨量引擎适配器 (抖音信息流/品牌广告)"""

    def __init__(self, advertiser_id: str = None, access_token: str = None):
        self._advertiser_id = advertiser_id
        self._access_token = access_token
        self._available = bool(advertiser_id and access_token)

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {"name": "巨量引擎", "code": "ocean_engine", "type": "advertising"}

    def _fail_closed(self, operation: str) -> None:
        self._require_available(operation)
        self._raise_external_api_unavailable(
            operation,
            RuntimeError("live ocean engine API is not implemented"),
            fallback_attempted=True,
        )

    def create_ad_group(self, name: str, campaign_id: str,
                        bid_amount: float, targeting: dict = None) -> dict:
        self._fail_closed("create_ad_group")
        return {
            "ad_group_id": f"OE{2505280001}",
            "name": name,
            "campaign_id": campaign_id,
            "bid_amount": bid_amount,
            "status": "created",
            "targeting": targeting or {},
        }

    def get_ad_performance(self, ad_group_id: str, date: str) -> dict:
        self._fail_closed("get_ad_performance")
        return {
            "ad_group_id": ad_group_id,
            "date": date,
            "spend": 5200.00,
            "impressions": 82000,
            "clicks": 4100,
            "ctr": 5.00,
            "conversions": 185,
            "cvr": 4.51,
            "cpc": 1.27,
            "roi": 2.9,
        }

    def get_audience_insights(self, ad_group_id: str) -> dict:
        self._fail_closed("get_audience_insights")
        return {
            "ad_group_id": ad_group_id,
            "age_distribution": {"18-24": 25, "25-34": 42, "35-44": 22, "45+": 11},
            "gender": {"male": 38, "female": 62},
            "top_regions": ["广东", "浙江", "江苏", "上海", "北京"],
            "top_interests": ["美妆", "穿搭", "家居", "母婴"],
        }

    def search_creators(self, category: str, count: int = 10) -> list[dict]:
        self._fail_closed("search_creators")
        return []

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict | None:
        self._fail_closed("get_campaign_report")
        return None

    def get_shop_data(self, shop_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        self._fail_closed("get_shop_data")
        return {
            "shop_id": shop_id,
            "platform": "ocean_engine",
            "ad_spend_30d": 120000,
            "ad_roi": 2.9,
            "ad_impressions": 4500000,
            "ad_clicks": 220000,
            "ctr": 4.9,
            "cvr": 4.1,
            "cpc": 0.55,
            "brand_lift": 12.5,
            "note": "巨量引擎侧重品牌广告和信息流投放，店铺GMV请通过抖音小店获取",
        }


class WanxiangtaiAdapter(PlatformAdapter):
    """万相台适配器 (淘宝/天猫智能投放)"""

    def __init__(self, app_key: str = None, app_secret: str = None,
                   session_key: str = None):
        self._app_key = app_key
        self._app_secret = app_secret
        self._session_key = session_key
        self._available = bool(app_key and app_secret and session_key)

    def is_available(self) -> bool:
        return self._available

    def get_platform_info(self) -> dict[str, Any]:
        return {"name": "万相台", "code": "wanxiangtai", "type": "advertising"}

    def _fail_closed(self, operation: str) -> None:
        self._require_available(operation)
        self._raise_external_api_unavailable(
            operation,
            RuntimeError("live wanxiangtai API is not implemented"),
            fallback_attempted=True,
        )

    def create_plan(self, name: str, daily_budget: float,
                    objective: str, product_ids: list[str]) -> dict:
        self._fail_closed("create_plan")
        return {
            "plan_id": f"WXT{2505280001}",
            "name": name,
            "daily_budget": daily_budget,
            "objective": objective,
            "product_ids": product_ids,
            "status": "created",
        }

    def get_plan_performance(self, plan_id: str, date: str) -> dict:
        self._fail_closed("get_plan_performance")
        return {
            "plan_id": plan_id,
            "date": date,
            "spend": 8500.00,
            "impressions": 156000,
            "clicks": 8200,
            "ctr": 5.26,
            "gmv": 52000.00,
            "roi": 6.12,
            "cpc": 1.04,
            "orders": 420,
        }

    def search_creators(self, category: str, count: int = 10) -> list[dict]:
        self._fail_closed("search_creators")
        return []

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict | None:
        self._fail_closed("get_campaign_report")
        return None

    def get_shop_data(self, shop_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        self._fail_closed("get_shop_data")
        return {
            "shop_id": shop_id,
            "platform": "wanxiangtai",
            "ad_spend_30d": 65000,
            "ad_roi": 6.1,
            "ad_impressions": 1800000,
            "ad_clicks": 98000,
            "ad_gmv": 396500,
            "ctr": 5.4,
            "cvr": 5.2,
            "cpc": 0.66,
            "note": "万相台侧重智能投放和全链路优化，店铺GMV请通过生意参谋获取",
        }

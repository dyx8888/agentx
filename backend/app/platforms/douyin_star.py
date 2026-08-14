"""
Douyin Star API Adapter for AgentX Stage 23
Provides real integration with Douyin Star platform API
"""

import hashlib
import hmac
import os
import time
from typing import Any

import requests

from app.core.logging import get_logger

from .base import PlatformAdapter

logger = get_logger(__name__)

class DouyinStarAdapter(PlatformAdapter):
    """
    Douyin Star platform API adapter
    Integrates with Douyin Star API for real KOL search and campaign data
    """

    def __init__(
        self,
        company_id: int = None,
        app_id: str = None,
        app_secret: str = None,
        access_token: str = None,
        advertiser_id: str = None,
        api_key: str = None,
        api_secret: str = None,
    ):
        """Initialize Douyin Star adapter"""
        self.api_key = api_key or app_id or access_token
        self.api_secret = api_secret or app_secret
        self.access_token = access_token
        self.advertiser_id = advertiser_id

        if company_id:
            # 从数据库获取公司专属凭证
            try:
                from app.database import db
                company = db.get_company(company_id)
                if company and company.platform_credentials:
                    import json
                    credentials = json.loads(company.platform_credentials)
                    douyin_creds = credentials.get('douyin_star', {})
                    if isinstance(douyin_creds, dict) and isinstance(
                        douyin_creds.get("credentials"), dict
                    ):
                        douyin_creds = douyin_creds["credentials"]
                    self.api_key = (
                        douyin_creds.get('api_key')
                        or douyin_creds.get('app_id')
                        or douyin_creds.get('access_token')
                        or self.api_key
                    )
                    self.api_secret = (
                        douyin_creds.get('api_secret')
                        or douyin_creds.get('app_secret')
                        or self.api_secret
                    )
                    self.access_token = douyin_creds.get("access_token") or self.access_token
                    self.advertiser_id = douyin_creds.get("advertiser_id") or self.advertiser_id
                    logger.info(f"Loaded company-specific credentials for company {company_id}")
            except Exception as e:
                logger.warning(f"Failed to load company credentials for {company_id}: {e}")

        # 如果没有公司专属凭证，降级到环境变量
        if not self.api_key or not self.api_secret:
            self.api_key = os.getenv('DOUYIN_STAR_API_KEY')
            self.api_secret = os.getenv('DOUYIN_STAR_API_SECRET')

        self.base_url = os.getenv('DOUYIN_STAR_API_BASE_URL', 'https://open.douyin.com/api/openapi')
        self.timeout = 30

        if not self.api_key or not self.api_secret:
            logger.warning("Douyin Star API credentials not configured")

    def _load_env_credentials(self):
        """Load credentials from environment variables"""
        self.api_key = os.getenv('DOUYIN_STAR_API_KEY')
        self.api_secret = os.getenv('DOUYIN_STAR_API_SECRET')
        self.base_url = os.getenv('DOUYIN_STAR_API_BASE_URL', 'https://open.douyin.com/api/openapi')

    def search_creators(self, category: str, count: int = 10) -> list[dict[str, Any]]:
        """
        Search for creators/KOLs using Douyin Star API
        
        Args:
            category: Category to search (e.g., "beauty", "fashion")
            count: Number of results to return
            
        Returns:
            List of creator dictionaries with Douyin Star data
        """
        if not self.is_available():
            self._require_available("search_creators")

        try:
            # 构建请求参数
            params = {
                'category': category,
                'page': 1,
                'page_size': count,
                'timestamp': int(time.time())
            }

            # 生成签名
            sign_str = '&'.join([f"{k}={params[k]}" for k in sorted(params.keys())])
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                sign_str.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            params['sign'] = signature

            # 发送请求
            url = f"{self.base_url}/creator/search"
            headers = {'X-Api-Key': self.api_key}
            response = requests.get(url, params=params, headers=headers, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                # 转换为统一格式
                creators = self._parse_creators_response(data)
                logger.info("platform_creators_retrieved", count=len(creators))
                self._log_api_call(
                    method="GET",
                    url=url,
                    params=params,
                    success=True,
                    response=creators
                )
                return creators
            else:
                logger.error("platform_api_error", status_code=response.status_code, response=response.text)
                return self._handle_api_error(
                    RuntimeError(f"Douyin Star API returned {response.status_code}"),
                    self._get_mock_creators(category, count),
                    operation="search_creators",
                )

        except Exception as e:
            logger.error("platform_exception", error=str(e))
            return self._handle_api_error(
                e,
                self._get_mock_creators(category, count),
                operation="search_creators",
            )

    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict[str, Any] | None:
        """
        Get campaign performance data from Douyin Star API
        
        Args:
            kol_id: Platform-specific KOL identifier
            campaign_id: Campaign identifier
            
        Returns:
            Campaign performance data or None if not found
        """
        if not self.is_available():
            self._require_available("get_campaign_report")
        self._raise_external_api_unavailable(
            "get_campaign_report",
            RuntimeError("live campaign report API is not implemented"),
            fallback_attempted=True,
        )

    def get_platform_info(self) -> dict[str, Any]:
        """
        Get Douyin Star platform information and capabilities
        """
        return {
            "name": "douyin_star",
            "display_name": "抖音星图",
            "description": "抖音官方创作者数据平台",
            "capabilities": [
                "creator_search",
                "campaign_analytics",
                "performance_tracking"
            ],
            "api_version": "v1.0",
            "auth_required": True,
            "rate_limits": {
                "search_per_minute": 100,
                "reports_per_hour": 1000
            }
        }

    def is_available(self) -> bool:
        """
        Check if Douyin Star adapter is properly configured
        """
        return bool(self.api_key and self.api_secret)

    def get_shop_data(self, shop_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        if not self.is_available():
            self._require_available("get_shop_data")
        self._raise_external_api_unavailable(
            "get_shop_data",
            RuntimeError("live shop data API is not implemented"),
            fallback_attempted=True,
        )
        return {
            "shop_id": shop_id,
            "platform": "douyin_star",
            "shop_name": f"店铺_{shop_id[:8]}",
            "gmv_30d": 450000,
            "gmv_growth": 12.5,
            "uv_30d": 82000,
            "conversion_rate": 3.8,
            "top_products": [
                {"name": "爆款商品A", "sales_30d": 3200, "revenue": 128000},
                {"name": "爆款商品B", "sales_30d": 2100, "revenue": 84000},
            ],
            "kol_collab_count": 15,
            "avg_kol_roi": 2.8,
        }

    def _get_mock_creators(self, category: str, count: int) -> list[dict[str, Any]]:
        """
        Get mock creator data that matches existing structure
        """
        mock_data = {
            "beauty": [
                {
                    "id": "douyin_beauty_001",
                    "nickname": "美妆达人小美",
                    "avatar": "https://example.com/avatar1.jpg",
                    "followers": 850000,
                    "following": 1200,
                    "likes": 2500000,
                    "videos": 180,
                    "category": "美妆",
                    "tags": ["护肤", "彩妆", "教程"],
                    "engagement_rate": 6.8,
                    "price_range": "15000-25000",
                    "platform": "douyin"
                },
                {
                    "id": "douyin_beauty_002",
                    "nickname": "彩妆达人Lisa",
                    "avatar": "https://example.com/avatar2.jpg",
                    "followers": 620000,
                    "following": 800,
                    "likes": 1800000,
                    "videos": 150,
                    "category": "美妆",
                    "tags": ["彩妆", "测评", "分享"],
                    "engagement_rate": 7.2,
                    "price_range": "12000-20000",
                    "platform": "douyin"
                },
                {
                    "id": "douyin_beauty_003",
                    "nickname": "护肤达人Anna",
                    "avatar": "https://example.com/avatar3.jpg",
                    "followers": 720000,
                    "following": 900,
                    "likes": 2100000,
                    "videos": 200,
                    "category": "美妆",
                    "tags": ["护肤", "保养", "分享"],
                    "engagement_rate": 6.5,
                    "price_range": "13000-22000",
                    "platform": "douyin"
                }
            ],
            "fashion": [
                {
                    "id": "douyin_fashion_001",
                    "nickname": "时尚达人小尚",
                    "avatar": "https://example.com/avatar3.jpg",
                    "followers": 980000,
                    "following": 2000,
                    "likes": 3200000,
                    "videos": 220,
                    "category": "时尚",
                    "tags": ["穿搭", "潮流", "搭配"],
                    "engagement_rate": 5.9,
                    "price_range": "18000-30000",
                    "platform": "douyin"
                }
            ]
        }

        creators = mock_data.get(category, [])
        actual_count = min(count, len(creators))
        return creators[:actual_count]

    def _parse_creators_response(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Parse real API response to unified format
        """
        try:
            # 假设 API 返回格式为 {"code": 0, "data": {"creators": [...]}}
            if 'data' in data and 'creators' in data['data']:
                return data['data']['creators']
            # 或者直接返回 creators 列表
            elif 'creators' in data:
                return data['creators']
            # 或者直接是列表
            elif isinstance(data, list):
                return data
            else:
                logger.warning("platform_unexpected_response", data=str(data))
                return []
        except Exception as e:
            logger.error("platform_parse_error", error=str(e))
            return []

    def _get_mock_campaign_report(self, kol_id: str, campaign_id: str) -> dict[str, Any]:
        """
        Get mock campaign report data
        """
        return {
            "kol_id": kol_id,
            "campaign_id": campaign_id,
            "campaign_name": f"活动{campaign_id}",
            "period": "2024-01-01 to 2024-01-31",
            "metrics": {
                "total_views": 1250000,
                "total_likes": 89000,
                "total_comments": 3400,
                "total_shares": 1200,
                "engagement_rate": 7.1,
                "conversion_rate": 2.3,
                "roi": 3.2
            },
            "content_performance": {
                "video_views": {
                    "best": {"video_id": "v001", "views": 156000, "title": "护肤产品介绍"},
                    "worst": {"video_id": "v005", "views": 23000, "title": "产品开箱"}
                },
                "engagement": {
                    "best": {"video_id": "v002", "rate": 8.9, "comments": 234},
                    "worst": {"video_id": "v003", "rate": 4.1, "comments": 45}
                }
            },
            "recommendations": [
                "继续发布护肤类内容，互动率较高",
                "优化视频发布时间，晚上8-10点效果最佳",
                "增加与用户互动，提升粉丝粘性"
            ],
            "created_at": "2024-01-31T23:59:59Z",
            "updated_at": "2024-01-31T23:59:59Z"
        }

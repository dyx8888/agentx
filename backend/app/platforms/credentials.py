"""
企业平台凭证管理
管理各公司绑定的多平台 API Key / Access Token，支持加密存储和运行时解密
"""

from typing import Any

from app.core.logging import get_logger
from app.platforms import PLATFORM_ADAPTERS

logger = get_logger(__name__)


CREDENTIAL_FIELD_MAP: dict[str, dict[str, str]] = {
    "douyin_star": {"app_id": "app_id", "app_secret": "app_secret",
                      "access_token": "access_token", "advertiser_id": "advertiser_id"},
    "douyin_shop": {"app_key": "app_key", "app_secret": "app_secret",
                      "shop_id": "shop_id", "access_token": "access_token"},
    "taobao": {"app_key": "app_key", "app_secret": "app_secret",
                "session_key": "session_key", "seller_id": "seller_id"},
    "chanmama": {"api_key": "api_key", "api_secret": "api_secret"},
    "xiaohongshu": {"app_id": "app_id", "app_secret": "app_secret",
                     "access_token": "access_token"},
    "shengyi_canshu": {"app_key": "app_key", "app_secret": "app_secret",
                         "session_key": "session_key", "seller_id": "seller_id"},
    "pinduoduo_open": {"pdd_client_id": "pdd_client_id",
                          "pdd_client_secret": "pdd_client_secret",
                          "pdd_access_token": "pdd_access_token",
                          "mall_id": "mall_id"},
    "qianchuan": {"advertiser_id": "advertiser_id",
                   "access_token": "access_token",
                   "app_id": "app_id", "secret": "secret"},
    "ocean_engine": {"advertiser_id": "advertiser_id",
                       "access_token": "access_token"},
    "wanxiangtai": {"app_key": "app_key", "app_secret": "app_secret",
                       "session_key": "session_key"},
}


# OAuth-managed fields are written by the OAuth callback and should not be
# required as manual credential inputs.
OAUTH_MANAGED_FIELDS: set[str] = {"refresh_token", "expires_at"}
OAUTH_MANAGED_FIELDS_BY_PLATFORM: dict[str, set[str]] = {
    "douyin_shop": {"refresh_token", "expires_at"},
    "taobao": {"refresh_token", "expires_at"},
    "pinduoduo_open": {"refresh_token", "expires_at"},
    "xiaohongshu": {"access_token", "refresh_token", "expires_at"},
}

OAUTH_PLATFORMS: set[str] = {"taobao", "douyin_shop", "pinduoduo_open", "xiaohongshu"}


def get_oauth_managed_fields(platform: str) -> set[str]:
    return set(OAUTH_MANAGED_FIELDS_BY_PLATFORM.get(platform, OAUTH_MANAGED_FIELDS))


def get_required_credentials(platform: str) -> dict[str, str]:
    """获取指定平台所需的凭证字段名列表"""
    return dict(CREDENTIAL_FIELD_MAP.get(platform, {}))


def build_adapter_kwargs(platform: str,
                           encrypted_credentials: dict[str, str]) -> dict[str, Any]:
    """
    从数据库加密凭证构建适配器初始化参数

    Args:
        platform: 平台标识
        encrypted_credentials: {field_name: encrypted_value} 字典

    Returns:
        适配器构造函数的关键字参数字典
    """
    field_map = CREDENTIAL_FIELD_MAP.get(platform)
    if not field_map:
        return {}

    kwargs = {}
    for db_field, adapter_param in field_map.items():
        encrypted_value = encrypted_credentials.get(db_field)
        if encrypted_value:
            try:
                from app.utils.encryption import encrypted_credential_manager
                kwargs[adapter_param] = encrypted_credential_manager.decrypt(encrypted_value)
            except Exception as exc:
                logger.warning(
                    "credential_decrypt_failed",
                    platform=platform,
                    field=db_field,
                    error=str(exc),
                )

    return kwargs


def validate_credentials(platform: str, credentials: dict[str, str]) -> dict[str, bool]:
    """
    验证指定平台的凭证是否完整

    Returns:
        {field_name: is_valid} 字典
    """
    field_map = CREDENTIAL_FIELD_MAP.get(platform, {})
    result = {}
    for db_field in field_map:
        result[db_field] = bool(credentials.get(db_field))
    return result


def get_platform_capabilities() -> dict[str, list[str]]:
    """
    获取所有平台的能力清单

    Returns:
        {platform_code: [capability_fields]} 字典
    """
    return {
        platform: list(fields.keys())
        for platform, fields in CREDENTIAL_FIELD_MAP.items()
        if platform in PLATFORM_ADAPTERS
    }


def get_supported_platforms() -> list[str]:
    """获取当前支持的所有平台标识列表"""
    return [
        p for p in CREDENTIAL_FIELD_MAP
        if p in PLATFORM_ADAPTERS
    ]

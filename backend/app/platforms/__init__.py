"""
Platform Adapters v2
统一平台适配器注册中心，支持所有电商平台对接
"""

import inspect

from app.platforms.ad_platforms import OceanEngineAdapter, QanchuanAdapter, WanxiangtaiAdapter
from app.platforms.base import PlatformAdapter
from app.platforms.chanmama import ChanMamaAdapter
from app.platforms.douyin_luopan import DouyinLuopanAdapter
from app.platforms.douyin_shop import DouyinShopAdapter
from app.platforms.douyin_star import DouyinStarAdapter
from app.platforms.pinduoduo import PinduoduoOpenAdapter
from app.platforms.shengyi_canshu import ShengyiCanshuAdapter
from app.platforms.taobao import TaobaoAdapter
from app.platforms.xiaohongshu import XiaohongshuAdapter

PLATFORM_ADAPTERS: dict[str, type[PlatformAdapter]] = {
    "douyin_star": DouyinStarAdapter,
    "douyin_luopan": DouyinLuopanAdapter,
    "douyin_shop": DouyinShopAdapter,
    "taobao": TaobaoAdapter,
    "chanmama": ChanMamaAdapter,
    "xiaohongshu": XiaohongshuAdapter,
    "shengyi_canshu": ShengyiCanshuAdapter,
    "pinduoduo_open": PinduoduoOpenAdapter,
    "qianchuan": QanchuanAdapter,
    "ocean_engine": OceanEngineAdapter,
    "wanxiangtai": WanxiangtaiAdapter,
}

_ACTIVE_ADAPTERS: dict[str, PlatformAdapter] = {}


def get_platform_adapter(platform_name: str, company_id: int = None,
                           api_credentials: dict = None) -> PlatformAdapter | None:
    cache_key = f"{platform_name}_{company_id or 'default'}"
    if cache_key in _ACTIVE_ADAPTERS:
        return _ACTIVE_ADAPTERS[cache_key]

    adapter_class = PLATFORM_ADAPTERS.get(platform_name)
    if not adapter_class:
        return None

    if api_credentials:
        adapter = adapter_class(**api_credentials)
    else:
        params = inspect.signature(adapter_class).parameters
        if company_id is not None and "company_id" in params:
            adapter = adapter_class(company_id=company_id)
        else:
            adapter = adapter_class()

    if adapter.is_available():
        _ACTIVE_ADAPTERS[cache_key] = adapter
        return adapter

    return adapter


def get_all_platform_names() -> list[str]:
    return list(PLATFORM_ADAPTERS.keys())


def clear_adapter_cache():
    _ACTIVE_ADAPTERS.clear()

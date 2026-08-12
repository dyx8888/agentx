"""
Platforms metadata API (T4.4)
提供平台清单、凭证字段定义、授权教程，供前端动态渲染平台授权中心。
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.logging import get_logger
from app.platforms import PLATFORM_ADAPTERS
from app.platforms.credentials import CREDENTIAL_FIELD_MAP, get_oauth_managed_fields

logger = get_logger(__name__)

router = APIRouter()


# ─── 静态元数据：平台展示信息（名称 / 图标 / 描述） ──────────────────────────────
# 统一维护所有平台的展示元数据，供前端卡片渲染。
# code 与 CREDENTIAL_FIELD_MAP / PLATFORM_ADAPTERS 的 key 对齐。
PLATFORM_METADATA: dict[str, dict] = {
    "douyin_star": {
        "name_display": "抖音星图",
        "icon": "star",
        "description": "抖音官方创作者数据平台，达人搜索与星图数据",
    },
    "douyin_shop": {
        "name_display": "抖音小店",
        "icon": "shop",
        "description": "抖音电商店铺管理，商品、订单与售后",
    },
    "douyin_luopan": {
        "name_display": "抖音电商罗盘",
        "icon": "compass",
        "description": "抖音电商数据罗盘，店铺经营分析",
    },
    "taobao": {
        "name_display": "淘宝",
        "icon": "taobao",
        "description": "淘宝开放平台，商品、交易与店铺管理",
    },
    "chanmama": {
        "name_display": "蝉妈妈",
        "icon": "chanmama",
        "description": "抖音电商数据分析，达人带货与商品监控",
    },
    "xiaohongshu": {
        "name_display": "小红书",
        "icon": "xiaohongshu",
        "description": "小红书开放平台，笔记与达人营销",
    },
    "shengyi_canshu": {
        "name_display": "生意参谋",
        "icon": "shengyi_canshu",
        "description": "淘宝生意参谋，店铺经营数据分析",
    },
    "pinduoduo_open": {
        "name_display": "拼多多",
        "icon": "pinduoduo",
        "description": "拼多多开放平台，商品与订单管理",
    },
    "qianchuan": {
        "name_display": "千川",
        "icon": "qianchuan",
        "description": "巨量千川广告投放平台，直播与短视频带货",
    },
    "ocean_engine": {
        "name_display": "巨量引擎",
        "icon": "ocean_engine",
        "description": "巨量引擎广告投放，广告主数据与投放管理",
    },
    "wanxiangtai": {
        "name_display": "万象台",
        "icon": "wanxiangtai",
        "description": "阿里万相台无界版，多渠道推广投放",
    },
}


# ─── 凭证字段的中文标签与帮助文案 ──────────────────────────────────────────────
# 前端根据此映射渲染表单 label / placeholder / help_text。
FIELD_LABELS: dict[str, dict] = {
    "app_id": {"label_zh": "应用 ID", "help_text": "开放平台应用的唯一标识"},
    "app_secret": {"label_zh": "应用密钥", "help_text": "应用的 Secret，敏感信息"},
    "app_key": {"label_zh": "应用 Key", "help_text": "开放平台应用的 App Key"},
    "access_token": {"label_zh": "访问令牌", "help_text": "OAuth 授权后的 Access Token"},
    "advertiser_id": {"label_zh": "广告主 ID", "help_text": "广告主账户的唯一标识"},
    "shop_id": {"label_zh": "店铺 ID", "help_text": "店铺的唯一标识"},
    "session_key": {"label_zh": "会话密钥", "help_text": "淘宝 SessionKey，授权后获得"},
    "seller_id": {"label_zh": "卖家 ID", "help_text": "卖家账号的唯一标识"},
    "api_key": {"label_zh": "API Key", "help_text": "第三方数据平台的 API Key"},
    "api_secret": {"label_zh": "API Secret", "help_text": "第三方数据平台的 API Secret"},
    "pdd_client_id": {"label_zh": "Client ID", "help_text": "拼多多开放平台的 Client ID"},
    "pdd_client_secret": {
        "label_zh": "Client Secret",
        "help_text": "拼多多开放平台的 Client Secret",
    },
    "pdd_access_token": {"label_zh": "访问令牌", "help_text": "拼多多 OAuth 授权后的 Access Token"},
    "mall_id": {"label_zh": "店铺 ID", "help_text": "拼多多店铺的唯一标识"},
    "secret": {"label_zh": "密钥", "help_text": "应用的 Secret，敏感信息"},
    "refresh_token": {"label_zh": "刷新令牌", "help_text": "OAuth 授权后自动写入"},
    "expires_at": {"label_zh": "过期时间", "help_text": "OAuth 授权后自动写入"},
}


# ─── 授权教程（每个平台一份静态指南） ──────────────────────────────────────────
PLATFORM_GUIDES: dict[str, dict] = {
    "douyin_star": {
        "title": "抖音星图授权教程",
        "steps": [
            {
                "step_num": 1,
                "action": "登录抖音开放平台",
                "note": "访问 https://open.douyin.com，使用企业账号登录",
            },
            {
                "step_num": 2,
                "action": "创建应用",
                "note": "在「应用管理」中创建新应用，获取 App ID 和 App Secret",
            },
            {
                "step_num": 3,
                "action": "配置权限",
                "note": "申请星图相关权限：达人数据查询、任务管理等",
            },
            {
                "step_num": 4,
                "action": "获取 Access Token",
                "note": "通过 OAuth 授权流程获取 Access Token",
            },
            {
                "step_num": 5,
                "action": "获取广告主 ID",
                "note": "在星图后台「账户设置」中查看广告主 ID",
            },
            {
                "step_num": 6,
                "action": "填写凭证",
                "note": "将以上信息填入左侧表单，点击「测试连接」验证",
            },
        ],
    },
    "douyin_shop": {
        "title": "抖音小店授权教程",
        "steps": [
            {"step_num": 1, "action": "登录抖店开放平台", "note": "访问 https://op.jinritemai.com"},
            {"step_num": 2, "action": "创建应用", "note": "获取 App Key 和 App Secret"},
            {"step_num": 3, "action": "配置回调地址", "note": "设置 OAuth 回调 URL"},
            {"step_num": 4, "action": "获取店铺 ID", "note": "在「店铺管理」中查看 Shop ID"},
            {"step_num": 5, "action": "获取 Access Token", "note": "通过 OAuth 授权获取"},
            {"step_num": 6, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
    "douyin_luopan": {
        "title": "抖音电商罗盘授权教程",
        "steps": [
            {"step_num": 1, "action": "登录抖店后台", "note": "罗盘数据通过抖店开放平台获取"},
            {"step_num": 2, "action": "创建应用并申请权限", "note": "申请「电商罗盘」相关数据权限"},
            {"step_num": 3, "action": "获取凭证", "note": "复用抖音小店的 App Key / App Secret"},
        ],
    },
    "taobao": {
        "title": "淘宝开放平台授权教程",
        "steps": [
            {"step_num": 1, "action": "登录淘宝开放平台", "note": "访问 https://open.taobao.com"},
            {"step_num": 2, "action": "创建应用", "note": "获取 App Key 和 App Secret"},
            {"step_num": 3, "action": "配置权限", "note": "申请商品、交易、店铺等 API 权限"},
            {
                "step_num": 4,
                "action": "获取 SessionKey",
                "note": "通过 OAuth 授权流程获取 SessionKey",
            },
            {"step_num": 5, "action": "获取卖家 ID", "note": "在「卖家中心」查看 Seller ID"},
            {"step_num": 6, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
    "chanmama": {
        "title": "蝉妈妈授权教程",
        "steps": [
            {
                "step_num": 1,
                "action": "登录蝉妈妈开放平台",
                "note": "访问 https://www.chanmama.com/open-api",
            },
            {
                "step_num": 2,
                "action": "申请 API 权限",
                "note": "联系商务获取 API Key 和 API Secret",
            },
            {"step_num": 3, "action": "填写凭证", "note": "将 API Key / API Secret 填入表单"},
        ],
    },
    "xiaohongshu": {
        "title": "小红书开放平台授权教程",
        "steps": [
            {
                "step_num": 1,
                "action": "登录小红书开放平台",
                "note": "访问 https://open.xiaohongshu.com",
            },
            {"step_num": 2, "action": "创建应用", "note": "获取 App ID 和 App Secret"},
            {"step_num": 3, "action": "配置权限", "note": "申请笔记、达人、广告等 API 权限"},
            {"step_num": 4, "action": "获取 Access Token", "note": "通过 OAuth 授权流程获取"},
            {"step_num": 5, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
    "shengyi_canshu": {
        "title": "生意参谋授权教程",
        "steps": [
            {
                "step_num": 1,
                "action": "登录淘宝开放平台",
                "note": "生意参谋数据通过淘宝开放平台获取",
            },
            {"step_num": 2, "action": "创建应用", "note": "获取 App Key 和 App Secret"},
            {
                "step_num": 3,
                "action": "申请生意参谋权限",
                "note": "在应用管理中申请「生意参谋」数据权限",
            },
            {"step_num": 4, "action": "获取 SessionKey", "note": "通过 OAuth 授权获取"},
            {"step_num": 5, "action": "获取卖家 ID", "note": "在「卖家中心」查看 Seller ID"},
            {"step_num": 6, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
    "pinduoduo_open": {
        "title": "拼多多开放平台授权教程",
        "steps": [
            {
                "step_num": 1,
                "action": "登录拼多多开放平台",
                "note": "访问 https://open.pinduoduo.com",
            },
            {"step_num": 2, "action": "创建应用", "note": "获取 Client ID 和 Client Secret"},
            {"step_num": 3, "action": "配置权限", "note": "申请商品、订单、物流等 API 权限"},
            {"step_num": 4, "action": "获取 Access Token", "note": "通过 OAuth 授权流程获取"},
            {"step_num": 5, "action": "获取店铺 ID", "note": "在「店铺管理」中查看 Mall ID"},
            {"step_num": 6, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
    "qianchuan": {
        "title": "巨量千川授权教程",
        "steps": [
            {
                "step_num": 1,
                "action": "登录巨量千川",
                "note": "访问 https://qianchuan.jinritemai.com",
            },
            {"step_num": 2, "action": "创建应用", "note": "在开放平台获取 App ID 和 Secret"},
            {
                "step_num": 3,
                "action": "获取广告主 ID",
                "note": "在千川后台「账户设置」查看广告主 ID",
            },
            {"step_num": 4, "action": "获取 Access Token", "note": "通过 OAuth 授权流程获取"},
            {"step_num": 5, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
    "ocean_engine": {
        "title": "巨量引擎授权教程",
        "steps": [
            {
                "step_num": 1,
                "action": "登录巨量引擎开放平台",
                "note": "访问 https://open.oceanengine.com",
            },
            {"step_num": 2, "action": "创建应用", "note": "获取 App ID 和 App Secret"},
            {"step_num": 3, "action": "获取广告主 ID", "note": "在「账户管理」中查看广告主 ID"},
            {"step_num": 4, "action": "获取 Access Token", "note": "通过 OAuth 授权流程获取"},
            {"step_num": 5, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
    "wanxiangtai": {
        "title": "万相台授权教程",
        "steps": [
            {"step_num": 1, "action": "登录淘宝开放平台", "note": "万相台数据通过淘宝开放平台获取"},
            {"step_num": 2, "action": "创建应用", "note": "获取 App Key 和 App Secret"},
            {"step_num": 3, "action": "申请万相台权限", "note": "申请「万相台无界版」推广数据权限"},
            {"step_num": 4, "action": "获取 SessionKey", "note": "通过 OAuth 授权获取"},
            {"step_num": 5, "action": "填写凭证", "note": "填入表单并测试连接"},
        ],
    },
}


# ─── 响应模型 ──────────────────────────────────────────────────────────────────


class CredentialFieldItem(BaseModel):
    field_name: str
    label_zh: str
    required: bool
    help_text: str


class PlatformItem(BaseModel):
    code: str
    name_display: str
    icon: str
    description: str
    credential_fields: list[str]
    required: bool  # 是否需要用户填写凭证


class CredentialFieldsResponse(BaseModel):
    code: str
    fields: list[CredentialFieldItem]


class GuideStep(BaseModel):
    step_num: int
    action: str
    note: str


class GuideResponse(BaseModel):
    title: str
    steps: list[GuideStep]


# ─── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[PlatformItem])
async def list_platforms():
    """获取所有平台清单——从 CREDENTIAL_FIELD_MAP 和 PLATFORM_ADAPTERS 组装。
    返回每个平台的展示信息与所需凭证字段名列表。"""
    result: list[PlatformItem] = []
    seen: set[str] = set()
    # 遍历所有已注册适配器，确保未在 CREDENTIAL_FIELD_MAP 中的平台也能展示
    for code in PLATFORM_ADAPTERS:
        # 防御性去重：即便数据源出现重复注册，也保证每个 code 只返回一次
        if code in seen:
            continue
        seen.add(code)
        meta = PLATFORM_METADATA.get(code, {})
        field_map = CREDENTIAL_FIELD_MAP.get(code, {})
        result.append(
            PlatformItem(
                code=code,
                name_display=meta.get("name_display", code),
                icon=meta.get("icon", "default"),
                description=meta.get("description", ""),
                credential_fields=list(field_map.keys()),
                required=bool(field_map),  # 有凭证字段定义则 required=True
            )
        )
    return result


@router.get("/{code}/credential-fields", response_model=CredentialFieldsResponse)
async def get_credential_fields(code: str):
    """获取某平台的凭证字段定义——前端据此动态渲染表单。"""
    field_map = CREDENTIAL_FIELD_MAP.get(code)
    if not field_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform code or no credential fields defined: {code}",
        )
    fields: list[CredentialFieldItem] = []
    oauth_managed_fields = get_oauth_managed_fields(code)
    for field_name in field_map:
        label_info = FIELD_LABELS.get(field_name, {})
        fields.append(
            CredentialFieldItem(
                field_name=field_name,
                label_zh=label_info.get("label_zh", field_name),
                required=field_name not in oauth_managed_fields,
                help_text=label_info.get("help_text", ""),
            )
        )
    return CredentialFieldsResponse(code=code, fields=fields)


@router.get("/{code}/guide", response_model=GuideResponse)
async def get_platform_guide(code: str):
    """获取某平台的授权教程——返回步骤列表，供前端引导用户完成授权。"""
    if code not in PLATFORM_ADAPTERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform code: {code}",
        )
    guide = PLATFORM_GUIDES.get(code)
    if not guide:
        # 未配置教程的平台返回占位提示，不报错
        return GuideResponse(
            title=PLATFORM_METADATA.get(code, {}).get("name_display", code) + "授权教程",
            steps=[GuideStep(step_num=1, action="请联系平台商务获取授权指引", note="")],
        )
    return GuideResponse(
        title=guide["title"],
        steps=[GuideStep(**step) for step in guide["steps"]],
    )

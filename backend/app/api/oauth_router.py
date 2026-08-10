"""
电商平台 OAuth 授权全链路路由

提供两个核心端点：
1. GET /api/oauth/authorize/{platform} — 生成授权 URL + state，返回给前端控制跳转
2. GET /api/oauth/callback/{platform} — 接收平台回调的 code + state，换取 token 并存储

OAuth 流程：
  前端点击"授权" → 调 authorize 端点获取 authorize_url → 前端跳转到平台授权页 →
  用户授权后平台回调 callback 端点 → 后端用 code 换 token → 存入 PlatformToken 表 +
  同步更新 credentials JSON → 返回成功页/重定向到前端

state 安全机制：
  使用 secrets.token_urlsafe(32) 生成，存内存 dict（_OAUTH_STATE_STORE）带 10 分钟 TTL，
  绑定 company_id + platform，回调时校验 state 合法性以防 CSRF。
"""

import json
import os
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.core.logging import get_logger
from app.database import User, db
from app.platforms import PLATFORM_ADAPTERS
from app.platforms.credentials import CREDENTIAL_FIELD_MAP, OAUTH_PLATFORMS

logger = get_logger(__name__)

router = APIRouter()


class OAuthCallbackRequest(BaseModel):
    code: str | None = None
    state: str | None = None


# ─── state 存储（内存 dict + TTL，不引入新依赖） ──────────────────────────────
# 结构: {state: {"company_id": int, "platform": str, "created_at": float}}
_OAUTH_STATE_STORE: dict[str, dict] = {}
_STATE_TTL_SECONDS = 600  # 10 分钟有效期


def _create_state(company_id: int, platform: str) -> str:
    """生成 state 并绑定 company_id + platform，存入内存 dict。"""
    # 清理过期 state（惰性清理，避免内存无限增长）
    _cleanup_expired_states()
    state = secrets.token_urlsafe(32)
    _OAUTH_STATE_STORE[state] = {
        "company_id": company_id,
        "platform": platform,
        "created_at": time.time(),
    }
    logger.info("oauth_state_created", company_id=company_id, platform=platform)
    return state


def _validate_state(state: str) -> dict | None:
    """校验 state 是否存在且未过期，返回绑定的 company_id + platform。"""
    entry = _OAUTH_STATE_STORE.pop(state, None)  # 弹出后即失效（一次性使用）
    if not entry:
        return None
    elapsed = time.time() - entry["created_at"]
    if elapsed > _STATE_TTL_SECONDS:
        logger.warning("oauth_state_expired", elapsed=elapsed)
        return None
    return entry


def _cleanup_expired_states() -> None:
    """清理过期的 state 条目"""
    now = time.time()
    expired = [
        k for k, v in _OAUTH_STATE_STORE.items() if now - v["created_at"] > _STATE_TTL_SECONDS
    ]
    for k in expired:
        _OAUTH_STATE_STORE.pop(k, None)


# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _get_redirect_uri(platform: str) -> str:
    """构造 OAuth 回调地址，基于 OAUTH_REDIRECT_BASE_URL 环境变量。"""
    base_url = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base_url}/api/oauth/callback/{platform}"


def _load_credentials_json(company) -> dict:
    """从 company.platform_credentials 反序列化 JSON（EncryptedText 已自动解密）。"""
    if not company.platform_credentials:
        return {}
    try:
        data = json.loads(company.platform_credentials)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("credentials_json_parse_failed", company_id=company.id, error=str(exc))
        return {}


def _save_credentials_json(company_id: int, credentials_map: dict) -> None:
    """序列化 JSON 并写回数据库（EncryptedText 会自动加密整体 blob）。"""
    updated_json = json.dumps(credentials_map, ensure_ascii=False)
    success = db.update_company_platform_credentials(company_id, updated_json)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update platform credentials",
        )


# ─── 归一化 token → credentials JSON 字段映射 ──────────────────────────────────
# 各平台 OAuth 返回的 token 字典中，access_token 对应 credentials JSON 中的不同字段名：
# - taobao: session_key（淘宝的 access_token 即 session_key）
# - douyin_shop: access_token
# - pinduoduo_open: pdd_access_token
PLATFORM_TOKEN_TO_CRED_FIELD: dict[str, dict[str, str]] = {
    "taobao": {
        "access_token_key": "session_key",  # credentials JSON 中 access_token 对应的字段名
        "extra_fields": {"seller_id": "taobao_user_id"},  # 额外映射: credentials_field → token_key
    },
    "douyin_shop": {
        "access_token_key": "access_token",
        "extra_fields": {},
    },
    "pinduoduo_open": {
        "access_token_key": "pdd_access_token",
        "extra_fields": {},
    },
    "xiaohongshu": {
        "access_token_key": "access_token",
        "extra_fields": {},
    },
}


def _store_token_to_db(company_id: int, platform: str, token_data: dict) -> None:
    """将 token 存入 PlatformToken 表（upsert）+ 同步更新 credentials JSON。

    token_data 格式（归一化后）:
        {
            "access_token": "...",
            "refresh_token": "...",
            "expires_at": "2026-07-01T12:00:00+00:00",
            "refresh_expires_at": "2026-07-31T12:00:00+00:00",
            ...
        }
    """
    from app.database.models import PlatformToken

    # 解析 expires_at 字符串为 datetime
    expires_at = _parse_iso_datetime(token_data.get("expires_at"))
    refresh_expires_at = _parse_iso_datetime(token_data.get("refresh_expires_at"))

    # 1. upsert PlatformToken 表
    try:
        with db.get_session() as session:
            existing = (
                session.query(PlatformToken)
                .filter(
                    PlatformToken.company_id == company_id,
                    PlatformToken.platform == platform,
                )
                .first()
            )

            if existing:
                existing.access_token = token_data.get("access_token", "")
                existing.refresh_token = token_data.get("refresh_token", "")
                existing.expires_at = expires_at
                existing.refresh_expires_at = refresh_expires_at
                existing.updated_at = datetime.utcnow()
            else:
                record = PlatformToken(
                    company_id=company_id,
                    platform=platform,
                    access_token=token_data.get("access_token", ""),
                    refresh_token=token_data.get("refresh_token", ""),
                    expires_at=expires_at,
                    refresh_expires_at=refresh_expires_at,
                    updated_at=datetime.utcnow(),
                )
                session.add(record)
            session.commit()
            logger.info("platform_token_stored", company_id=company_id, platform=platform)
    except Exception as exc:
        logger.error(
            "platform_token_store_failed", company_id=company_id, platform=platform, error=str(exc)
        )
        raise

    # 2. 同步更新 credentials JSON（让现有适配器能读到新 token）
    company = db.get_company(company_id)
    if not company:
        logger.warning("company_not_found_for_token_sync", company_id=company_id)
        return

    creds_map = _load_credentials_json(company)
    platform_entry = creds_map.get(platform)
    if not isinstance(platform_entry, dict):
        # 平台凭证尚未配置（用户未手动填写 app_key 等），仅存 token 不合并
        logger.warning(
            "credentials_not_configured_skip_sync", company_id=company_id, platform=platform
        )
        return

    platform_creds = platform_entry.setdefault("credentials", {})
    field_mapping = PLATFORM_TOKEN_TO_CRED_FIELD.get(platform, {})
    access_token_key = field_mapping.get("access_token_key", "access_token")

    # 写入 access_token（映射到对应字段名）
    if token_data.get("access_token"):
        platform_creds[access_token_key] = token_data["access_token"]
    # 写入 refresh_token
    if token_data.get("refresh_token"):
        platform_creds["refresh_token"] = token_data["refresh_token"]
    # 写入 expires_at
    if token_data.get("expires_at"):
        platform_creds["expires_at"] = token_data["expires_at"]
    # 写入额外字段（如淘宝的 seller_id ← taobao_user_id）
    for cred_field, token_key in field_mapping.get("extra_fields", {}).items():
        if token_data.get(token_key):
            platform_creds[cred_field] = token_data[token_key]

    # 更新 _meta
    meta = platform_entry.setdefault("_meta", {})
    meta["last_verified"] = datetime.utcnow().isoformat() + "Z"
    meta["last_verify_valid"] = True
    meta["oauth_authorized_at"] = datetime.utcnow().isoformat() + "Z"

    _save_credentials_json(company_id, creds_map)
    logger.info("credentials_synced_with_token", company_id=company_id, platform=platform)


def _parse_iso_datetime(dt_str: str | None) -> datetime | None:
    """解析 ISO 8601 时间字符串为 datetime 对象。"""
    if not dt_str:
        return None
    try:
        # 兼容带时区和不带时区的 ISO 格式
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        logger.warning("parse_datetime_failed", dt_str=dt_str, error=str(exc))
        return None


def _build_adapter_from_credentials(company_id: int, platform: str):
    """从公司凭证存储加载凭证并实例化适配器。

    Returns:
        实例化后的适配器对象
    Raises:
        HTTPException: 平台不支持 OAuth 或凭证缺失
    """

    company = db.get_company(company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    creds_map = _load_credentials_json(company)
    platform_entry = creds_map.get(platform)
    if not isinstance(platform_entry, dict) or not platform_entry.get("credentials"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"请先在凭证设置中配置 {platform} 的 app_key/app_secret，再发起 OAuth 授权",
        )

    # credentials JSON 中的值已经是明文（EncryptedText 在读取时已解密整体 JSON），
    # 但 credentials 子字典中的各字段值是明文字符串，直接传给 build_adapter_kwargs
    raw_creds = platform_entry["credentials"]
    # build_adapter_kwargs 期望 {field_name: encrypted_value} 格式并尝试解密，
    # 但这里的值已经是明文（因为整体 JSON 已被 EncryptedText 解密）。
    # 直接构建 kwargs，跳过 build_adapter_kwargs 的解密逻辑。
    field_map = CREDENTIAL_FIELD_MAP.get(platform, {})
    kwargs = {}
    for db_field, adapter_param in field_map.items():
        value = raw_creds.get(db_field)
        if value:
            kwargs[adapter_param] = value

    adapter_class = PLATFORM_ADAPTERS.get(platform)
    if not adapter_class:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform: {platform}",
        )

    return adapter_class(**kwargs)


# ─── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("/authorize/{platform}")
async def authorize(
    platform: str,
    current_user: User = Depends(get_current_active_user),
):
    """生成 OAuth 授权 URL。

    流程：
    1. 校验平台支持 OAuth
    2. 从当前登录用户获取 company_id
    3. 生成 state 并绑定 company_id + platform（存内存 dict，10 分钟 TTL）
    4. 从凭证存储加载 app_key，实例化适配器
    5. 调适配器 get_authorize_url 构造授权页 URL
    6. 返回 {"authorize_url": "...", "state": "..."}，前端用 window.location 跳转

    不直接 302 重定向，让前端控制跳转时机和方式。
    """
    if platform not in OAUTH_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"平台 {platform} 不支持 OAuth 授权，支持的平台: {sorted(OAUTH_PLATFORMS)}",
        )

    if current_user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前用户未关联公司，无法发起 OAuth 授权",
        )

    company_id = current_user.company_id

    # 生成 state 并绑定 company_id + platform
    state = _create_state(company_id, platform)

    # 实例化适配器（需要 app_key 来构造授权 URL）
    adapter = _build_adapter_from_credentials(company_id, platform)

    redirect_uri = _get_redirect_uri(platform)

    try:
        authorize_url = await adapter.get_authorize_url(redirect_uri, state)
    except RuntimeError as exc:
        logger.error("oauth_authorize_url_failed", platform=platform, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"构造授权 URL 失败: {exc}",
        )

    logger.info(
        "oauth_authorize_ready", company_id=company_id, platform=platform, redirect_uri=redirect_uri
    )

    return {
        "authorize_url": authorize_url,
        "state": state,
        "platform": platform,
        "redirect_uri": redirect_uri,
    }


@router.get("/callback/{platform}")
async def oauth_callback(
    platform: str,
    code: str | None = Query(None, description="OAuth authorization code"),
    state: str | None = Query(None, description="OAuth state"),
):
    """OAuth 回调端点 — 接收平台回调的 code + state，换取 token 并存储。

    流程：
    1. 校验 state（从内存 dict弹出，一次性使用）
    2. 从 state 获取绑定的 company_id
    3. 实例化适配器（加载 app_key/app_secret）
    4. 调 exchange_authorization_code(code, redirect_uri) 换取 token
    5. 存入 PlatformToken 表 + 同步更新 credentials JSON
    6. 返回 HTML 成功页（自动跳转到前端 /settings?oauth=success）

    注意：此端点不需要 JWT 鉴权（平台回调时不会携带 Authorization 头），
    安全性由 state 校验保证。
    """
    if not isinstance(code, str) or not code.strip() or not isinstance(state, str) or not state.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth callback requires code and state",
        )

    if platform not in OAUTH_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"平台 {platform} 不支持 OAuth 授权",
        )

    # 1. 校验 state
    state_data = _validate_state(state)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state 无效或已过期，请重新发起授权",
        )

    # 校验 state 中的 platform 与 URL 中的 platform 一致
    if state_data["platform"] != platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state 中的平台信息与回调路径不匹配",
        )

    company_id = state_data["company_id"]

    # 2. 实例化适配器
    adapter = _build_adapter_from_credentials(company_id, platform)

    redirect_uri = _get_redirect_uri(platform)

    # 3. 换取 token
    try:
        token_data = await adapter.exchange_authorization_code(code, redirect_uri)
    except RuntimeError as exc:
        logger.error(
            "oauth_exchange_failed", company_id=company_id, platform=platform, error=str(exc)
        )
        # 返回 HTML 错误页而非 JSON，因为这是浏览器跳转
        return HTMLResponse(
            content=_error_html(str(exc)),
            status_code=status.HTTP_200_OK,  # 返回 200 让浏览器正常渲染错误页
        )

    # 4. 存储 token
    try:
        _store_token_to_db(company_id, platform, token_data)
    except Exception as exc:
        logger.error(
            "oauth_store_token_failed", company_id=company_id, platform=platform, error=str(exc)
        )
        return HTMLResponse(
            content=_error_html(f"Token 存储失败: {exc}"),
            status_code=status.HTTP_200_OK,
        )

    logger.info("oauth_callback_success", company_id=company_id, platform=platform)

    # 5. 返回成功页（自动跳转到前端）
    frontend_url = os.getenv(
        "OAUTH_FRONTEND_REDIRECT_URL",
        "http://localhost:3000/settings?oauth=success",
    )
    return HTMLResponse(content=_success_html(platform, frontend_url))


@router.post("/callback/{platform}")
async def oauth_callback_post(platform: str, payload: OAuthCallbackRequest):
    """JSON callback endpoint used by the frontend OAuth callback page."""
    if not isinstance(payload.code, str) or not payload.code.strip() or not isinstance(payload.state, str) or not payload.state.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth callback requires code and state",
        )

    if platform not in OAUTH_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"平台 {platform} 不支持 OAuth 授权",
        )

    state_data = _validate_state(payload.state)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state 无效或已过期，请重新发起授权",
        )
    if state_data["platform"] != platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state 中的平台信息与回调路径不匹配",
        )

    company_id = state_data["company_id"]
    adapter = _build_adapter_from_credentials(company_id, platform)
    redirect_uri = _get_redirect_uri(platform)

    try:
        token_data = await adapter.exchange_authorization_code(payload.code, redirect_uri)
    except RuntimeError as exc:
        logger.error(
            "oauth_exchange_failed", company_id=company_id, platform=platform, error=str(exc)
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        _store_token_to_db(company_id, platform, token_data)
    except Exception as exc:
        logger.error(
            "oauth_store_token_failed", company_id=company_id, platform=platform, error=str(exc)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token storage failed: {exc}",
        )

    logger.info("oauth_callback_success", company_id=company_id, platform=platform)
    return {"message": "OAuth authorization completed", "platform": platform, "bound": True}


# ─── HTML 响应模板 ─────────────────────────────────────────────────────────────


def _success_html(platform: str, redirect_url: str) -> str:
    """OAuth 授权成功后的 HTML 页面，自动跳转到前端。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>授权成功</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               display: flex; justify-content: center; align-items: center;
               min-height: 100vh; margin: 0; background: #f5f5f5; }}
        .card {{ background: #fff; padding: 40px; border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1); text-align: center; max-width: 400px; }}
        .icon {{ font-size: 48px; color: #4caf50; margin-bottom: 16px; }}
        h1 {{ color: #333; font-size: 20px; margin: 0 0 8px; }}
        p {{ color: #666; font-size: 14px; margin: 0 0 20px; }}
        .redirect {{ color: #1976d2; font-size: 13px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#10004;</div>
        <h1>授权成功</h1>
        <p>{platform} 平台授权已完成，即将跳转到设置页面...</p>
        <p class="redirect">如未自动跳转，请<a href="{redirect_url}">点击这里</a></p>
    </div>
    <script>
        setTimeout(function() {{ window.location.href = '{redirect_url}'; }}, 2000);
    </script>
</body>
</html>"""


def _error_html(error_msg: str) -> str:
    """OAuth 授权失败时的 HTML 页面。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>授权失败</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               display: flex; justify-content: center; align-items: center;
               min-height: 100vh; margin: 0; background: #f5f5f5; }}
        .card {{ background: #fff; padding: 40px; border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1); text-align: center; max-width: 400px; }}
        .icon {{ font-size: 48px; color: #f44336; margin-bottom: 16px; }}
        h1 {{ color: #333; font-size: 20px; margin: 0 0 8px; }}
        p {{ color: #666; font-size: 14px; margin: 0 0 20px; word-break: break-word; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">&#10006;</div>
        <h1>授权失败</h1>
        <p>{error_msg}</p>
        <p>请检查凭证配置后重试，或联系管理员</p>
    </div>
</body>
</html>"""

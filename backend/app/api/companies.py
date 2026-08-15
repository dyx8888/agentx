"""
Companies router for AgentX Stage 4
Manages tenant (company) operations
"""

import inspect
import ipaddress
import json
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import get_current_active_user
from app.core.logging import get_logger
from app.core.permissions import admin_required  # 仅管理员可以创建公司，确保租户管理安全
from app.database import Company, User, db
from app.platforms import PLATFORM_ADAPTERS
from app.platforms.credentials import CREDENTIAL_FIELD_MAP, get_oauth_managed_fields

logger = get_logger(__name__)

router = APIRouter()

PLATFORM_API_PAUSED_DETAIL = {
    "code": "platform_api_paused",
    "message": "平台 API 暂停，数据获取将通过浏览器连接器",
}


def _raise_platform_api_paused() -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=PLATFORM_API_PAUSED_DETAIL,
    )


# Pydantic models
class CompanyCreate(BaseModel):
    name: str
    brand_name: str
    category: str
    platforms: str  # Comma-separated string  # 前端以逗号分隔字符串传入，后端存储为 JSON


class CompanyResponse(BaseModel):
    id: int
    name: str
    brand_name: str
    category: str
    platforms_json: str  # 数据库中以 JSON 字符串存储，响应中保持原样
    created_at: str | None = None


def _read_company_attr(company, field: str, default=None):
    if isinstance(company, dict):
        return company.get(field, default)
    return getattr(company, field, default)


def _format_created_at(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _company_to_response(company) -> CompanyResponse:
    return CompanyResponse(
        id=_read_company_attr(company, "id"),
        name=_read_company_attr(company, "name", ""),
        brand_name=_read_company_attr(company, "brand_name", ""),
        category=_read_company_attr(company, "category", ""),
        platforms_json=_read_company_attr(company, "platforms_json", "") or "",
        created_at=_format_created_at(_read_company_attr(company, "created_at")),
    )


@router.post("/", response_model=CompanyResponse)
async def create_company(
    company_data: CompanyCreate,
    current_user: User = Depends(admin_required),  # 管理员权限：普通用户不能创建公司
):
    """Create a new company (admin only)"""
    # Convert platforms to JSON string for storage
    platforms_json = company_data.platforms  # 前端传入的逗号分隔字符串直接存储

    new_company = Company(
        name=company_data.name,
        brand_name=company_data.brand_name,
        category=company_data.category,
        platforms_json=platforms_json,
    )

    company_id = db.create_company(new_company)
    created_company = db.get_company(company_id)  # 创建后重新查询获取完整数据

    if not created_company:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create company"
        )

    return _company_to_response(created_company)


@router.get("/{company_id:int}", response_model=CompanyResponse)
async def get_company_info(company_id: int, current_user: User = Depends(get_current_active_user)):
    """Get company information by ID"""
    if (
        not current_user.is_admin and current_user.company_id != company_id
    ):  # 非管理员只能查看自己公司的信息
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot view other company's information",
        )

    try:
        company = db.get_company(company_id)
    except Exception as exc:
        logger.warning("get_company_info_unavailable", company_id=company_id, error=str(exc))
        company = None

    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    return _company_to_response(company)


@router.get("/", response_model=list[CompanyResponse])
async def get_companies(current_user: User = Depends(get_current_active_user)):
    """Get companies accessible to current user"""
    try:
        if current_user.is_admin:
            company_list = db.get_all_companies()  # 管理员可以看到所有公司
        elif current_user.company_id:
            company = db.get_company(current_user.company_id)
            company_list = [company] if company else []  # 普通用户只能看到自己的公司
        else:
            company_list = []  # 无公司归属的用户看不到任何公司
    except Exception as exc:
        logger.warning(
            "list_companies_unavailable",
            user_id=getattr(current_user, "id", None),
            company_id=getattr(current_user, "company_id", None),
            error=str(exc),
        )
        company_list = []

    return [_company_to_response(c) for c in company_list]


@router.put("/{company_id:int}", response_model=CompanyResponse)
async def update_company(
    company_id: int,
    company_data: CompanyCreate,
    current_user: User = Depends(get_current_active_user),
):
    """Update company information"""
    if (
        not current_user.is_admin and current_user.company_id != company_id
    ):  # 权限校验：管理员或同公司用户
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot update other company's information",
        )

    existing_company = db.get_company(company_id)

    if not existing_company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    # Update company
    updated_company = Company(
        id=company_id,
        name=company_data.name,
        brand_name=company_data.brand_name,
        category=company_data.category,
        platforms_json=company_data.platforms,  # 直接使用前端传入的字符串
    )

    success = db.update_company(company_id, updated_company)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update company"
        )

    # Return updated company
    updated_record = db.get_company(company_id)  # 更新后重新查询

    return _company_to_response(updated_record)


# ─── 平台凭证管理（T4.1 升级：动态字段 + masked 返回 + verify 端点） ──────────


# Pydantic models for credentials
class PlatformCredentials(BaseModel):
    """平台凭证请求体——字段集合按平台动态变化，由 CREDENTIAL_FIELD_MAP 定义"""

    platform: str = Field(..., description="平台代码，如 douyin_star / xiaohongshu")
    credentials: dict[str, str] = Field(
        ...,
        description='动态字段，如 {"app_id":"...","app_secret":"...","access_token":"..."}',
    )


class BoundPlatformItem(BaseModel):
    """已绑定平台的 masked 视图——不返回任何敏感值"""

    platform: str
    bound: bool
    last_verified: str | None = None
    last_verify_valid: bool | None = None


class VerifyResult(BaseModel):
    valid: bool
    message: str


def _load_credentials_json(company: Company) -> dict:
    """从 company.platform_credentials 反序列化 JSON。
    EncryptedText 类型在 ORM 读取时已自动解密，此处只需 json.loads。"""
    if not company.platform_credentials:
        return {}
    try:
        data = json.loads(company.platform_credentials)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("credentials_json_parse_failed", company_id=company.id, error=str(exc))
        return {}


def _save_credentials_json(company_id: int, credentials_map: dict) -> None:
    """序列化 JSON 并写回数据库（EncryptedText 会自动加密整体 blob）"""
    updated_json = json.dumps(credentials_map, ensure_ascii=False)
    success = db.update_company_platform_credentials(company_id, updated_json)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update platform credentials",
        )


def _check_company_access(current_user: User, company_id: int) -> Company:
    """公共前置：公司存在性 + 当前用户对该公司的访问权限"""
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found",
        )
    if not current_user.is_admin and current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage this company's credentials",
        )
    return company


def _validate_platform_and_fields(platform: str, credentials: dict[str, str]) -> None:
    """校验平台代码合法 + 动态字段包含所有必填字段"""
    field_map = CREDENTIAL_FIELD_MAP.get(platform)
    if not field_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform code: {platform}",
        )
    oauth_managed_fields = get_oauth_managed_fields(platform)
    required_fields = [field for field in field_map if field not in oauth_managed_fields]
    missing = [f for f in required_fields if not credentials.get(f)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required credential fields for {platform}: {missing}",
        )


@router.post("/{company_id:int}/credentials")
async def bind_platform_credentials(
    company_id: int,
    credentials: PlatformCredentials,
    current_user: User = Depends(get_current_active_user),
):
    """为公司绑定/更新平台凭证（动态字段，按平台独立 key 合并存储）"""
    company = _check_company_access(current_user, company_id)
    _validate_platform_and_fields(credentials.platform, credentials.credentials)

    try:
        existing = _load_credentials_json(company)

        # 合并入该平台的独立 key；保留已有的 _meta（last_verified 等）若存在
        previous_meta = {}
        if isinstance(existing.get(credentials.platform), dict):
            previous_meta = existing[credentials.platform].get("_meta", {}) or {}

        existing[credentials.platform] = {
            "credentials": dict(
                credentials.credentials
            ),  # 仅存值，字段名由 CREDENTIAL_FIELD_MAP 约束
            "_meta": previous_meta,
        }

        _save_credentials_json(company_id, existing)

        logger.info(
            "platform_credentials_bound",
            company_id=company_id,
            platform=credentials.platform,
        )
        return {"message": f"Platform credentials for {credentials.platform} updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("bind_credentials_failed", company_id=company_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="内部服务器错误",
        )


@router.delete("/{company_id:int}/credentials")
async def unbind_platform_credentials(
    company_id: int,
    platform: str,  # 通过查询参数指定要解绑的平台
    current_user: User = Depends(get_current_active_user),
):
    """解绑公司指定平台的凭证（幂等：平台不存在也返回成功）"""
    company = _check_company_access(current_user, company_id)

    # 校验平台代码合法（即便没绑定也要明确告知前端代码错误）
    if platform not in CREDENTIAL_FIELD_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform code: {platform}",
        )

    try:
        existing = _load_credentials_json(company)

        if platform in existing:
            del existing[platform]
            _save_credentials_json(company_id, existing)
            logger.info("platform_credentials_unbound", company_id=company_id, platform=platform)
            return {"message": f"Platform credentials for {platform} removed successfully"}
        else:
            return {"message": f"No credentials found for platform {platform}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("unbind_credentials_failed", company_id=company_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="内部服务器错误",
        )


@router.get("/{company_id:int}/credentials", response_model=list[BoundPlatformItem])
async def list_bound_platforms(
    company_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """返回已绑定平台的 masked 列表——只返回平台名与状态，不返回任何敏感值"""
    company = _check_company_access(current_user, company_id)

    try:
        existing = _load_credentials_json(company)
        result: list[BoundPlatformItem] = []

        # 遍历 CREDENTIAL_FIELD_MAP 中所有支持的平台，统一返回（含未绑定）
        for platform_code in CREDENTIAL_FIELD_MAP:
            entry = existing.get(platform_code)
            if isinstance(entry, dict) and entry.get("credentials"):
                meta = entry.get("_meta") or {}
                result.append(
                    BoundPlatformItem(
                        platform=platform_code,
                        bound=True,
                        last_verified=meta.get("last_verified"),
                        last_verify_valid=meta.get("last_verify_valid"),
                    )
                )
            else:
                result.append(BoundPlatformItem(platform=platform_code, bound=False))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("list_credentials_failed", company_id=company_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="内部服务器错误",
        )


@router.post(
    "/{company_id:int}/credentials/{platform}/verify",
    response_model=VerifyResult,
)
async def verify_platform_credentials(
    company_id: int,
    platform: str,
    current_user: User = Depends(get_current_active_user),
):
    """验证指定平台凭证的有效性。
    流程：读取已存凭证 → 尝试实例化适配器 → 调用 authenticate()（若适配器已实现），
    否则退化为字段完整性校验。验证结果回写 _meta.last_verified。
    """
    _raise_platform_api_paused()

    company = _check_company_access(current_user, company_id)

    if platform not in CREDENTIAL_FIELD_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown platform code: {platform}",
        )

    try:
        existing = _load_credentials_json(company)
        entry = existing.get(platform)
        if not isinstance(entry, dict) or not entry.get("credentials"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No credentials bound for platform {platform}",
            )

        creds: dict[str, str] = entry["credentials"]
        field_map = CREDENTIAL_FIELD_MAP[platform]
        # 字段完整性校验（即便已绑定也可能字段不完整）
        # 跳过 OAuth 自动获取字段（refresh_token / expires_at 由授权流程自动写入）
        oauth_managed_fields = get_oauth_managed_fields(platform)
        missing = [f for f in field_map if f not in oauth_managed_fields and not creds.get(f)]
        if missing:
            return VerifyResult(
                valid=False,
                message=f"Missing required fields: {missing}",
            )

        # 尝试创建适配器并调用 authenticate()。字段完整不能代表真实连通。
        valid = False
        message = "Credential fields complete, but no adapter is registered for live verification"
        adapter_class = PLATFORM_ADAPTERS.get(platform)
        if adapter_class is not None:
            try:
                params = inspect.signature(adapter_class).parameters
                adapter_kwargs = {k: v for k, v in creds.items() if k in params}
                if "company_id" in params:
                    adapter_kwargs["company_id"] = company_id
                adapter = adapter_class(**adapter_kwargs)
                authenticate_fn = getattr(adapter, "authenticate", None)
                if callable(authenticate_fn):
                    result = authenticate_fn()
                    if inspect.isawaitable(result):
                        result = await result
                    # authenticate() 可能返回 bool 或 (bool, str)
                    if isinstance(result, tuple) and len(result) >= 2:
                        valid, message = bool(result[0]), str(result[1])
                    else:
                        valid, message = (
                            bool(result),
                            "authenticate() succeeded" if valid else "authenticate() failed",
                        )
                else:
                    message = "Adapter does not implement authenticate(); live verification unavailable"
            except Exception as exc:
                valid = False
                message = f"Adapter instantiation failed: {exc}"
                logger.warning("verify_adapter_init_failed", platform=platform, error=str(exc))

        # 回写验证元数据
        meta = entry.setdefault("_meta", {})
        meta["last_verified"] = datetime.utcnow().isoformat() + "Z"
        meta["last_verify_valid"] = valid
        _save_credentials_json(company_id, existing)

        logger.info(
            "platform_credentials_verified",
            company_id=company_id,
            platform=platform,
            valid=valid,
        )
        return VerifyResult(valid=valid, message=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "verify_credentials_failed", company_id=company_id, platform=platform, error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="内部服务器错误",
        )


# ─── LLM 配置管理（T4.11：多厂商 LLM 配置持久化） ──────────────────────────
# 复用 Company.llm_api_key (EncryptedText) 字段存储多厂商配置 JSON，
# 与 platform_credentials 同样享受 EncryptedText 透明加解密保护。
# 存储结构: { "<provider_key>": { providerType, baseUrl, gateway, modelName, apiKey, enabled, preferredTasks, tpm, usage, warnAt90 }, ... }
# GET 返回 apiKey 的脱敏版（apiKeyMasked），PUT 时 apiKey 为空表示保留原值。


class LlmProviderConfigResponse(BaseModel):
    """单个厂商配置的响应视图——apiKey 以脱敏形式返回，永不暴露明文"""

    providerType: str | None = None
    baseUrl: str | None = None
    gateway: str | None = None
    modelName: str | None = None
    enabled: bool | None = None
    preferredTasks: list[str] | None = None
    apiKeyMasked: str = ""
    tpm: dict[str, int] | None = None
    usage: dict[str, int] | None = None
    warnAt90: bool | None = None


class LlmConfigResponse(BaseModel):
    """LLM 配置响应（GET）"""

    providers: dict[str, LlmProviderConfigResponse] = Field(default_factory=dict)
    status: str = "not_configured"
    setup_required: bool = True
    configured_provider_count: int = 0
    missing_required: list[str] = Field(default_factory=list)


class LlmProviderConfigUpdate(BaseModel):
    """单个厂商配置的更新请求——apiKey 为空字符串表示保留原值"""

    providerType: str | None = None
    baseUrl: str | None = None
    gateway: str | None = None
    modelName: str | None = None
    enabled: bool | None = None
    preferredTasks: list[str] | None = None
    apiKey: str = ""  # 空字符串 => 保留原值；非空 => 更新
    tpm: dict[str, int] | None = None
    usage: dict[str, int] | None = None
    warnAt90: bool | None = None


class LlmConfigUpdateRequest(BaseModel):
    """LLM 配置更新请求（PUT）"""

    providers: dict[str, LlmProviderConfigUpdate] = Field(default_factory=dict)


def _mask_api_key(key: str) -> str:
    """脱敏 API Key：sk-****abcd 格式（前 3 + 后 4）。与 rag.py 保持一致。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}****{key[-4:]}"


def _validate_llm_base_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None

    candidate = str(base_url).strip()
    if not candidate:
        return None

    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").strip().lower()
    if parsed.scheme.lower() != "https" or not parsed.netloc or not hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LLM provider baseUrl must be an https URL",
        )

    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LLM provider baseUrl must not include userinfo, query, or fragment",
        )

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LLM provider baseUrl must not target localhost",
        )

    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        return candidate

    if not host_ip.is_global:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LLM provider baseUrl must not target private or metadata IP ranges",
        )

    return candidate


def _normalize_preferred_tasks(preferred_tasks: list[str] | None) -> list[str] | None:
    if preferred_tasks is None:
        return None

    normalized: list[str] = []
    for task in preferred_tasks:
        task_name = str(task).strip()
        if task_name and task_name not in normalized:
            normalized.append(task_name)
    return normalized


def _llm_base_url_from_config(cfg: dict) -> str | None:
    value = cfg.get("baseUrl")
    if value is None:
        value = cfg.get("gateway")
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _llm_preferred_tasks_from_config(cfg: dict) -> list[str] | None:
    tasks = cfg.get("preferredTasks")
    if tasks is None:
        tasks = cfg.get("preferred_tasks")
    if not isinstance(tasks, list):
        return None
    return _normalize_preferred_tasks(tasks)


def _llm_provider_response(cfg: dict) -> LlmProviderConfigResponse:
    api_key_plain = cfg.get("apiKey", "") or ""
    base_url = _llm_base_url_from_config(cfg)
    return LlmProviderConfigResponse(
        providerType=cfg.get("providerType"),
        baseUrl=base_url,
        gateway=cfg.get("gateway") or base_url,
        modelName=cfg.get("modelName"),
        enabled=cfg.get("enabled"),
        preferredTasks=_llm_preferred_tasks_from_config(cfg),
        apiKeyMasked=_mask_api_key(api_key_plain),
        tpm=cfg.get("tpm"),
        usage=cfg.get("usage"),
        warnAt90=cfg.get("warnAt90"),
    )


def _require_llm_config_update_access(current_user: User) -> None:
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update LLM provider configuration",
        )


def _llm_config_status(config_map: dict) -> dict:
    configured_provider_count = 0
    has_provider = False
    missing_required = set()

    for cfg in config_map.values():
        if not isinstance(cfg, dict):
            continue
        has_provider = True
        has_gateway = bool(_llm_base_url_from_config(cfg))
        has_api_key = bool(str(cfg.get("apiKey") or "").strip())
        if has_gateway and has_api_key:
            configured_provider_count += 1
        else:
            if not has_gateway:
                missing_required.add("baseUrl")
            if not has_api_key:
                missing_required.add("apiKey")

    if not has_provider:
        missing_required.update({"provider", "baseUrl", "apiKey"})
        status_value = "not_configured"
    elif configured_provider_count == 0:
        status_value = "incomplete"
    elif missing_required:
        status_value = "partially_configured"
    else:
        status_value = "configured"

    return {
        "status": status_value,
        "setup_required": status_value != "configured",
        "configured_provider_count": configured_provider_count,
        "missing_required": sorted(missing_required),
    }


def _load_llm_config_json(company: Company) -> dict:
    """从 company.llm_api_key 反序列化 JSON。
    EncryptedText 类型在 ORM 读取时已自动解密，此处只需 json.loads。"""
    if not company.llm_api_key:
        return {}
    try:
        data = json.loads(company.llm_api_key)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("llm_config_json_parse_failed", company_id=company.id, error=str(exc))
        return {}


def _save_llm_config_json(company_id: int, config_map: dict) -> None:
    """序列化 JSON 并写回数据库（EncryptedText 会自动加密整体 blob）"""
    updated_json = json.dumps(config_map, ensure_ascii=False)
    success = db.update_company_llm_config(company_id, updated_json)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update LLM config",
        )


@router.get("/{company_id:int}/llm-config", response_model=LlmConfigResponse)
async def get_llm_config(
    company_id: int,
    current_user: User = Depends(get_current_active_user),
):
    """获取公司的 LLM 配置。

    - apiKey 返回脱敏版（apiKeyMasked，如 "sk-****abcd"），永不返回明文
    - 未配置的厂商不包含在 providers 中（前端用默认值兜底）
    """
    company = _check_company_access(current_user, company_id)
    try:
        stored = _load_llm_config_json(company)
        providers: dict[str, LlmProviderConfigResponse] = {}
        for key, cfg in stored.items():
            if not isinstance(cfg, dict):
                continue
            providers[key] = _llm_provider_response(cfg)
        return LlmConfigResponse(providers=providers, **_llm_config_status(stored))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_llm_config_failed", company_id=company_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="内部服务器错误",
        )


@router.put("/{company_id:int}/llm-config", response_model=LlmConfigResponse)
async def update_llm_config(
    company_id: int,
    request: LlmConfigUpdateRequest,
    current_user: User = Depends(get_current_active_user),
):
    """更新公司的 LLM 配置。

    - apiKey 为空字符串 => 保留原值（便于只改 gateway/限额不改 key）
    - apiKey 非空 => 更新为新值
    - 返回更新后的脱敏视图（与 GET 一致）
    """
    company = _check_company_access(current_user, company_id)
    _require_llm_config_update_access(current_user)
    try:
        existing = _load_llm_config_json(company)

        for key, incoming in request.providers.items():
            current_cfg = existing.get(key, {}) if isinstance(existing.get(key), dict) else {}
            base_url_provided = incoming.baseUrl is not None or incoming.gateway is not None
            requested_base_url = incoming.baseUrl if incoming.baseUrl is not None else incoming.gateway
            effective_base_url = (
                _validate_llm_base_url(requested_base_url)
                if base_url_provided
                else _llm_base_url_from_config(current_cfg)
            )
            # apiKey 空字符串 => 保留原值；非空 => 更新
            new_api_key = incoming.apiKey.strip() if incoming.apiKey else ""
            if not new_api_key:
                new_api_key = current_cfg.get("apiKey", "") or ""

            merged = {
                "providerType": incoming.providerType
                if incoming.providerType is not None
                else current_cfg.get("providerType"),
                "baseUrl": effective_base_url,
                "gateway": effective_base_url,
                "modelName": incoming.modelName
                if incoming.modelName is not None
                else current_cfg.get("modelName"),
                "enabled": incoming.enabled
                if incoming.enabled is not None
                else current_cfg.get("enabled"),
                "preferredTasks": _normalize_preferred_tasks(incoming.preferredTasks)
                if incoming.preferredTasks is not None
                else _llm_preferred_tasks_from_config(current_cfg),
                "preferred_tasks": _normalize_preferred_tasks(incoming.preferredTasks)
                if incoming.preferredTasks is not None
                else _llm_preferred_tasks_from_config(current_cfg),
                "apiKey": new_api_key,
                "tpm": incoming.tpm if incoming.tpm is not None else current_cfg.get("tpm"),
                "usage": incoming.usage if incoming.usage is not None else current_cfg.get("usage"),
                "warnAt90": incoming.warnAt90
                if incoming.warnAt90 is not None
                else current_cfg.get("warnAt90"),
            }
            existing[key] = merged

        _save_llm_config_json(company_id, existing)
        logger.info("llm_config_updated", company_id=company_id, provider_count=len(existing))

        # 返回脱敏视图
        providers: dict[str, LlmProviderConfigResponse] = {}
        for key, cfg in existing.items():
            if not isinstance(cfg, dict):
                continue
            providers[key] = _llm_provider_response(cfg)
        return LlmConfigResponse(providers=providers, **_llm_config_status(existing))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_llm_config_failed", company_id=company_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="内部服务器错误",
        )

# ==========================================
# 认证 API
# ==========================================
# 这个文件负责用户登录、注册、获取当前用户信息
# 就像是公司的"门卫系统"：验证身份、发放通行证
"""
Authentication router for AgentX Stage 4
Provides login and user information endpoints
"""

# FastAPI 核心工具
# Response: 用于在响应中 Set-Cookie / Delete-Cookie（任务 1：httpOnly cookie 方案）
# Request: 用于在 refresh/logout 端点从 cookie 读取 refresh_token（兼容 body + cookie 双通道）
import os  # 读取 REFRESH_TOKEN_ROTATION 环境变量，控制是否启用 refresh token 轮换

import jwt  # 撤销旧 refresh token 时读取 exp 字段（token 已通过 decode_refresh_token 验证签名）
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

# OAuth2PasswordRequestForm: 标准的登录表单（包含 username 和 password）
from fastapi.security import OAuth2PasswordRequestForm

# Pydantic：定义数据格式
from pydantic import BaseModel, field_validator

# 导入认证核心功能：
# authenticate_user: 验证用户名和密码是否正确
# create_access_token: 生成短期访问令牌（JWT）
# create_refresh_token: 生成长期刷新令牌，用于 access token 过期后换取新 token
# decode_refresh_token: 解码验证 refresh token
# is_token_revoked: P4 新增，检查 refresh token 的 jti 是否在黑名单
# get_current_active_user: 获取当前登录用户（自动验证令牌）
# ACCESS_TOKEN_EXPIRE_MINUTES / REFRESH_TOKEN_EXPIRE_DAYS: 用于计算 cookie 的 max_age（任务 1）
from app.auth import (  # 复用 HS256 算法常量与密钥获取函数
    ACCESS_TOKEN_EXPIRE_MINUTES,  # 任务 1: access_token cookie 的 max_age
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,  # 任务 1: refresh_token cookie 的 max_age
    _get_secret_key,
    authenticate_user,
    create_access_token_for_user,  # P0-3: 签发带 user_id 的 token
    create_refresh_token,
    decode_refresh_token,
    get_current_active_user,
    is_token_revoked,
)
from app.core.logging import get_logger

# token 黑名单单例：logout 时撤销 jti，refresh 时撤销旧 jti
from app.core.token_blacklist import get_token_blacklist

# 数据库相关
from app.database import User, db

logger = get_logger(__name__)

# 创建路由对象
router = APIRouter()

# ==========================================
# Cookie 辅助函数（任务 1：Token 存储强化）
# ==========================================
# 将 access_token / refresh_token 写入 httpOnly cookie，浏览器自动管理，JS 读不到，消除 XSS 窃取风险。
# 三个端点（login / refresh / logout）共用此处的配置，保证 cookie 属性始终一致。


def _is_prod_env() -> bool:
    """判断是否需要启用 Secure cookie。

    默认策略仍然是生产环境启用 Secure；但 Docker 本地联调通常运行在
    http://localhost，此时可通过 COOKIE_SECURE=false 显式关闭，避免登录态
    cookie 被浏览器拒绝发送。
    """
    cookie_secure = os.getenv("COOKIE_SECURE")
    if cookie_secure is not None:
        return cookie_secure.strip().lower() in {"1", "true", "yes", "on"}
    env = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "").strip().lower()
    return env in {"production", "prod"}


def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str | None = None
) -> None:
    """将 access_token / refresh_token 写入 httpOnly cookie。

    属性说明：
    - httponly=True: JS 无法通过 document.cookie 读取，抵御 XSS 窃取 token
    - secure: 仅生产环境开启，要求 cookie 只通过 HTTPS 传输（本地开发 HTTP 不带此标志）
    - samesite="lax": 跨站请求不自动带 cookie，缓解 CSRF；同时允许顶层导航携带，保证登录跳转正常
    - max_age: 与 token 本身的 exp 对齐，过期后浏览器自动清除，无需前端手动清理
    """
    # access_token cookie：短期（默认 30 分钟）
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=_is_prod_env(),
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # 分钟 → 秒，与 JWT exp 保持一致
        path="/",  # 全站可见，确保所有 API 路径都能自动携带
    )
    # refresh_token cookie：可选（轮换未启用或登录失败时不写）
    if refresh_token:
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=_is_prod_env(),
            samesite="lax",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,  # 天 → 秒，与 JWT exp 保持一致
            path="/",
        )


def _clear_auth_cookies(response: Response) -> None:
    """清除 access_token / refresh_token cookie（登出时调用）。

    delete_cookie 需要与 set_cookie 使用相同的 path/samesite 等属性才能正确清除，
    因此此处显式传 path="/"，与 _set_auth_cookies 保持一致。
    """
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/")


# ==========================================
# 数据格式定义
# ==========================================


# 登录成功后的返回格式（令牌信息）
class Token(BaseModel):
    access_token: str  # 短期访问令牌（默认 30 分钟），用于业务接口鉴权
    refresh_token: str  # 长期刷新令牌（默认 7 天），access token 过期后用它换取新 token
    token_type: str  # 令牌类型（固定为 "bearer"）


# 刷新令牌请求体：前端用 refresh_token 换取新 access_token
class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None


# 刷新成功响应：
# - access_token: 必返，新的短期访问令牌
# - refresh_token: 可选，启用轮换策略时返回新的 refresh_token，前端应替换本地存储的旧 token
#   未启用轮换时为 None，前端 client.js 的 setAuthTokens 对 None 值会跳过覆盖，保留原 token
class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str


# 登出请求体：前端将持有的 refresh_token 上交，服务端撤销其 jti 加入黑名单
class LogoutRequest(BaseModel):
    refresh_token: str | None = None


# 登出响应：始终 200，即使 token 已过期或无效也返回 success，
# 避免给攻击者区分"有效 token"和"无效 token"的机会（与登录失败统一返回 401 同理）
class LogoutResponse(BaseModel):
    success: bool
    message: str = ""


# 用户信息的返回格式
class UserResponse(BaseModel):
    id: int  # 用户 ID
    username: str  # 用户名
    company_id: int | None = None  # 所属公司 ID（可能为空）
    disabled: bool = False  # 是否已被禁用
    email: str | None = None  # 邮箱（注册时提供，不允许修改）
    company_name: str | None = None  # 公司名称（关联 companies.name）
    brand_name: str | None = None  # 品牌名称（关联 companies.brand_name）
    category: str | None = None  # 主营类目（关联 companies.category）
    is_admin: bool = False  # 是否为管理员
    avatar_url: str | None = None  # 头像地址（暂未支持上传，预留字段）
    bio: str | None = None  # 个人简介（由 PUT /users/me 原生 SQL 维护）


# 用户注册的请求格式
class UserCreate(BaseModel):
    username: str  # 用户名
    password: str  # 密码
    company_id: int | None = None  # 可选：所属公司 ID
    email: str | None = None  # 可选：邮箱
    company_name: str | None = None  # 可选：公司名称（提供则自动创建公司）
    brand_name: str | None = None  # 可选：品牌名称
    category: str | None = None  # 可选：主营类目

    # 密码校验：确保密码至少 8 位
    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


# ==========================================
# API 接口：登录
# ==========================================
# POST /api/auth/token
# 用户输入用户名密码后，获取访问令牌和刷新令牌
@router.post("/token", response_model=Token)
async def login_for_access_token(
    response: Response, form_data: OAuth2PasswordRequestForm = Depends()
):
    """Login endpoint to get access token and refresh token

    任务 1：登录成功后，除返回 JSON 令牌外，额外通过 Set-Cookie 将 access_token / refresh_token
    写入 httpOnly cookie。浏览器后续请求自动携带 cookie，JS 读不到 token，消除 XSS 窃取风险。
    JSON 返回结构保持不变，旧客户端（localStorage + header）继续可用，新前端可直接用 cookie。
    """

    # 第一步：验证用户名和密码
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        # 验证失败，返回 401 错误（未授权）
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 第二步：生成登录令牌（JWT）
    # access_token 短期有效（30 分钟），用于业务请求鉴权
    # refresh_token 长期有效（7 天），用于 access_token 过期后静默换取新 token，避免用户重新登录
    access_token = create_access_token_for_user(
        user
    )  # P0-3: 嵌入 user_id/company_id/is_admin，使后续请求可走缓存
    refresh_token = create_refresh_token(
        user.username, token_version=int(getattr(user, "token_version", 0) or 0)
    )

    # 第三步：任务 1 —— 把令牌写入 httpOnly cookie，浏览器自动管理，JS 无法读取
    _set_auth_cookies(response, access_token, refresh_token)

    # 返回令牌（JSON 结构保持不变，向后兼容 localStorage 方案的前端）
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


# ==========================================
# API 接口：刷新访问令牌
# ==========================================
# POST /api/auth/token/refresh
# access_token 过期时，前端用 refresh_token 调用此接口换取新的 access_token
# 前端 src/api/client.js 第 108 行调用 /auth/token/refresh（main.py 添加 /api/auth 前缀）
@router.post("/token/refresh", response_model=RefreshTokenResponse)
async def refresh_access_token(
    http_request: Request,
    response: Response,
    req_body: RefreshTokenRequest | None = None,
):
    """Exchange a refresh token for a new access token

    任务 1：refresh_token 双通道提取 —— body 优先（旧客户端），httpOnly cookie 兜底（新前端）。
    刷新成功后重新 Set-Cookie，保持 cookie 与最新令牌同步。

    P4 增强：
    1. 检查 jti 是否在黑名单（logout 后旧 token 失效）
    2. 启用 REFRESH_TOKEN_ROTATION 时撤销旧 refresh_token 并签发新 refresh_token
    """

    # 第零步：任务 1 —— refresh_token 提取（body 优先，cookie 兜底）
    # 旧客户端在 body 传 {refresh_token: "xxx"}；新前端不传 body，靠 httpOnly cookie 自动携带
    refresh_token = (
        req_body.refresh_token if req_body and req_body.refresh_token else None
    ) or http_request.cookies.get("refresh_token")
    if not refresh_token:
        # 两种渠道都没有 refresh_token：视为无效，返回 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 第一步：解码并验证 refresh token（签名、过期时间、type 字段）
    # P4：返回 username / jti / token_version，而非仅 username
    decoded = decode_refresh_token(refresh_token)
    if decoded is None:
        # refresh token 无效或过期，返回 401，前端会清除本地令牌并跳转登录页
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username, jti, refresh_token_version = decoded

    # 第二步：P4 新增 —— 检查 refresh token 是否已被撤销（黑名单）
    # 已 logout 或被轮换掉的 token 应当无法继续换取 access_token
    if await is_token_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 第三步：确认用户仍然存在且未被禁用
    # refresh token 有效期长（7 天），期间用户可能被删除或禁用，必须二次校验防止已失效账号续签
    user = db.get_user_by_username(username)
    if user is None or user.disabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_token_version = int(getattr(user, "token_version", 0) or 0)
    if refresh_token_version is None:
        if current_token_version != 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    elif refresh_token_version != current_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 第四步：签发新的 access token（P0-3: 嵌入 user_id 等字段，使后续请求可走缓存）
    access_token = create_access_token_for_user(user)

    # 第五步：P4 新增 —— 可选的 refresh_token 轮换
    # 默认启用（REFRESH_TOKEN_ROTATION=true）。轮换后旧 jti 撤销，签发带新 jti 的 refresh_token。
    # 前端 client.js 的 setAuthTokens(access, refresh) 仅在 refresh 非空时覆盖本地存储，
    # 因此未启用轮换时返回 None，前端保留原 token。
    rotation_enabled = os.getenv("REFRESH_TOKEN_ROTATION", "true").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )
    new_refresh_token: str | None = None
    if rotation_enabled and jti:
        # 撤销旧 refresh_token：从 JWT payload 读 exp，写入黑名单直到自然过期
        # 此处 token 已通过 decode_refresh_token 验证签名，可安全解码取 exp
        try:
            payload = jwt.decode(
                refresh_token,
                _get_secret_key(),
                algorithms=[ALGORITHM],
                options={
                    "verify_exp": False
                },  # exp 已在 decode_refresh_token 中校验过，此处跳过避免重复
            )
            old_exp = int(payload.get("exp", 0))
            if old_exp > 0:
                await get_token_blacklist().revoke(jti, old_exp)
        except Exception as e:
            # 撤销失败不阻塞主流程：极端情况下旧 token 仍可用，但新 token 已下发，风险可控
            logger.warning("old_token_revoke_failed", error=str(e))
        # 签发新 refresh_token（create_refresh_token 自动注入新 jti）
        new_refresh_token = create_refresh_token(
            username, token_version=current_token_version
        )

    # 第六步：任务 1 —— 刷新成功后重新写 cookie，使 httpOnly cookie 与最新令牌保持同步
    # new_refresh_token 可能为 None（未启用轮换），此时只更新 access_token cookie，保留原 refresh_token cookie
    _set_auth_cookies(response, access_token, new_refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


# ==========================================
# API 接口：登出
# ==========================================
# POST /api/auth/token/logout
# 用户登出时前端将 refresh_token 上交，服务端撤销其 jti 加入黑名单
# 不验证 access_token：登出是公开端点，仅依靠 refresh_token 本身的签名验证身份
@router.post("/token/logout", response_model=LogoutResponse)
async def logout(
    http_request: Request,
    response: Response,
    req_body: LogoutRequest | None = None,
):
    """Revoke a refresh token by adding its jti to the blacklist.

    始终返回 success=True，即使 token 无效或已过期：
    - 防止攻击者通过响应差异枚举有效 token
    - 客户端登出体验一致，无需根据服务端响应决定是否清除本地令牌

    任务 1：refresh_token 双通道提取（body 优先，cookie 兜底）；
    登出时无条件清除 httpOnly cookie，确保浏览器不再持有任何凭据。
    """
    # 任务 1 —— refresh_token 提取（body 优先，cookie 兜底）
    refresh_token = (
        req_body.refresh_token if req_body and req_body.refresh_token else None
    ) or http_request.cookies.get("refresh_token")

    # 任务 1 —— 无条件清除 httpOnly cookie：登出必须清理浏览器侧凭据，
    # 即使后续 token 无效或黑名单撤销失败，cookie 也已删除，客户端进入未登录态
    _clear_auth_cookies(response)

    # 没有 refresh_token（body 和 cookie 都没有）：无法撤销黑名单，但仍返回成功
    if not refresh_token:
        return LogoutResponse(success=True, message="Logged out")

    decoded = decode_refresh_token(refresh_token)
    if decoded is None:
        # token 无效/过期：仍返回 success，前端会无条件清除本地令牌
        return LogoutResponse(success=True, message="Logged out")

    _, jti, _token_version = decoded
    if not jti:
        # 旧版 token 无 jti，无法拉黑，直接返回成功
        return LogoutResponse(success=True, message="Logged out")

    # 读取 exp，将 jti 加入黑名单直到自然过期
    try:
        payload = jwt.decode(
            refresh_token,
            _get_secret_key(),
            algorithms=[ALGORITHM],
            options={"verify_exp": False},  # 已在 decode_refresh_token 中校验过 exp
        )
        exp = int(payload.get("exp", 0))
        if exp > 0:
            await get_token_blacklist().revoke(jti, exp)
    except Exception as e:
        # 撤销失败仍返回 success：客户端已决定登出，服务端记录不到也不应回滚客户端状态
        logger.warning("logout_token_revoke_failed", error=str(e))

    return LogoutResponse(success=True, message="Logged out")


# ==========================================
# API 接口：获取当前用户信息
# ==========================================
# GET /api/auth/users/me
# 获取当前登录用户的信息（自动验证令牌）
@router.get("/users/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Get current user information"""

    # Depends(get_current_active_user) 会自动验证令牌
    # 如果令牌无效或过期，会自动返回 401 错误

    # 查询用户关联的公司信息，填充 company_name / brand_name / category
    company = None
    if current_user.company_id:
        company = db.get_company(current_user.company_id)

    # bio 列在 ORM 模型中未声明（由 PUT /users/me 用原生 SQL 维护），
    # 通过原生 SQL 安全读取；列不存在或查询失败时降级为 None
    bio: str | None = None
    try:
        from sqlalchemy import text

        with db.get_session() as session:
            row = session.execute(
                text("SELECT bio FROM users WHERE id = :uid"),
                {"uid": current_user.id},
            ).first()
            if row is not None:
                bio = row[0]
    except Exception as e:
        logger.warning("get_user_bio_failed", user_id=current_user.id, error=str(e))
        bio = None

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        company_id=current_user.company_id,
        disabled=current_user.disabled,
        email=getattr(current_user, "email", None),
        is_admin=getattr(current_user, "is_admin", False),
        company_name=company.name if company else None,
        brand_name=company.brand_name if company else None,
        category=company.category if company else None,
        avatar_url=getattr(current_user, "avatar_url", None),
        bio=bio,
    )


# ==========================================
# API 接口：用户注册
# ==========================================
# POST /api/auth/users/register
# 创建新用户账号
@router.post("/users/register", response_model=UserResponse)
async def register_user(user_data: UserCreate):
    """Register a new user"""

    # 第一步：检查用户名是否已存在
    existing_user = db.get_user_by_username(user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered"
        )

    # 第二步：解析所属公司
    # - 优先使用传入的 company_id（校验公司存在性）
    # - 否则若传了 company_name，自动创建 Company 记录（含 brand_name / category）
    from app.database.models import Company as ORMCompany
    from app.database.models import User as ORMUser

    company_id = user_data.company_id
    if company_id:
        company = db.get_company(company_id)
        if not company:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")
    elif user_data.company_name:
        new_company = ORMCompany(
            name=user_data.company_name,
            brand_name=user_data.brand_name or user_data.company_name,
            category=user_data.category or "其他",
            platforms_json="[]",
        )
        company_id = db.create_company(new_company)
    else:
        # Regular users need a tenant workspace because conversations, RAG data,
        # cost records, and KOL records are all scoped by company_id.
        default_company_name = f"{user_data.username} workspace"
        new_company = ORMCompany(
            name=default_company_name,
            brand_name=user_data.brand_name or user_data.username,
            category=user_data.category or "default",
            platforms_json="[]",
        )
        company_id = db.create_company(new_company)

    # 第三步：密码加密（永远不要存储明文密码！）
    from app.auth import hash_password

    hashed_password = hash_password(user_data.password)

    # 第四步：创建用户记录
    # 直接使用 ORM 写入，确保 email 字段被持久化（db.create_user 内部的转换会丢弃 email）
    with db.get_session() as session:
        new_user = ORMUser(
            username=user_data.username,
            email=user_data.email,
            password_hash=hashed_password,  # 存储加密后的密码
            company_id=company_id,
            is_admin=False,  # 新用户默认非管理员
            disabled=False,  # 新用户默认启用
        )
        session.add(new_user)
        session.commit()
        user_id = new_user.id

    # 第五步：回读用户与公司信息，构造完整响应
    created_user = db.get_user_by_id(user_id)
    company = db.get_company(company_id) if company_id else None

    return UserResponse(
        id=created_user.id,
        username=created_user.username,
        company_id=created_user.company_id,
        disabled=created_user.disabled,
        email=getattr(created_user, "email", None),
        is_admin=getattr(created_user, "is_admin", False),
        company_name=company.name if company else None,
        brand_name=company.brand_name if company else None,
        category=company.category if company else None,
        avatar_url=None,
        bio=None,
    )


# ==========================================
# API 接口：更新当前用户资料
# ==========================================
# PUT /api/auth/users/me
# 更新当前登录用户的资料（公司信息、个人简介）；用户名/邮箱属于账号标识，不在资料页修改
class UserProfileUpdateRequest(BaseModel):
    username: str | None = None
    company_name: str | None = None
    brand_name: str | None = None
    category: str | None = None
    avatar_url: str | None = None
    bio: str | None = None


@router.put("/users/me")
async def update_current_user_profile(
    request: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_active_user),
):
    """更新当前用户资料

    字段分流（参照 database/models.py 中的表结构）：
    - bio → users 表
    - company_name(→name), brand_name, category → companies 表（通过 company_id 关联）
    - username / email 不允许在资料页修改
    """
    from sqlalchemy import inspect, text

    from app.database.models import Company as ORMCompany
    from app.database.models import User as ORMUser

    updates = {k: v for k, v in request.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    if "username" in updates:
        requested_username = updates.pop("username")
        if requested_username != current_user.username:
            raise HTTPException(status_code=400, detail="用户名暂不支持在资料页修改")
        if not updates:
            return {"success": True, "message": "资料已保存"}

    # 公司字段名映射：请求体字段 → companies 表列名
    company_key_map = {
        "company_name": "name",
        "brand_name": "brand_name",
        "category": "category",
    }

    try:
        with db.get_session() as session:
            # 0) bio 列在历史 schema 中可能不存在：幂等添加（在任何业务更新之前完成）
            if "avatar_url" in updates:
                session.query(ORMUser).filter(ORMUser.id == current_user.id).update(
                    {ORMUser.avatar_url: updates["avatar_url"]}, synchronize_session=False
                )

            if "bio" in updates:
                try:
                    columns = {column["name"] for column in inspect(session.bind).get_columns("users")}
                    if "bio" not in columns:
                        session.execute(text("ALTER TABLE users ADD COLUMN bio TEXT"))
                        session.commit()
                except Exception as e:
                    # 列已存在或 DDL 失败 → 回滚后继续，后续 UPDATE 仍可正常工作
                    logger.warning("add_bio_column_failed", error=str(e))
                    session.rollback()

            # 1) bio → users 表（原生 SQL，因为 ORM 模型未声明 bio 字段）
            if "bio" in updates:
                session.execute(
                    text("UPDATE users SET bio = :bio WHERE id = :uid"),
                    {"bio": updates["bio"], "uid": current_user.id},
                )

            # 2) 公司相关字段 → companies 表
            company_updates = {
                company_key_map[k]: updates[k] for k in updates if k in company_key_map
            }
            if company_updates and current_user.company_id:
                company = (
                    session.query(ORMCompany)
                    .filter(ORMCompany.id == current_user.company_id)
                    .first()
                )
                if company:
                    for k, v in company_updates.items():
                        setattr(company, k, v)

            session.commit()
    except HTTPException:
        raise
    except Exception:
        logger.exception("update_user_profile_failed")
        raise HTTPException(status_code=500, detail="内部服务器错误")

    return {"success": True, "message": "资料已保存"}


# ==========================================
# API 接口：修改密码
# ==========================================
# POST /api/auth/password/change
# 已登录用户修改自己的密码，需验证当前密码
class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/password/change")
async def change_password(
    request: PasswordChangeRequest,
    current_user: User = Depends(get_current_active_user),
):
    """修改当前用户密码"""
    # 复用 app.auth 中已有的 bcrypt 哈希/校验函数，保持密码策略一致
    from app.auth import hash_password, invalidate_user_cache, verify_password

    # auth_router 顶层导入的 User 是 Pydantic 模型，ORM 查询需要真正的 SQLAlchemy 模型
    from app.database.models import User as ORMUser

    # 校验新密码强度（最简校验：≥8 位）
    if len(request.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少 8 位")

    # 在新的 session 中获取用户并更新密码
    # current_user 来自已关闭的 session（detached），不能直接修改后 commit
    with db.get_session() as session:
        user = session.query(ORMUser).filter(ORMUser.id == current_user.id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

        # 校验当前密码（不区分"用户不存在"和"密码错误"，统一返回相同提示以防枚举）
        if not user.password_hash or not verify_password(
            request.current_password, user.password_hash
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")

        # 更新密码哈希
        user.password_hash = hash_password(request.new_password)
        user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
        user_id = user.id
        session.commit()

    try:
        invalidate_user_cache(user_id)
    except Exception as e:
        logger.warning("change_password_cache_invalidate_failed", user_id=user_id, error=str(e))

    return {"success": True, "message": "密码已更新"}


# ==========================================
# API 接口：忘记密码 — 申请重置链接
# ==========================================
# POST /api/auth/password/forgot
# 用户在登录页点击"忘记密码"后提交邮箱，触发重置流程
# 安全策略：无论邮箱是否存在都返回相同响应（防枚举攻击）
class PasswordForgotRequest(BaseModel):
    email: str


@router.post("/password/forgot")
async def forgot_password(request: PasswordForgotRequest):
    """忘记密码 — 申请重置链接

    安全策略：无论邮箱是否存在都返回相同响应（防枚举攻击）
    实际项目中这里应该：
    1. 查询用户是否存在
    2. 生成重置 token（带过期时间）
    3. 发送重置邮件（SMTP）
    4. 当前未接入 SMTP，仅记录日志
    """
    from app.core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("password_reset_requested", email=request.email)

    # 接入 SMTP 实现真实邮件发送：
    # 1. 按 email 查询用户是否存在（db 未提供 get_user_by_email，用原生 SQL 安全查询）
    # 2. 若存在，生成短期密码重置 token（JWT，type=password_reset，30 分钟过期）
    # 3. 构造重置链接并调用 send_email 发送 HTML 邮件
    # 4. send_email 内部失败不抛异常，此处整体 try/except 兜底
    #
    # 安全策略：无论用户是否存在、邮件是否发送成功，均返回相同响应（防枚举攻击），
    # 攻击者无法通过响应差异判断邮箱是否已注册。
    import time

    from sqlalchemy import text

    from app.core.email import send_email

    try:
        # 按 email 查询用户（email 列在 register_user 中已确认存在）
        user_row = None
        with db.get_session() as session:
            row = session.execute(
                text("SELECT id, username FROM users WHERE email = :email"),
                {"email": request.email},
            ).first()
            user_row = row

        if user_row is not None:
            _user_id, username = user_row[0], user_row[1]

            # 生成密码重置 token：复用 JWT 签名能力，嵌入 username/email/type/exp
            # type=password_reset 区分于 access/refresh token，防止跨用途滥用
            reset_payload = {
                "sub": username,
                "email": request.email,
                "type": "password_reset",
                "exp": int(time.time()) + 1800,  # 30 分钟有效期
            }
            reset_token = jwt.encode(reset_payload, _get_secret_key(), algorithm=ALGORITHM)

            # 重置链接：前端 URL + token，前端页面负责引导用户输入新密码并调用重置接口
            # FRONTEND_URL 从环境变量读取（如 https://app.example.com）
            frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")
            reset_link = f"{frontend_url}/reset-password?token={reset_token}"

            # 构造 HTML 邮件正文（send_email 会自动附纯文本兜底）
            html_body = (
                f"<p>您好 {username}，</p>"
                f"<p>您正在重置 AgentX 账号密码，请在 30 分钟内点击下方链接完成重置：</p>"
                f'<p><a href="{reset_link}">{reset_link}</a></p>'
                f"<p>若非本人操作，请忽略此邮件，您的账号安全不受影响。</p>"
            )
            # 发送邮件：send_email 失败时仅记日志、返回 False，不抛异常中断流程
            await send_email(
                to=request.email,
                subject="【AgentX】密码重置",
                body=html_body,
                html=True,
            )
    except Exception as e:
        # 兜底：任何异常都不影响对用户的统一响应，避免泄露内部状态或邮箱是否存在
        logger.error("password_reset_email_flow_failed", email=request.email, error=str(e))

    return {"success": True, "message": "如果该邮箱已注册，你将收到重置密码邮件"}


# ==========================================
# API 接口：密码重置确认（任务 2）
# ==========================================
# POST /api/auth/password/reset
# 用户从重置邮件链接进入重置页面，提交 reset token + 新密码，验证通过后更新密码
# 配合 POST /api/auth/password/forgot 使用（forgot 签发 token，reset 验证 token）
class PasswordResetConfirmRequest(BaseModel):
    token: str  # forgot 接口签发的密码重置 JWT（type=password_reset，30 分钟有效）
    new_password: str  # 新密码（需通过强度校验：长度 >= 8）

    # 新密码基本强度校验：与注册/修改密码保持一致的最小长度策略
    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


@router.post("/password/reset")
async def reset_password(request: PasswordResetConfirmRequest):
    """密码重置确认 —— 验证 reset token 并设置新密码（任务 2）

    流程：
    1. 新密码强度校验（长度 >= 8）—— 输入校验，可明示原因
    2. jwt.decode 验证 token：签名、过期、type=password_reset
    3. 从 token 取 username，查询用户
    4. 用 bcrypt 哈希新密码，更新数据库

    安全策略：
    - token 无效/过期/类型不符/用户不存在，统一返回 400 通用消息，不泄露具体原因（防枚举）
    - 新密码不达标返回 400 明确提示（属于输入校验，不依赖 token 有效性，不泄露 token 状态）
    - 成功返回 200；token 无效/过期返回 400
    """
    # 延迟导入：复用 app.auth 的哈希函数与缓存失效函数，保持密码策略与缓存行为一致
    from app.auth import hash_password, invalidate_user_cache

    # ORM User：更新密码需要真正的 SQLAlchemy 模型，而非顶层导入的 Pydantic User
    from app.database.models import User as ORMUser

    # 第一步：验证 reset token（签名 + 过期 + type）
    # 复用 forgot_password 签发时的 ALGORITHM 与 _get_secret_key，保证验签一致
    try:
        payload = jwt.decode(
            request.token,
            _get_secret_key(),
            algorithms=[ALGORITHM],
        )
    except jwt.PyJWTError:
        # 签名无效 / 格式错误 / 已过期：统一返回通用消息，不区分具体原因（防枚举攻击）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接无效或已过期")

    # 校验 type 字段：必须是 password_reset，拒绝 access/refresh token 被挪用作重置凭据
    if payload.get("type") != "password_reset":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接无效或已过期")

    # 第二步：从 token 取 username（forgot 签发时 sub=username），查询用户
    username = payload.get("sub")
    if not username:
        # sub 字段缺失：token 签发不完整，视为无效
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接无效或已过期")

    # 第三步：查询用户并更新密码哈希
    # 用户不存在也返回通用消息：避免攻击者通过响应差异判断用户名是否存在
    with db.get_session() as session:
        user = session.query(ORMUser).filter(ORMUser.username == username).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="重置链接无效或已过期"
            )

        # 用 bcrypt 哈希新密码（hash_password 内部自动生成随机盐）
        user.password_hash = hash_password(request.new_password)
        user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
        session.commit()
        # 在 session 关闭前取出 user_id，用于失效缓存（detached 后访问 id 仍可，但显式取出更稳妥）
        user_id = user.id

    # 第四步：失效用户缓存。token_version 已递增，旧 access/refresh token 会因版本不匹配失效。
    try:
        invalidate_user_cache(user_id)
    except Exception as e:
        # 缓存失效失败不阻塞主流程：缓存有 TTL，最迟 60s 后自然过期
        logger.warning("reset_password_cache_invalidate_failed", user_id=user_id, error=str(e))

    return {"success": True, "message": "密码已重置，请使用新密码登录"}

"""Authentication utilities for AgentX Stage 4
Handles JWT tokens, password hashing, and user authentication"""
# 本模块是系统中所有身份认证的单一入口，集中管理可以避免各处重复实现导致的安全策略不一致

import contextlib
import os  # 从环境变量读取敏感配置（密钥、过期时间），避免硬编码到代码中
import time  # 用户缓存的 TTL 时间戳计算
import uuid  # 为 refresh token 生成唯一 jti（JWT ID），用于黑名单撤销与轮换追踪
from datetime import (  # JWT 签发和过期判断必须使用 UTC 时间，避免跨时区部署时的时钟偏差
    datetime,
    timedelta,
)
from typing import (
    Any,  # JWT payload 中可存放任意类型的自定义字段（如 sub、company_id），因此键值类型不定
)

import bcrypt  # 选用 bcrypt 而非 SHA 系列，因为 bcrypt 内置盐值 + 自适应计算成本，能有效抵御彩虹表和暴力破解
import jwt  # PyJWT 库：轻量、纯 Python 实现，与 FastAPI 生态契合，不需要额外安装 C 扩展
from fastapi import (  # Depends 让认证逻辑以依赖注入方式复用；Request 用于从 cookie 兜底读取 token
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.security import (
    OAuth2PasswordBearer,  # 符合 OAuth2 规范的 Bearer Token 提取器，自动解析 Authorization 头
)

from app.core.logging import get_logger  # 使用项目统一的日志格式，便于 ELK/链路追踪中按模块过滤
from app.database import (  # 直接导入数据库单例，而非在函数内按需获取，保证所有认证操作使用同一个数据库连接
    User,
    db,
)
from app.database.models import (
    User as ORMUser,  # ORM User：db.get_user_by_username 实际返回此类型，缓存构造也用此类型保持一致
)

logger = get_logger(__name__)  # 用模块名作为 logger 标识，排查问题时可以快速定位日志来源

ALGORITHM = (
    "HS256"  # 对称签名算法：单服务部署场景下无需引入 RSA 密钥对的复杂性，且 HS256 验证速度最快
)
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_EXPIRE_MINUTES", "30")
)  # access token 短期有效（默认 30 分钟），过期后用 refresh token 换取新 token
REFRESH_TOKEN_EXPIRE_DAYS = int(
    os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7")
)  # refresh token 长期有效（默认 7 天），仅用于换取新 access token，不用于业务鉴权

# 用户对象缓存 TTL（秒）：缓存命中时跳过 DB 查询，将认证路由的 P99 瓶颈消除
# TTL 60s 平衡实时性与性能——用户被禁用/删除后最多 60s 内失效
USER_CACHE_TTL_SECONDS = int(os.getenv("USER_CACHE_TTL_SECONDS", "60"))

# 进程内用户缓存（Redis 不可用时降级使用）
# 结构: {user_id: (user_dict, expire_timestamp)}
_user_cache: dict[int, tuple[dict, float]] = {}

# Redis 客户端（懒初始化）：可用时用于多实例共享用户缓存
_redis_client = None


def _get_redis_client():
    """懒初始化 Redis 客户端，连接失败返回 None（降级到内存缓存）"""
    global _redis_client
    if _redis_client is not None:
        return _redis_client if _redis_client is not False else None
    try:
        import redis as _redis

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = _redis.from_url(url, socket_connect_timeout=2)
        _redis_client.ping()
        logger.info("auth_user_cache_redis_connected")
    except Exception as e:
        logger.warning("auth_user_cache_redis_unavailable_fallback_to_memory", error=str(e))
        _redis_client = False  # 标记为不可用，避免每次请求都重试连接
        return None
    return _redis_client


def _user_to_dict(user: User) -> dict:
    """将 User ORM 对象转为可缓存的 dict（避免 session 关闭后属性访问问题）"""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "company_id": user.company_id,
        "is_admin": user.is_admin,
        "disabled": user.disabled,
        "is_active": user.is_active,
        "token_version": int(getattr(user, "token_version", 0) or 0),
        "password_hash": user.password_hash,
        "created_at": user.created_at,
    }


def _user_from_dict(data: dict) -> User:
    """从缓存 dict 构造 User 对象（不走 DB，避免每请求查库）

    使用 ORM User 构造，与 db.get_user_by_username 返回类型一致。
    SQLAlchemy ORM 模型可直接用 **kwargs 构造，不会像 Pydantic 那样
    依赖 __init__ 设置内部状态（如 __pydantic_fields_set__）。
    """
    return ORMUser(**data)


def _cache_get(user_id: int) -> User | None:
    """从 Redis 或内存缓存读取用户，miss 返回 None"""
    # 优先 Redis
    rds = _get_redis_client()
    if rds is not None:
        try:
            import json

            raw = rds.get(f"user_cache:{user_id}")
            if raw:
                return _user_from_dict(json.loads(raw))
        except Exception as e:
            logger.warning("auth_user_cache_redis_get_failed", error=str(e))
    # 内存降级
    entry = _user_cache.get(user_id)
    if entry and entry[1] > time.time():
        return _user_from_dict(entry[0])
    if entry:
        _user_cache.pop(user_id, None)  # 过期清理
    return None


def _cache_set(user: User) -> None:
    """写入用户缓存（Redis + 内存双写，Redis 失败只写内存）"""
    data = _user_to_dict(user)
    rds = _get_redis_client()
    if rds is not None:
        try:
            import json

            rds.setex(
                f"user_cache:{user.id}", USER_CACHE_TTL_SECONDS, json.dumps(data, default=str)
            )
        except Exception as e:
            logger.warning("auth_user_cache_redis_set_failed", error=str(e))
    # 内存也写一份（Redis 不可用时的主缓存，可用时作为本地热副本）
    _user_cache[user.id] = (data, time.time() + USER_CACHE_TTL_SECONDS)


def invalidate_user_cache(user_id: int) -> None:
    """用户被禁用/删除/更新时调用，主动失效缓存（管理后台修改用户时使用）"""
    _user_cache.pop(user_id, None)
    rds = _get_redis_client()
    if rds is not None:
        with contextlib.suppress(Exception):
            rds.delete(f"user_cache:{user_id}")


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/token"
)  # tokenUrl 告知 OpenAPI 文档和前端登录端点位置，FastAPI 自动生成表单登录页

# 可选 Bearer 提取器：header 缺失时不抛 401，返回 None。
# 用于 get_current_user 实现"header 优先 + cookie 兜底"的双通道提取：
# 旧客户端继续走 Authorization header，新前端走 httpOnly cookie，互不干扰。
# 保留原 oauth2_scheme（auto_error=True）不改动，避免影响其他可能的引用与文档行为。
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


def _get_secret_key() -> str:
    # 每次调用时从环境变量读取，而非模块加载时缓存，这样密钥轮换无需重启进程
    key = os.getenv("JWT_SECRET_KEY")
    # 严禁使用默认值：默认密钥一旦提交到代码仓库，攻击者可直接伪造任意用户的 JWT
    # 覆盖 .env.example 中可能出现的占位符及常见不安全默认值，命中即拒绝启动
    if key in (
        "your-secret-key-here",
        "change-me",
        "",
        None,
        "your-secret-key-change-in-production",
    ):
        raise RuntimeError("JWT_SECRET_KEY 未配置或使用了不安全的默认值，请在 .env 中设置真实密钥")
    return key


def hash_password(plain_password: str) -> str:
    """Hash a password using bcrypt"""
    salt = (
        bcrypt.gensalt()
    )  # 每次调用都生成新的随机盐，即使两个用户使用相同明文密码，存储的哈希值也完全不同
    hashed = bcrypt.hashpw(
        plain_password.encode("utf-8"), salt
    )  # 必须先编码为 bytes，因为 bcrypt 底层操作的是字节流
    return hashed.decode("utf-8")  # 存回字符串以兼容数据库 TEXT 字段，避免到处处理 bytes/str 转换


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        # 不暴露具体错误原因：无论密码错误、哈希格式损坏还是其他异常，统一返回 False
        # 这样可以防止攻击者通过错误消息差异推断有效用户或哈希格式
        return False


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token

    优化（P0-3）：建议调用方使用 create_access_token_for_user 传入完整 user 对象，
    将 user_id/company_id/is_admin/disabled 嵌入 payload，使 get_current_user
    可直接从缓存读取用户而无需每请求查库。本函数保持向后兼容。
    """
    to_encode = data.copy()  # 复制一份，避免修改调用方传入的 dict，防止副作用导致调用方状态异常

    if expires_delta:
        expire = (
            datetime.utcnow() + expires_delta
        )  # 调用方显式指定过期时长时优先使用，用于"记住我"等场景的延长过期
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )  # 默认使用全局配置，保证所有短期 token 策略一致

    # type 字段区分 access/refresh，防止 refresh token 被当作 access token 用于业务鉴权
    to_encode.update(
        {"exp": expire, "type": "access"}
    )  # JWT 规范要求 exp 字段，PyJWT 库在 decode 时会自动校验，但此处也手动设置确保兼容
    encoded_jwt = jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)
    return encoded_jwt


def create_access_token_for_user(user: Any, expires_delta: timedelta | None = None) -> str:
    """签发 access token 并将用户关键字段嵌入 payload（P0-3 优化）

    将 user_id/company_id/is_admin/disabled 写入 JWT，使 get_current_user
    可优先从缓存读取用户对象，避免每个认证请求都查库。

    Args:
        user: User ORM 对象，需有 id/username/company_id/is_admin/disabled 属性
        expires_delta: 可选过期时长
    """
    return create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "company_id": user.company_id,
            "is_admin": bool(user.is_admin),
            "disabled": bool(user.disabled),
            "token_version": int(getattr(user, "token_version", 0) or 0),
        },
        expires_delta=expires_delta,
    )


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode a JWT access token"""
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        # Check if token has expired
        exp = payload.get("exp")
        if exp is None or datetime.utcnow() > datetime.fromtimestamp(exp):
            # 手动双重校验过期：虽然 jwt.decode 内部已校验 exp，但某些旧版 PyJWT 或特殊配置下可能跳过
            # 同时 exp 为 None 表示签发时有 Bug，不应放行
            return None
        if payload.get("type") != "access":
            # 严格校验 type 字段：拒绝 refresh token 或缺失 type 的旧 token 用于访问受保护资源
            # 这样即使 refresh token 泄露，也无法直接调用业务接口
            return None
        return payload
    except jwt.PyJWTError:
        # 任何 JWT 异常（签名无效、格式错误、已过期等）统一返回 None
        # 不抛出异常是为了让调用方用统一的返回值模式处理，避免多层 try/except 嵌套
        return None


def create_refresh_token(
    username: str, jti: str | None = None, token_version: int | None = None
) -> str:
    """Create a long-lived JWT refresh token (default 7 days)

    与 access token 使用相同密钥签名，但通过 type='refresh' 字段区分用途，
    确保两种 token 不可互相替代：refresh token 只能用于换取新 access token，
    不能直接访问受保护接口；access token 也不能用于刷新。

    Args:
        username: 用户名，作为 JWT 的 sub 字段
        jti: 可选的 JWT ID。未传入时自动生成 uuid4。
             注入 jti 后可在 refresh 端点撤销旧 token、在 logout 时拉黑具体 token，
             实现 token 轮换与登出语义。
        token_version: 用户级 token 版本。密码修改/重置后递增，旧 token 因版本不匹配失效。
    """
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    # jti = JWT ID：RFC 7519 标准字段，用作 token 唯一标识符，用于黑名单撤销
    # 默认生成 uuid4：碰撞概率可忽略，且不依赖外部输入，防止调用方传入可预测值
    token_jti = jti or str(uuid.uuid4())
    to_encode = {
        "sub": username,
        "exp": expire,
        "type": "refresh",
        "jti": token_jti,
    }
    if token_version is not None:
        to_encode["token_version"] = int(token_version or 0)
    return jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)


def decode_refresh_token(token: str) -> tuple[str, str, int | None] | None:
    """Decode and validate a refresh token.

    Returns:
        (username, jti, token_version) 元组；token 无效或过期时返回 None。

    返回 jti 是为了让调用方（auth_router.refresh_access_token / logout）
    能进一步查询黑名单或撤销旧 token。旧版 refresh token（无 jti 字段）
    会得到 jti="" —— 调用方应允许空 jti 通过黑名单检查，保证向后兼容。
    """
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        exp = payload.get("exp")
        if exp is None or datetime.utcnow() > datetime.fromtimestamp(exp):
            return None
        if payload.get("type") != "refresh":
            # 拒绝 access token 或其他类型 token 被用作 refresh，强制类型隔离
            return None
        username: str = payload.get("sub")
        if username is None:
            return None
        # 旧 token 没有 jti 字段，统一返回空字符串，由调用方决定是否放行
        jti: str = payload.get("jti") or ""
        token_version_raw = payload.get("token_version")
        token_version: int | None = None
        if token_version_raw is not None:
            try:
                token_version = int(token_version_raw)
            except (TypeError, ValueError):
                return None
        return (username, jti, token_version)
    except jwt.PyJWTError:
        return None


async def is_token_revoked(jti: str) -> bool:
    """检查 refresh token 的 jti 是否已被加入黑名单。

    委托给 TokenBlacklist 单例，Redis 异常时降级到内存查询；
    空 jti（旧版 token 无 jti 字段）视为未撤销，由调用方在路由层决定是否拒绝。

    设计为 async：底层 TokenBlacklist.is_revoked 是 async 方法（Redis 异步 IO）。
    """
    if not jti:
        # 旧版 token 没有 jti，无法拉黑，保守放行，避免一刀切导致老用户被踢
        return False
    # 延迟导入避免循环依赖：token_blacklist 不依赖 auth，但保持延迟导入习惯
    from app.core.token_blacklist import get_token_blacklist

    return await get_token_blacklist().is_revoked(jti)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme_optional),
) -> User:
    """FastAPI dependency to get current authenticated user

    双通道 token 提取（任务 1：Token 存储强化）：
    1. 优先从 Authorization: Bearer xxx header 提取 —— 向后兼容旧客户端、移动端、API 调用
    2. header 缺失时从 httpOnly cookie 'access_token' 读取 —— 新前端方案，JS 读不到，消除 XSS 窃取风险
    两种渠道都没有 token 时抛 401。

    优化（P0-3）：优先从 JWT payload 提取 user_id，查 Redis/内存缓存；
    缓存命中直接返回 User 对象，跳过 DB 查询。miss 时回退到 DB 查询并写缓存。
    旧版 token（无 user_id 字段）保持原行为，按 username 查库。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={
            "WWW-Authenticate": "Bearer"
        },  # WWW-Authenticate 头让浏览器在收到 401 时自动弹出登录窗口，符合 RFC 7235
    )

    # Token 提取：先 Authorization header（oauth2_scheme_optional 已解析），再 httpOnly cookie 兜底
    # 这样旧客户端（localStorage + header）和新前端（httpOnly cookie）可同时工作，互不破坏
    actual_token = token
    if not actual_token:
        # header 无 Bearer token 时，尝试从 httpOnly cookie 读取（新前端方案）
        actual_token = request.cookies.get("access_token")
    if not actual_token:
        # 两种渠道都没有 token：未登录或会话已失效
        raise credentials_exception

    try:
        payload = decode_access_token(actual_token)
        if payload is None:
            raise credentials_exception  # token 无效或过期时统一抛 401，不给攻击者区分"无效 token"和"过期 token"的机会

        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception  # sub 字段缺失说明 token 签发不完整，视为无效
    except jwt.PyJWTError:
        # PyJWTError 捕获 decode_access_token 内部未捕获的所有 JWT 异常（极端防御）
        raise credentials_exception

    # 优先走缓存路径：payload 中含 user_id 时查缓存
    user_id = payload.get("user_id")
    user: User | None = None
    if user_id is not None:
        user = _cache_get(user_id)

    # 缓存 miss 或旧版 token（无 user_id）：回退到 DB 查询
    if user is None:
        user = db.get_user_by_username(username)
        if user is None:
            raise credentials_exception  # token 有效但用户已被删除，同样返回 401 而非 404，防止用户枚举攻击
        # 写缓存供后续请求命中
        _cache_set(user)

    current_token_version = int(getattr(user, "token_version", 0) or 0)
    payload_token_version = payload.get("token_version")
    if payload_token_version is None:
        if current_token_version != 0:
            raise credentials_exception
    else:
        try:
            if int(payload_token_version) != current_token_version:
                raise credentials_exception
        except (TypeError, ValueError):
            raise credentials_exception

    if user.disabled:
        # 用户被禁用返回 400 而非 401：认证成功但账号不可用，客户端可据此展示不同的提示信息
        # 注意：缓存中 disabled=True 也会在此拦截，主动失效缓存避免持续返回被禁用户
        if user_id is not None:
            invalidate_user_cache(user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency to get current active user"""
    if current_user.disabled:
        # 此处重复检查 disabled 状态：虽然 get_current_user 已检查，但 get_current_active_user 可能被其他
        # 非 get_current_user 路径创建的 User 对象调用，独立校验保证任何入口都不会遗漏禁用检查
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def authenticate_user(username: str, password: str) -> User | None:
    """Authenticate a user with username and password"""
    user = db.get_user_by_username(username)
    if not user:
        return None  # 用户不存在时直接返回 None，不给调用方区分"用户不存在"和"密码错误"的机会
    if not verify_password(password, user.password_hash):
        return None  # 密码错误也返回 None，与用户不存在的返回值一致，防止基于响应的用户枚举
    return user


async def get_current_company_id(current_user: User = Depends(get_current_active_user)) -> int:
    """FastAPI dependency to get current user's company_id for multi-tenant isolation"""
    if current_user.company_id is None:
        # company_id 为空说明用户未关联任何租户，可能是系统管理员或数据异常，返回 403 明确拒绝
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is not associated with any company"
        )
    return current_user.company_id


def same_company_access(company_id: int, resource_company_id: int):
    """Verify resource belongs to the same company"""
    if company_id != resource_company_id:
        # 跨公司访问返回 404 而非 403：从安全角度，不应让攻击者知道另一个公司的资源是否存在
        # 404 让所有无权限的资源"看起来不存在"，是最小化信息泄露的做法
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

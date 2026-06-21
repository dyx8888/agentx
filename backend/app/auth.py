"""Authentication utilities for AgentX Stage 4
Handles JWT tokens, password hashing, and user authentication"""
# 本模块是系统中所有身份认证的单一入口，集中管理可以避免各处重复实现导致的安全策略不一致

import os  # 从环境变量读取敏感配置（密钥、过期时间），避免硬编码到代码中
from datetime import datetime, timedelta  # JWT 签发和过期判断必须使用 UTC 时间，避免跨时区部署时的时钟偏差
from typing import Any  # JWT payload 中可存放任意类型的自定义字段（如 sub、company_id），因此键值类型不定

import bcrypt  # 选用 bcrypt 而非 SHA 系列，因为 bcrypt 内置盐值 + 自适应计算成本，能有效抵御彩虹表和暴力破解
import jwt  # PyJWT 库：轻量、纯 Python 实现，与 FastAPI 生态契合，不需要额外安装 C 扩展
from fastapi import Depends, HTTPException, status  # Depends 让认证逻辑以依赖注入方式复用，避免每个路由手动调用
from fastapi.security import OAuth2PasswordBearer  # 符合 OAuth2 规范的 Bearer Token 提取器，自动解析 Authorization 头

from app.core.logging import get_logger  # 使用项目统一的日志格式，便于 ELK/链路追踪中按模块过滤
from app.database import User, db  # 直接导入数据库单例，而非在函数内按需获取，保证所有认证操作使用同一个数据库连接

logger = get_logger(__name__)  # 用模块名作为 logger 标识，排查问题时可以快速定位日志来源

ALGORITHM = "HS256"  # 对称签名算法：单服务部署场景下无需引入 RSA 密钥对的复杂性，且 HS256 验证速度最快
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))  # 环境变量控制过期时间，生产环境可调短以降低泄露风险

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")  # tokenUrl 告知 OpenAPI 文档和前端登录端点位置，FastAPI 自动生成表单登录页


def _get_secret_key() -> str:
    # 每次调用时从环境变量读取，而非模块加载时缓存，这样密钥轮换无需重启进程
    key = os.getenv("JWT_SECRET_KEY")
    if not key or key == "your-secret-key-change-in-production":
        # 严禁使用默认值：默认密钥一旦提交到代码仓库，攻击者可直接伪造任意用户的 JWT
        raise ValueError(
            "JWT_SECRET_KEY environment variable must be set and not use the default value. "
            "Generate a secure key with: python -c \"import secrets; print(secrets.token_hex(32))\"")
    return key

def hash_password(plain_password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()  # 每次调用都生成新的随机盐，即使两个用户使用相同明文密码，存储的哈希值也完全不同
    hashed = bcrypt.hashpw(plain_password.encode('utf-8'), salt)  # 必须先编码为 bytes，因为 bcrypt 底层操作的是字节流
    return hashed.decode('utf-8')  # 存回字符串以兼容数据库 TEXT 字段，避免到处处理 bytes/str 转换

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        # 不暴露具体错误原因：无论密码错误、哈希格式损坏还是其他异常，统一返回 False
        # 这样可以防止攻击者通过错误消息差异推断有效用户或哈希格式
        return False

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()  # 复制一份，避免修改调用方传入的 dict，防止副作用导致调用方状态异常

    if expires_delta:
        expire = datetime.utcnow() + expires_delta  # 调用方显式指定过期时长时优先使用，用于"记住我"等场景的延长过期
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)  # 默认使用全局配置，保证所有短期 token 策略一致

    to_encode.update({"exp": expire})  # JWT 规范要求 exp 字段，PyJWT 库在 decode 时会自动校验，但此处也手动设置确保兼容
    encoded_jwt = jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)
    return encoded_jwt

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
        return payload
    except jwt.PyJWTError:
        # 任何 JWT 异常（签名无效、格式错误、已过期等）统一返回 None
        # 不抛出异常是为了让调用方用统一的返回值模式处理，避免多层 try/except 嵌套
        return None

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """FastAPI dependency to get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},  # WWW-Authenticate 头让浏览器在收到 401 时自动弹出登录窗口，符合 RFC 7235
    )

    try:
        payload = decode_access_token(token)
        if payload is None:
            raise credentials_exception  # token 无效或过期时统一抛 401，不给攻击者区分"无效 token"和"过期 token"的机会

        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception  # sub 字段缺失说明 token 签发不完整，视为无效
    except jwt.PyJWTError:
        # PyJWTError 捕获 decode_access_token 内部未捕获的所有 JWT 异常（极端防御）
        raise credentials_exception

    user = db.get_user_by_username(username)
    if user is None:
        raise credentials_exception  # token 有效但用户已被删除，同样返回 401 而非 404，防止用户枚举攻击

    if user.disabled:
        # 用户被禁用返回 400 而非 401：认证成功但账号不可用，客户端可据此展示不同的提示信息
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any company"
        )
    return current_user.company_id


def same_company_access(company_id: int, resource_company_id: int):
    """Verify resource belongs to the same company"""
    if company_id != resource_company_id:
        # 跨公司访问返回 404 而非 403：从安全角度，不应让攻击者知道另一个公司的资源是否存在
        # 404 让所有无权限的资源"看起来不存在"，是最小化信息泄露的做法
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resource not found"
        )

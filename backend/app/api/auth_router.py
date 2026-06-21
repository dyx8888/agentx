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
from fastapi import APIRouter, Depends, HTTPException, status
# OAuth2PasswordRequestForm: 标准的登录表单（包含 username 和 password）
from fastapi.security import OAuth2PasswordRequestForm
# Pydantic：定义数据格式
from pydantic import BaseModel, field_validator

# 导入认证核心功能：
# authenticate_user: 验证用户名和密码是否正确
# create_access_token: 生成登录令牌（JWT）
# get_current_active_user: 获取当前登录用户（自动验证令牌）
from app.auth import (
    authenticate_user,
    create_access_token,
    get_current_active_user,
)

# 数据库相关
from app.database import User, db

# 创建路由对象
router = APIRouter()

# ==========================================
# 数据格式定义
# ==========================================

# 登录成功后的返回格式（令牌信息）
class Token(BaseModel):
    access_token: str  # 登录令牌（一串加密字符串）
    token_type: str    # 令牌类型（固定为 "bearer"）

# 用户信息的返回格式
class UserResponse(BaseModel):
    id: int            # 用户 ID
    username: str      # 用户名
    company_id: int | None  # 所属公司 ID（可能为空）
    disabled: bool     # 是否已被禁用

# 用户注册的请求格式
class UserCreate(BaseModel):
    username: str               # 用户名
    password: str               # 密码
    company_id: int | None = None  # 可选：所属公司 ID

    # 密码校验：确保密码至少 8 位
    @field_validator('password')
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        return v

# ==========================================
# API 接口：登录
# ==========================================
# POST /api/token
# 用户输入用户名密码后，获取登录令牌
@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint to get access token"""

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
    # 令牌就像是一张"通行证"，后续请求都需要携带它
    access_token = create_access_token(
        data={"sub": user.username},  # sub = subject，存储用户名
        expires_delta=None  # 使用默认过期时间
    )

    # 返回令牌
    return {"access_token": access_token, "token_type": "bearer"}

# ==========================================
# API 接口：获取当前用户信息
# ==========================================
# GET /api/users/me
# 获取当前登录用户的信息（自动验证令牌）
@router.get("/users/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Get current user information"""

    # Depends(get_current_active_user) 会自动验证令牌
    # 如果令牌无效或过期，会自动返回 401 错误

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        company_id=current_user.company_id,
        disabled=current_user.disabled
    )

# ==========================================
# API 接口：用户注册
# ==========================================
# POST /api/users/register
# 创建新用户账号
@router.post("/users/register", response_model=UserResponse)
async def register_user(user_data: UserCreate):
    """Register a new user"""

    # 第一步：检查用户名是否已存在
    existing_user = db.get_user_by_username(user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # 第二步：如果指定了公司 ID，验证公司是否存在
    if user_data.company_id:
        company = db.get_company(user_data.company_id)
        if not company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company not found"
            )

    # 第三步：密码加密（永远不要存储明文密码！）
    from app.auth import hash_password
    hashed_password = hash_password(user_data.password)

    # 第四步：创建用户记录
    new_user = User(
        username=user_data.username,
        password_hash=hashed_password,  # 存储加密后的密码
        company_id=user_data.company_id,
        disabled=False  # 新用户默认启用
    )

    # 第五步：写入数据库
    user_id = db.create_user(new_user)
    created_user = db.get_user_by_id(user_id)

    # 返回新创建的用户信息
    return UserResponse(
        id=created_user.id,
        username=created_user.username,
        company_id=created_user.company_id,
        disabled=created_user.disabled
    )

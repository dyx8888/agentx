"""
Companies router for AgentX Stage 4
Manages tenant (company) operations
"""


from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.core.permissions import admin_required  # 仅管理员可以创建公司，确保租户管理安全
from app.database import Company, User, db

router = APIRouter()

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

@router.post("/", response_model=CompanyResponse)
async def create_company(
    company_data: CompanyCreate,
    current_user: User = Depends(admin_required)  # 管理员权限：普通用户不能创建公司
):
    """Create a new company (admin only)"""
    # Convert platforms to JSON string for storage
    platforms_json = company_data.platforms  # 前端传入的逗号分隔字符串直接存储

    new_company = Company(
        name=company_data.name,
        brand_name=company_data.brand_name,
        category=company_data.category,
        platforms_json=platforms_json
    )

    company_id = db.create_company(new_company)
    created_company = db.get_company(company_id)  # 创建后重新查询获取完整数据

    if not created_company:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create company"
        )

    return CompanyResponse(
        id=created_company.id,
        name=created_company.name,
        brand_name=created_company.brand_name,
        category=created_company.category,
        platforms_json=created_company.platforms_json,
        created_at=created_company.created_at
    )

@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company_info(
    company_id: int,
    current_user: User = Depends(get_current_active_user)
):
    """Get company information by ID"""
    if not current_user.is_admin and current_user.company_id != company_id:  # 非管理员只能查看自己公司的信息
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot view other company's information"
        )

    company = db.get_company(company_id)

    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    return CompanyResponse(
        id=company.id,
        name=company.name,
        brand_name=company.brand_name,
        category=company.category,
        platforms_json=company.platforms_json,
        created_at=company.created_at
    )

@router.get("/", response_model=list[CompanyResponse])
async def get_companies(
    current_user: User = Depends(get_current_active_user)
):
    """Get companies accessible to current user"""
    if current_user.is_admin:
        company_list = db.get_all_companies()  # 管理员可以看到所有公司
    elif current_user.company_id:
        company = db.get_company(current_user.company_id)
        company_list = [company] if company else []  # 普通用户只能看到自己的公司
    else:
        company_list = []  # 无公司归属的用户看不到任何公司

    return [
        CompanyResponse(
            id=c.id,
            name=c.name,
            brand_name=c.brand_name,
            category=c.category,
            platforms_json=c.platforms_json,
            created_at=c.created_at
        )
        for c in company_list
    ]

@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: int,
    company_data: CompanyCreate,
    current_user: User = Depends(get_current_active_user)
):
    """Update company information"""
    if not current_user.is_admin and current_user.company_id != company_id:  # 权限校验：管理员或同公司用户
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot update other company's information"
        )

    existing_company = db.get_company(company_id)

    if not existing_company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # Update company
    updated_company = Company(
        id=company_id,
        name=company_data.name,
        brand_name=company_data.brand_name,
        category=company_data.category,
        platforms_json=company_data.platforms  # 直接使用前端传入的字符串
    )

    success = db.update_company(company_id, updated_company)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update company"
        )

    # Return updated company
    updated_record = db.get_company(company_id)  # 更新后重新查询

    return CompanyResponse(
        id=updated_record.id,
        name=updated_record.name,
        brand_name=updated_record.brand_name,
        category=updated_record.category,
        platforms_json=updated_record.platforms_json,
        created_at=updated_record.created_at
    )


# Pydantic models for credentials
class PlatformCredentials(BaseModel):
    platform: str  # 平台名称（如 taobao、jd）
    api_key: str
    api_secret: str  # 敏感信息，传输时依赖 HTTPS 加密


@router.post("/{company_id}/credentials")
async def bind_platform_credentials(
    company_id: int,
    credentials: PlatformCredentials,
    current_user: User = Depends(get_current_active_user)
):
    """为公司绑定/更新平台凭证"""
    # 检查公司是否存在
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # 检查权限（管理员或同公司用户）
    if not current_user.is_admin and current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage this company's credentials"
        )

    try:
        import json  # 函数内导入，避免顶层不必要的依赖

        # 获取现有凭证
        existing_credentials = {}
        if company.platform_credentials:
            existing_credentials = json.loads(company.platform_credentials)  # 反序列化已有凭证

        # 更新指定平台的凭证
        existing_credentials[credentials.platform] = {  # 按平台名称做 key，支持多平台凭证共存
            "api_key": credentials.api_key,
            "api_secret": credentials.api_secret
        }

        # 保存更新后的凭证
        updated_credentials_json = json.dumps(existing_credentials)
        success = db.update_company_platform_credentials(company_id, updated_credentials_json)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update platform credentials"
            )

        return {"message": f"Platform credentials for {credentials.platform} updated successfully"}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process credentials: {str(e)}"
        )


@router.delete("/{company_id}/credentials")
async def unbind_platform_credentials(
    company_id: int,
    platform: str,  # 通过查询参数指定要解绑的平台
    current_user: User = Depends(get_current_active_user)
):
    """解绑公司指定平台的凭证"""
    # 检查公司是否存在
    company = db.get_company(company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )

    # 检查权限（管理员或同公司用户）
    if not current_user.is_admin and current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage this company's credentials"
        )

    try:
        import json

        # 获取现有凭证
        existing_credentials = {}
        if company.platform_credentials:
            existing_credentials = json.loads(company.platform_credentials)

        # 移除指定平台的凭证
        if platform in existing_credentials:
            del existing_credentials[platform]  # 安全删除：先检查再删除

            # 保存更新后的凭证
            updated_credentials_json = json.dumps(existing_credentials)
            success = db.update_company_platform_credentials(company_id, updated_credentials_json)

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update platform credentials"
                )

            return {"message": f"Platform credentials for {platform} removed successfully"}
        else:
            return {"message": f"No credentials found for platform {platform}"}  # 平台不存在也返回成功，幂等操作

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process credentials: {str(e)}"
        )

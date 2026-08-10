"""
Permission Management
Provides role-based access control and admin dependencies
"""

from fastapi import Depends, HTTPException, status

from app.auth import get_current_active_user
from app.database import User


def admin_required(current_user: User = Depends(get_current_active_user)):
    """
    Dependency that requires admin privileges
    
    Args:
        current_user: Currently authenticated user
        
    Returns:
        User if admin, raises HTTPException otherwise
        
    Raises:
        HTTPException: If user is not admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user

def company_access_required(current_user: User = Depends(get_current_active_user)):
    """
    Dependency that ensures user has access to their company data
    
    Args:
        current_user: Currently authenticated user
        
    Returns:
        User with company access
        
    Raises:
        HTTPException: If user has no company access
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company access required"
        )
    return current_user

def same_company_access(resource_company_id: int, current_user: User = Depends(get_current_active_user)):
    """
    Dependency that ensures user can only access their own company's resources
    
    Args:
        resource_company_id: Company ID of the resource being accessed
        current_user: Currently authenticated user
        
    Returns:
        User if access is allowed
        
    Raises:
        HTTPException: If user tries to access other company's resources
    """
    if current_user.company_id != resource_company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot access resources from other companies"
        )
    return current_user

def get_user_with_company_access(current_user: User = Depends(get_current_active_user)):
    """
    Combined dependency for user and company access validation
    
    Args:
        current_user: Currently authenticated user
        
    Returns:
        User with validated company access
    """
    return company_access_required(current_user)

def get_admin_with_company_access(current_user: User = Depends(get_current_active_user)):
    """
    Combined dependency for admin and company access validation
    
    Args:
        current_user: Currently authenticated user
        
    Returns:
        Admin user with validated company access
    """
    admin_required(current_user)
    return company_access_required(current_user)

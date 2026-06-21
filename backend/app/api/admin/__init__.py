# 管理员 API 接口模块
# 这个文件的作用是把 admin 文件夹下的所有 API 接口集中导出，方便其他地方统一引用
# 就像是一个"总目录"，告诉大家这个文件夹提供了哪些功能
"""
Admin API endpoints module
"""

# 从 admin.py 文件导入管理员管理相关接口
# router 是 FastAPI 的路由对象，所有 API 接口都注册在这个对象上
from .admin import router as admin_router
# 从 costs.py 文件导入成本管理相关接口
from .costs import router as costs_router

# __all__ 定义了这个模块"对外公开"的内容
# 其他文件用 from app.api.admin import * 时，只会导入 __all__ 中列出的内容
__all__ = ['admin_router', 'costs_router']

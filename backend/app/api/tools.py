"""
Tools router for AgentX Stage 4
Provides tool marketplace endpoints
"""

import os  # 用于构建配置文件路径

import yaml  # 使用 YAML 格式存储工具配置，结构清晰，便于人工编辑
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import get_current_active_user
from app.core.logging import get_logger
from app.database import User

logger = get_logger(__name__)

# Calculate BASE_DIR directly to avoid circular import
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)  # 直接计算路径，避免从 app 模块导入导致循环引用

router = APIRouter()

_TOOL_NAME_ALIASES = {
    "search_kols": "kol_search",
    "kol-search": "kol_search",
}


# Pydantic models
class ToolInfo(BaseModel):
    name: str
    module: str  # 工具所在的 Python 模块
    function: str  # 模块中实现工具功能的函数名
    description: str


@router.get("/", response_model=list[ToolInfo])
async def get_available_tools(
    current_user: User = Depends(get_current_active_user),
):
    """Get all available tools from configuration"""
    tools_config_path = os.path.join(
        BASE_DIR, "config", "tool_providers.yaml"
    )  # 工具配置统一存放在 config 目录

    try:
        with open(tools_config_path, encoding="utf-8") as f:  # utf-8 编码确保中文描述正常显示
            config = yaml.safe_load(f)  # 使用 safe_load 防止 YAML 注入攻击

        tools = config.get("providers", [])  # providers 字段下存放所有工具定义
        return [
            ToolInfo(
                name=tool.get("name", ""),
                module=tool.get("module", ""),
                function=tool.get("function", ""),
                description=tool.get("description", ""),
            )
            for tool in tools
        ]
    except FileNotFoundError:
        return []  # 配置文件不存在时返回空列表，避免 API 崩溃
    except Exception as e:
        # Log error but return empty list to avoid breaking the API
        logger.error("tools_config_load_error", error=str(e))
        return []  # 即使配置解析失败也返回空列表，保证 API 可用性


@router.get("/categories")
async def get_tool_categories(
    current_user: User = Depends(get_current_active_user),
):
    """Get available tool categories"""
    tools = await get_available_tools(current_user)  # 复用工具列表接口，DRY 原则

    # Extract categories from tool descriptions or modules
    categories = set()  # 使用 set 去重
    for tool in tools:
        # Simple categorization based on module name
        if "kol_search" in tool.module:
            categories.add("达人搜索")
        elif "outreach" in tool.module:
            categories.add("商务合作")
        elif "script" in tool.module:
            categories.add("内容创作")
        elif "monitor" in tool.module:
            categories.add("物流监控")
        elif "report" in tool.module:
            categories.add("数据分析")
        elif "agent" in tool.module:
            categories.add("基础工具")
        else:
            categories.add("其他")  # 无法匹配的归入"其他"分类

    return list(categories)


# ── T4.12: 快捷指令能力列表 ─────────────────────────────────────

# capability key → 用户友好中文标签
_CAPABILITY_LABELS = {
    "search": "达人搜索",
    "analysis": "数据分析",
    "content": "内容创作",
    "logistics": "物流查询",
    "advertising": "广告投放",
    "service": "客服支持",
    "design": "视觉设计",
    "knowledge": "知识检索",
}


@router.get("/capabilities")
async def get_tool_capabilities(
    current_user: User = Depends(get_current_active_user),
):
    """返回可用能力列表（供前端快捷指令动态生成）"""
    tools_config_path = os.path.join(BASE_DIR, "config", "tool_providers.yaml")
    try:
        with open(tools_config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        cap_map = config.get("capability_map", {})
        # 取所有能力 key（去重、保持顺序）
        seen = set()
        caps = []
        for key in cap_map:
            if key not in seen and key in _CAPABILITY_LABELS:
                seen.add(key)
                caps.append({"key": key, "label": f"/{_CAPABILITY_LABELS[key]}"})
        # 兜底：配置文件无 capability_map 时返回默认 4 项
        if not caps:
            for k, v in list(_CAPABILITY_LABELS.items())[:4]:
                caps.append({"key": k, "label": f"/{v}"})
        return caps
    except Exception as e:
        logger.error("get_tool_capabilities_failed", error=str(e))
        # 降级返回默认 4 项
        return [{"key": k, "label": f"/{v}"} for k, v in list(_CAPABILITY_LABELS.items())[:4]]


@router.get("/{tool_name}")
async def get_tool_details(
    tool_name: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get detailed information about a specific tool"""
    tools = await get_available_tools(current_user)
    normalized_tool_name = _TOOL_NAME_ALIASES.get(tool_name, tool_name)

    for tool in tools:
        if tool.name == normalized_tool_name:
            return tool  # 找到匹配的工具后直接返回

    from fastapi import HTTPException, status  # 延迟导入，仅在需要时加载

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{tool_name}' not found"
    )

"""
AgentX Agent Registry

All 8 digital employee agent definitions:
- brand_bd: 品牌商务 - KOL marketing & BD
- cc: 内容运营 - Content creation & multi-platform management
- ben: 数据分析 - Data analysis & insights
- amy: 客服专员 - Customer service & relationship management
- warehouse_logistics: 仓储物流 - Warehouse & logistics management
- visual_designer: 视觉设计 - Visual design & AIGC generation
- product_selector: 供应链选品师 - Product selection & supplier evaluation
- smart_ad_delivery: 智能投流专员 - Ad delivery & ROI optimization
"""  # 模块级文档字符串，为外部调用方提供 Agent 注册表概览，方便 IDE 智能提示

import importlib  # 使用 importlib 而非直接 import，实现懒加载——避免启动时一次性加载所有 agent 模块
from typing import Dict, List, Optional  # 类型注解让外部调用方清楚知道入参和返回值结构，减少运行时类型错误

AGENT_REGISTRY: dict[str, dict] = {  # 集中注册表——所有 agent 元数据单点维护，新增 agent 只需在此添加条目
    "master": {
        "module": "app.agents.master",
        "name_display": "主协调器",
        "icon": "🎯",
        "role": "orchestrator",
        "review_level": "auto",
    },
    "brand_bd": {
        "module": "app.agents.brand_bd",  # 用字符串路径而非直接引用，支持懒加载，避免循环导入
        "name_display": "品牌商务",
        "icon": "🤝",
        "role": "bd",  # role 字段用于按角色分组查询，方便前端按业务线筛选 agent
        "review_level": "recommended",  # 审核级别区分关键业务（mandatory=强制人工审核）和常规业务（recommended/auto）
    },
    "content_operation": {
        "module": "app.agents.cc",
        "name_display": "内容运营",
        "icon": "✍️",
        "role": "content",
        "review_level": "recommended",
    },
    "data_analysis": {
        "module": "app.agents.ben",
        "name_display": "数据分析",
        "icon": "📊",
        "role": "analyst",
        "review_level": "auto",  # 数据分析结果可自动放行，因为结果是客观数值而非主观操作
    },
    "customer_service": {
        "module": "app.agents.amy",
        "name_display": "客服专员",
        "icon": "🎧",
        "role": "service",
        "review_level": "mandatory",  # 客服直接面向终端消费者，所有回复必须人工审核，避免品牌风险
    },
    "warehouse_logistics": {
        "module": "app.agents.warehouse_logistics",
        "name_display": "仓储物流",
        "icon": "📦",
        "role": "logistics",
        "review_level": "recommended",
    },
    "visual_designer": {
        "module": "app.agents.visual_designer",
        "name_display": "视觉设计",
        "icon": "🎨",
        "role": "design",
        "review_level": "recommended",
    },
    "product_selector": {
        "module": "app.agents.product_selector",
        "name_display": "供应链选品师",
        "icon": "🔍",
        "role": "product",
        "review_level": "recommended",
    },
    "smart_ad_delivery": {
        "module": "app.agents.smart_ad_delivery",
        "name_display": "智能投流专员",
        "icon": "📈",
        "role": "ad",
        "review_level": "recommended",
    },
    "kol_search": {
        "module": "app.agents.kol_search",
        "name_display": "达人搜索",
        "icon": "🔎",
        "role": "kol",
        "review_level": "auto",
    },
}


def get_agent_definition(agent_key: str) -> dict | None:
    """Get agent module definitions: system prompt, tools, skills"""
    agent_info = AGENT_REGISTRY.get(agent_key)  # 先查注册表避免无意义的 import 尝试
    if not agent_info:
        return None  # 返回 None 而非抛异常，让调用方优雅处理未知 agent key
    try:
        mod = importlib.import_module(agent_info["module"])  # 动态导入——只在需要时才加载对应模块
        return {
            "key": agent_key,
            "display_name": agent_info["name_display"],
            "icon": agent_info["icon"],
            "role": agent_info["role"],
            "review_level": agent_info["review_level"],
            "system_prompt": mod.get_system_prompt(),  # 约定每个 agent 模块必须导出 get_system_prompt 函数
            "default_tools": mod.get_default_tools(),  # 约定接口，统一调用方式
            "default_skills": mod.get_default_skills(),
        }
    except Exception:
        return None  # 吞掉所有异常——单个 agent 加载失败不应影响其他 agent 的可用性


def get_all_agent_keys() -> list[str]:
    return list(AGENT_REGISTRY.keys())


def get_all_agent_definitions() -> dict[str, dict]:
    result = {}
    for key in AGENT_REGISTRY:
        definition = get_agent_definition(key)
        if definition:
            result[key] = definition
    return result


def get_agents_by_role(role: str) -> list[str]:
    return [k for k, v in AGENT_REGISTRY.items() if v.get("role") == role]


def create_agent_execution_context(
    agent_key: str,
    company_id: int,
    task_description: str,
    company_context: dict = None,
) -> dict:
    """Create full execution context for an agent task with engine integration."""
    agent_def = get_agent_definition(agent_key)
    if not agent_def:
        return {}  # 返回空字典而非 None，让调用方统一用 dict 操作，避免空指针

    from app.agents.tools import get_agent_tools  # 延迟导入避免循环依赖——tools 模块会引用 agent 常量

    engine_tools = get_agent_tools(agent_key)

    context = {
        "agent_key": agent_key,
        "company_id": company_id,
        "task_description": task_description,
        "system_prompt": agent_def["system_prompt"],
        "default_skills": agent_def["default_skills"],
        "engine_tools": engine_tools,
        "review_level": agent_def["review_level"],
        "company_context": company_context or {},  # 用 or 而非 if 判断，确保 company_context 始终是 dict
    }

    try:
        from app.rag.company_context_bus import CompanyContextBus  # 延迟导入 RAG 模块——不是所有场景都需要 RAG 上下文
        bus = CompanyContextBus(str(company_id))  # 将 company_id 转为字符串，因为 RAG 索引以字符串为 key
        rag_context = bus.get_context_for_agent(agent_key)
        if rag_context:
            context["rag_context"] = rag_context  # 只在有 RAG 上下文时才注入，避免空字段污染
    except Exception:
        pass  # RAG 服务不可用时不阻塞主流程，Agent 仍可基于 system_prompt 工作

    return context


def load_engine_for_agent(agent_key: str):
    """Lazily load and return the deterministic engine instance for an agent."""
    engine_map = {  # 只有需要确定性引擎的 agent 才映射——brand_bd/cc 这类纯 LLM agent 不需要引擎
        "data_analysis": ("app.engines.metrics_engine", "MetricsEngine"),
        "warehouse_logistics": ("app.engines.warehouse_logistics_engine", "WarehouseLogisticsEngine"),
        "customer_service": ("app.engines.customer_service_engine", "CustomerServiceEngine"),
        "visual_designer": ("app.services.image_pipeline", "ImageGenerationPipeline"),
        "product_selector": ("app.engines.product_scoring", "ProductScoringEngine"),
        "smart_ad_delivery": ("app.engines.ad_delivery_engine", "AdDeliveryEngine"),
    }

    engine_info = engine_map.get(agent_key)
    if not engine_info:
        return None  # 非引擎 agent 返回 None，调用方据此判断是否走纯 LLM 路径

    module_path, class_name = engine_info  # 元组解包，映射关系清晰可读
    try:
        mod = importlib.import_module(module_path)  # 懒加载引擎模块，避免不必要的启动开销
        engine_cls = getattr(mod, class_name)
        if class_name in ("MetricsEngine", "ProductScoringEngine"):  # 无状态引擎直接返回类，不需要实例化
            return engine_cls
        return engine_cls()  # 有状态引擎实例化一次，后续复用
    except Exception:
        return None  # 引擎加载失败不阻塞，降级到纯 LLM 模式


def get_agent_collaboration_rules(agent_key: str) -> dict:
    """Get collaboration rules for an agent (who it can delegate to, who delegates to it)."""
    collab_rules = {  # 协作规则集中定义——避免散布在各 agent 模块中形成隐式耦合
        "brand_bd": {
            "can_delegate_to": ["content_operation", "data_analysis", "product_selector", "visual_designer"],
            "receives_from": ["product_selector", "data_analysis", "warehouse_logistics"],
        },
        "content_operation": {
            "can_delegate_to": ["visual_designer", "data_analysis"],
            "receives_from": ["brand_bd", "product_selector", "smart_ad_delivery"],
        },
        "data_analysis": {  # 数据分析是中枢——几乎所有 agent 都需要它的数据支持
            "can_delegate_to": ["brand_bd", "content_operation", "customer_service", "warehouse_logistics",
                                "product_selector", "smart_ad_delivery", "visual_designer"],
            "receives_from": ["brand_bd", "content_operation", "customer_service", "warehouse_logistics",
                              "product_selector", "smart_ad_delivery", "visual_designer"],
        },
        "customer_service": {
            "can_delegate_to": ["warehouse_logistics", "data_analysis", "product_selector"],
            "receives_from": ["warehouse_logistics", "data_analysis", "smart_ad_delivery"],
        },
        "warehouse_logistics": {
            "can_delegate_to": ["customer_service", "data_analysis", "product_selector", "brand_bd"],
            "receives_from": ["customer_service", "data_analysis", "product_selector"],
        },
        "visual_designer": {
            "can_delegate_to": ["data_analysis"],
            "receives_from": ["brand_bd", "content_operation", "product_selector", "smart_ad_delivery"],
        },
        "product_selector": {
            "can_delegate_to": ["data_analysis", "brand_bd", "content_operation", "warehouse_logistics"],
            "receives_from": ["data_analysis", "warehouse_logistics", "customer_service"],
        },
        "smart_ad_delivery": {
            "can_delegate_to": ["data_analysis", "content_operation", "visual_designer", "brand_bd"],
            "receives_from": ["brand_bd", "product_selector", "data_analysis"],
        },
    }
    return collab_rules.get(agent_key, {"can_delegate_to": [], "receives_from": []})  # 默认空列表确保调用方安全遍历


def get_agent_engine_config(agent_key: str) -> dict:
    """Get engine configuration for an agent including model preferences."""
    configs = {
        "brand_bd": {"preferred_model": "deepseek-chat", "max_tokens": 4096, "temperature": 0.7},
        "content_operation": {"preferred_model": "deepseek-chat", "max_tokens": 8192, "temperature": 0.8},
        "data_analysis": {"preferred_model": "deepseek-chat", "max_tokens": 4096, "temperature": 0.3},
        "customer_service": {"preferred_model": "deepseek-chat", "max_tokens": 2048, "temperature": 0.5},
        "warehouse_logistics": {"preferred_model": "deepseek-chat", "max_tokens": 2048, "temperature": 0.2},
        "visual_designer": {"preferred_model": "deepseek-chat", "max_tokens": 4096, "temperature": 0.9},
        "product_selector": {"preferred_model": "deepseek-chat", "max_tokens": 4096, "temperature": 0.6},
        "smart_ad_delivery": {"preferred_model": "deepseek-chat", "max_tokens": 4096, "temperature": 0.4},
    }
    return configs.get(agent_key, {"preferred_model": "deepseek-chat", "max_tokens": 4096, "temperature": 0.7})

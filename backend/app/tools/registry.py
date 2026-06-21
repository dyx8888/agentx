"""
全局工具注册中心
实现 ToolRegistry 单例，支持 MCP 服务启动时自动注册工具，Agent 通过能力名称动态获取工具集
"""

import importlib
import os
from collections.abc import Callable
from typing import Any

import yaml
from langchain_core.tools import StructuredTool, tool

from app.core.logging import get_logger

logger = get_logger(__name__)

class ToolRegistry:
    """全局工具注册中心单例"""

    _instance = None

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._capability_map = {}
        return cls._instance

    def register(self, name: str, func: Callable, description: str = None, module_path: str = None, endpoint: str = None):
        """
        注册一个工具
        
        Args:
            name: 工具名称
            func: 工具函数或 StructuredTool 实例
            description: 工具描述
            module_path: 模块路径
            endpoint: 端点信息
        """
        # 如果 func 已经是 StructuredTool 实例，直接使用；否则用 @tool 包装
        if isinstance(func, StructuredTool):
            wrapped = func
        else:
            wrapped = tool(func)
            wrapped.name = name

        # 设置描述
        if description:
            wrapped.description = description

        # 存储工具信息
        self._tools[name] = {
            'tool': wrapped,
            'module_path': module_path,
            'endpoint': endpoint
        }

        logger.info("tool_registered", tool_name=name, tool_id=tool_id)

    def register_from_config(self, config_path: str = None):
        """
        从 tool_providers.yaml 配置文件批量注册工具。

        Args:
            config_path: 配置文件路径，默认 tool_providers.yaml
        """
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), '..', '..', 'config', 'tool_providers.yaml'
            )

        try:
            with open(config_path, encoding='utf-8') as f:
                config = yaml.safe_load(f)

            for tool_config in config.get('providers', []):
                try:
                    # 动态导入模块
                    module = importlib.import_module(tool_config['module'])

                    # 获取工具函数
                    func = getattr(module, tool_config['function'])

                    # 注册工具
                    self.register(
                        name=tool_config['name'],
                        func=func,
                        description=tool_config.get('description'),
                        module_path=tool_config['module'],
                        endpoint=tool_config.get('endpoint')
                    )
                except Exception as e:
                    logger.warning("tool_register_config_error", tool_name=tool_config['name'], error=str(e))

        except FileNotFoundError:
            logger.warning("tools_config_not_found", path=config_path)
        except Exception as e:
            logger.error("tools_config_load_error", error=str(e))

    def get_tools_by_names(self, names: list[str]) -> list[Any]:
        """
        根据工具名列表返回工具对象列表
        
        Args:
            names: 工具名称列表
            
        Returns:
            工具对象列表
        """
        tools = []
        for name in names:
            if name in self._tools:
                tools.append(self._tools[name]['tool'])
            else:
                logger.warning("tool_not_found", tool_name=name)
        return tools

    def map_capability_to_tools(self, capability: str, tool_names: list[str]):
        """
        将一个能力名称映射到一组工具名
        
        Args:
            capability: 能力名称
            tool_names: 工具名称列表
        """
        self._capability_map[capability] = tool_names
        logger.info("capability_mapped", capability=capability, tools=tool_names)

    def get_tools_by_capabilities(self, capabilities: list[str]) -> list[Any]:
        """
        根据能力名称列表返回工具对象列表
        
        Args:
            capabilities: 能力名称列表
            
        Returns:
            工具对象列表
        """
        tool_names = set()
        for cap in capabilities:
            if cap in self._capability_map:
                tool_names.update(self._capability_map[cap])

        return self.get_tools_by_names(list(tool_names))

    def list_registered_tools(self) -> list[str]:
        """
        列出所有已注册的工具名
        
        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def get_tool_info(self, name: str) -> dict[str, Any]:
        """
        获取工具详细信息
        
        Args:
            name: 工具名称
            
        Returns:
            工具信息字典
        """
        return self._tools.get(name, {})

    def initialize_from_config(self):
        """
        从配置文件初始化所有工具
        """
        logger.info("tool_registry_initializing_from_config")
        self.register_from_config()

        self.map_capability_to_tools("search", ["search_kols", "search_douyin"])
        self.map_capability_to_tools("analysis", ["analyze_performance", "generate_report"])
        self.map_capability_to_tools("content", ["create_content", "edit_content"])

        logger.info("tool_registry_initialized", tool_count=len(self._tools))

# 创建全局单例实例
registry = ToolRegistry()

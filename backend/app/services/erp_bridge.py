"""
ERPBridge - ERP/WMS adapter for warehouse logistics agent

Integrates with external ERP/WMS systems:
- ExpressBird (kdniao) API for shipment tracking and e-waybill
- Cainiao Logistics API for warehouse dispatch
- Generic ERP sync bridge (Kingdee/Yonyou/Jushuitan)

Implements MCP tool three-level permission control:
  Level 1: Read-only - query inventory, track shipments
  Level 2: Write - create orders, update inventory
  Level 3: External Control - operate external software, print waybills
"""  # 仓储物流Agent的外部ERP/WMS适配层，统一封装多家ERP接口差异

from dataclasses import dataclass, field  # dataclass避免手写大量样板代码，field用于设置可变默认值
from datetime import datetime  # 用于生成时间戳和格式化日期
from enum import StrEnum  # 使用StrEnum而非普通Enum，因为权限等级需要以字符串形式存储和序列化


class MCPPermission(StrEnum):  # MCP三级权限枚举，遵循最小权限原则，防止Agent越权操作
    READ_ONLY = "read_only"  # 只读权限：仅允许查询操作，不产生任何副作用
    WRITE = "write"  # 写入权限：允许创建订单、更新库存等有副作用的操作
    EXTERNAL_CONTROL = "external_control"  # 外部操控权限：最高级别，可操作外部软件和硬件设备


@dataclass  # 使用dataclass而非普通类，因为权限配置对象是纯数据载体，不需要复杂方法
class MCPToolPermission:  # 每个MCP工具的权限配置，用于声明式权限控制而非硬编码在业务逻辑中
    tool_name: str  # 工具名称，作为权限检查的唯一标识
    permission: MCPPermission  # 该工具对应的权限等级
    requires_approval: bool = False  # 默认无需审批，仅外部操控级别的工具需要人工审批
    max_daily_calls: int = 1000  # 每日调用上限，防止滥用和意外超量调用
    audit_log_enabled: bool = True  # 默认开启审计日志，确保所有操作可追溯
    allowed_agents: list[str] = field(default_factory=list)  # 使用field而非直接赋值[]，因为可变默认值会导致所有实例共享同一列表
    description: str = ""  # 工具描述，用于审计日志和权限展示


class ERPBridge:  # ERP/WMS适配器，作为静态方法集合而非实例，因为所有操作都是无状态的适配逻辑
    """ERP/WMS system integration adapter."""

    MCP_PERMISSIONS: dict[str, MCPToolPermission] = {  # 类级别字典，所有实例共享；使用类属性而非实例属性，避免每次创建对象时重复初始化
        "inventory_check": MCPToolPermission(  # 库存查询：最高频操作，允许5000次/天，无需审批
            tool_name="inventory_check",
            permission=MCPPermission.READ_ONLY,
            requires_approval=False,
            max_daily_calls=5000,  # 高于默认值，因为库存查询是高频刚需操作
            allowed_agents=["warehouse_logistics", "product_selector", "customer_service"],  # 多个Agent需要查询库存
            description="查询库存数据",
        ),
        "shipment_tracking": MCPToolPermission(  # 物流追踪：最高频操作，允许10000次/天，因为客户频繁查询物流
            tool_name="shipment_tracking",
            permission=MCPPermission.READ_ONLY,
            requires_approval=False,
            max_daily_calls=10000,  # 物流查询是最频繁的客户需求
            allowed_agents=["warehouse_logistics", "customer_service"],
            description="查询物流轨迹",
        ),
        "order_fulfillment": MCPToolPermission(  # 订单履约：写操作，仅仓储Agent可用，限制2000次/天防止误操作
            tool_name="order_fulfillment",
            permission=MCPPermission.WRITE,
            requires_approval=False,
            max_daily_calls=2000,
            allowed_agents=["warehouse_logistics"],  # 只能由仓储Agent操作，其他Agent不应直接履约
            description="订单履约操作",
        ),
        "warehouse_allocator": MCPToolPermission(  # 仓库分配：写操作，1000次/天，分配逻辑需要仓储专业知识
            tool_name="warehouse_allocator",
            permission=MCPPermission.WRITE,
            requires_approval=False,
            max_daily_calls=1000,
            allowed_agents=["warehouse_logistics"],
            description="仓库分配调度",
        ),
        "erp_sync_bridge": MCPToolPermission(  # ERP同步：外部操控级别，需要人工审批，限制500次/天
            tool_name="erp_sync_bridge",
            permission=MCPPermission.EXTERNAL_CONTROL,  # 最高权限级别，因为涉及外部系统操作
            requires_approval=True,  # 必须人工审批，防止自动同步导致数据错误
            max_daily_calls=500,  # 限制较严格，因为外部系统操作风险高
            allowed_agents=["warehouse_logistics"],
            description="ERP外部系统操作（仅读写/外部操控进行授权流程+操作日志）",
        ),
        "return_logistics_handler": MCPToolPermission(  # 退货处理：写操作，客服和仓储都需要处理退货
            tool_name="return_logistics_handler",
            permission=MCPPermission.WRITE,
            requires_approval=False,
            max_daily_calls=1000,
            allowed_agents=["warehouse_logistics", "customer_service"],
            description="退货物流处理",
        ),
    }

    @staticmethod  # 静态方法，因为权限检查不依赖实例状态，仅基于类级别的MCP_PERMISSIONS字典
    def check_permission(tool_name: str, agent_key: str, operation_type: str = "read") -> dict:  # 默认operation_type为read，符合最小权限原则
        perm = ERPBridge.MCP_PERMISSIONS.get(tool_name)  # 使用.get而非[]，避免KeyError导致未注册工具引发异常
        if not perm:  # 工具未注册时直接拒绝，防止未授权工具被调用
            return {"allowed": False, "reason": f"工具{tool_name}未注册"}

        if perm.allowed_agents and agent_key not in perm.allowed_agents:  # 先检查allowed_agents列表，空列表表示所有Agent可用
            return {"allowed": False, "reason": f"Agent {agent_key} 无权使用工具{tool_name}"}

        if operation_type == "write" and perm.permission == MCPPermission.READ_ONLY:  # 写操作只能在WRITE及以上权限执行
            return {"allowed": False, "reason": f"工具{tool_name}仅支持只读操作"}

        if operation_type == "external_control" and perm.permission != MCPPermission.EXTERNAL_CONTROL:  # 外部操控需要最高权限
            return {"allowed": False, "reason": f"工具{tool_name}不支持外部操控"}

        return {  # 返回权限检查结果，包含requires_approval和audit_log_enabled供调用方使用
            "allowed": True,
            "requires_approval": perm.requires_approval,
            "permission_level": perm.permission,
            "audit_log_enabled": perm.audit_log_enabled,
        }

    @staticmethod  # 静态方法，快递查询不需要任何实例状态
    def query_express(express_no: str, provider: str = "auto") -> dict:  # provider默认auto，由快递鸟API自动识别快递公司
        return {  # 返回模拟数据作为占位，保留完整API响应结构，便于后续接入快递鸟真实API时无缝替换
            "express_no": express_no,
            "provider": provider,
            "status": "in_transit",
            "current_location": "\u5e7f\u5dde\u4e2d\u8f6c\u4e2d\u5fc3",
            "estimated_delivery": str(datetime.now().date()),
            "tracking_details": [
                {"time": datetime.now().isoformat(), "status": "\u5df2\u63fd\u6536", "location": "\u6df1\u5733\u5e02"},
                {"time": datetime.now().isoformat(), "status": "\u5230\u8fbe\u4e2d\u8f6c\u4e2d\u5fc3", "location": "\u5e7f\u5dde\u5e02"},
            ],
            "note": "\u5f85\u5b9e\u9645\u5bf9\u63a5\u5feb\u9012\u9e1fAPI\u540e\u8fd4\u56de\u5b9e\u65f6\u6570\u636e",  # 明确标注这是占位实现，避免误以为已对接真实API
        }

    @staticmethod  # 静态方法，电子面单创建是纯函数式操作
    def create_ewaybill(order_id: str, sender: dict, receiver: dict,
                          package_info: dict, provider: str = "zhongtong") -> dict:  # 默认中通快递，因为中通覆盖面广且价格适中
        return {  # 返回模拟数据，保留快递鸟电子面单API的标准响应格式
            "success": True,
            "order_id": order_id,
            "ewaybill_no": f"SF{int(datetime.now().timestamp())}",  # 使用时间戳生成唯一运单号，避免与真实运单号冲突
            "provider": provider,
            "print_url": "",
            "note": "\u5f85\u5bf9\u63a5\u5feb\u9012\u9e1f\u7535\u5b50\u9762\u5355API",
        }

    @staticmethod  # 静态方法，ERP同步是纯数据转换操作
    def sync_erp(entity_type: str, entity_id: str, data: dict,
                  erp_system: str = "jushuitan") -> dict:  # 默认聚水潭，因为它是电商ERP常用方案
        supported_erps = ["jushuitan", "kingdee", "yonyou", "wangdiantong"]  # 白名单验证，防止传入不支持的ERP系统
        if erp_system not in supported_erps:  # 先验证再执行，防止无效请求进入后续处理
            return {"success": False, "error": f"ERP系统{erp_system}不支持，支持: {supported_erps}"}

        return {  # 返回模拟数据，保留各ERP厂商的通用响应格式
            "success": True,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "erp_system": erp_system,
            "synced_fields": list(data.keys()),  # 仅记录同步了哪些字段，不暴露实际数据内容
            "note": "待对接实际ERP API",
        }

    @staticmethod  # 静态方法，审计日志记录不依赖实例状态
    def audit_log(agent_key: str, tool_name: str, action: str,
                   company_id: str, details: dict = None) -> dict:  # details可选，允许记录简单操作
        log_entry = {  # 构建日志条目，包含审计所需的所有关键字段
            "timestamp": datetime.now().isoformat(),  # ISO格式时间戳，便于跨系统解析和排序
            "agent": agent_key,
            "tool": tool_name,
            "action": action,
            "company_id": company_id,
            "details": details or {},  # 使用or而非if not，避免None值导致序列化问题
        }
        return log_entry  # 当前仅返回日志对象，待集成日志持久化后写入数据库

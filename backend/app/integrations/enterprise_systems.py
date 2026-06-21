"""
Enterprise System Integrations (ERP / WMS / 客服系统)
通过 MCP 协议对接外部企业系统，提供工具桩供 Agent 调用
"""

from abc import ABC, abstractmethod

from app.core.logging import get_logger

logger = get_logger(__name__)


class ERPIntegration(ABC):
    """ERP 系统集成（企业资源计划: 进销存、财务）"""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def get_inventory(self, sku: str = None, warehouse: str = None) -> list[dict]:
        """获取库存信息"""
        ...

    @abstractmethod
    def get_purchase_orders(self, status: str = None, limit: int = 20) -> list[dict]:
        """获取采购单"""
        ...

    @abstractmethod
    def create_purchase_order(self, supplier: str, items: list[dict]) -> dict:
        """创建采购单"""
        ...

    @abstractmethod
    def get_suppliers(self, category: str = None) -> list[dict]:
        """获取供应商列表"""
        ...


class WMSIntegration(ABC):
    """WMS 系统集成（仓储管理: 入库、出库、盘点、库位）"""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def get_warehouse_list(self) -> list[dict]:
        """仓库列表"""
        ...

    @abstractmethod
    def get_stock_detail(self, warehouse_id: str, sku: str = None) -> list[dict]:
        """库存明细（含库位）"""
        ...

    @abstractmethod
    def create_outbound_order(self, order_id: str, warehouse_id: str,
                                items: list[dict]) -> dict:
        """创建出库单"""
        ...

    @abstractmethod
    def get_picking_list(self, warehouse_id: str = None) -> list[dict]:
        """待拣货列表"""
        ...

    @abstractmethod
    def get_inventory_alerts(self, warehouse_id: str = None) -> list[dict]:
        """库存预警"""
        ...


class MockERPIntegration(ERPIntegration):

    def is_available(self) -> bool:
        return True

    def get_inventory(self, sku: str = None, warehouse: str = None) -> list[dict]:
        logger.info("erp_mock_get_inventory", sku=sku)
        items = [
            {"sku": "SKU001", "name": "商品A", "stock": 350, "warehouse": "北京仓"},
            {"sku": "SKU002", "name": "商品B", "stock": 120, "warehouse": "北京仓"},
            {"sku": "SKU003", "name": "商品C", "stock": 8, "warehouse": "上海仓"},
        ]
        if sku:
            items = [i for i in items if i["sku"] == sku]
        return items

    def get_purchase_orders(self, status: str = None, limit: int = 20) -> list[dict]:
        return [
            {"po_id": "PO20260501", "supplier": "供应商A", "total": 12500.00,
             "status": "待入库", "items": 15},
            {"po_id": "PO20260502", "supplier": "供应商B", "total": 8900.00,
             "status": "已完成", "items": 8},
        ]

    def create_purchase_order(self, supplier: str, items: list[dict]) -> dict:
        logger.info("erp_mock_create_po", supplier=supplier, items_count=len(items))
        return {"po_id": f"PO{hash(str(items)) % 10000:05d}", "status": "待审核",
                "supplier": supplier, "items": len(items)}

    def get_suppliers(self, category: str = None) -> list[dict]:
        return [
            {"id": "SUP001", "name": "优质供应商A", "rating": 4.8, "category": "美妆"},
            {"id": "SUP002", "name": "优质供应商B", "rating": 4.5, "category": "食品"},
            {"id": "SUP003", "name": "普通供应商C", "rating": 3.9, "category": "日用品"},
        ]


class MockWMSIntegration(WMSIntegration):

    def is_available(self) -> bool:
        return True

    def get_warehouse_list(self) -> list[dict]:
        return [
            {"id": "WH001", "name": "北京顺义仓", "address": "北京市顺义区", "capacity": 5000},
            {"id": "WH002", "name": "上海松江仓", "address": "上海市松江区", "capacity": 3500},
        ]

    def get_stock_detail(self, warehouse_id: str, sku: str = None) -> list[dict]:
        return [
            {"sku": "SKU001", "location": "A-01-03", "stock": 200, "status": "正常"},
            {"sku": "SKU001", "location": "B-02-05", "stock": 150, "status": "正常"},
            {"sku": "SKU002", "location": "A-03-01", "stock": 120, "status": "正常"},
            {"sku": "SKU003", "location": "C-01-02", "stock": 8, "status": "低于安全库存"},
        ]

    def create_outbound_order(self, order_id: str, warehouse_id: str,
                                items: list[dict]) -> dict:
        logger.info("wms_mock_create_outbound", order=order_id)
        return {"outbound_id": f"OUT{hash(order_id) % 100000:05d}",
                "status": "待拣货", "warehouse": warehouse_id}

    def get_picking_list(self, warehouse_id: str = None) -> list[dict]:
        return [
            {"outbound_id": "OUT00001", "order_id": "ORD001", "items": 3,
             "warehouse": "WH001", "priority": "高", "sla_hours": 4},
            {"outbound_id": "OUT00002", "order_id": "ORD002", "items": 1,
             "warehouse": "WH001", "priority": "普通", "sla_hours": 24},
        ]

    def get_inventory_alerts(self, warehouse_id: str = None) -> list[dict]:
        return [
            {"sku": "SKU003", "current": 8, "safe": 50, "alert": "紧急性库存不足",
             "warehouse": "WH001"},
            {"sku": "SKU012", "current": 15, "safe": 30, "alert": "库存预警",
             "warehouse": "WH002"},
        ]


class CustomerServiceIntegration(ABC):
    """客服系统集成（旺旺 / 飞鸽 / 企业微信 / 抖音客服）"""

    @abstractmethod
    def get_unread_messages(self, platform: str = None, limit: int = 20) -> list[dict]: ...
    @abstractmethod
    def send_reply(self, conversation_id: str, content: str,
                     auto_send: bool = False) -> dict: ...
    @abstractmethod
    def get_customer_profile(self, customer_id: str) -> dict: ...


class MockCustomerServiceIntegration(CustomerServiceIntegration):

    def get_unread_messages(self, platform: str = None, limit: int = 20) -> list[dict]:
        return [
            {"conv_id": "CONV001", "customer": "王女士", "platform": "douyin",
             "message": "这个裙子有XL码吗？", "time": "10:30", "emotion": "neutral"},
            {"conv_id": "CONV002", "customer": "刘先生", "platform": "taobao",
             "message": "发货太慢了，已经3天了！", "time": "10:25", "emotion": "angry"},
            {"conv_id": "CONV003", "customer": "赵小姐", "platform": "xiaohongshu",
             "message": "收到货了很喜欢，想问下有没有优惠？", "time": "10:15", "emotion": "happy"},
        ]

    def send_reply(self, conversation_id: str, content: str,
                     auto_send: bool = False) -> dict:
        logger.info("cs_mock_send_reply", conv=conversation_id, auto=auto_send)
        return {"conv_id": conversation_id, "status": "sent",
                "method": "auto" if auto_send else "pending_review"}

    def get_customer_profile(self, customer_id: str) -> dict:
        return {
            "customer_id": customer_id,
            "name": "王女士",
            "level": "VIP",
            "total_orders": 15,
            "total_spent": 3200.00,
            "avg_response_time": "2h",
            "tags": ["高价值", "复购率高", "偏好美妆"],
        }


erp_integration = MockERPIntegration()
wms_integration = MockWMSIntegration()
cs_integration = MockCustomerServiceIntegration()

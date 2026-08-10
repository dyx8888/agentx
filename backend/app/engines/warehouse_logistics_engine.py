"""
仓储物流执行引擎 - 库存预警/效期管理/智能分配
"""  # 仓储物流引擎：纯规则驱动的库存监控、效期检查、出库处理和物流追踪

from dataclasses import dataclass  # 使用dataclass定义库存物品数据模型
from datetime import datetime  # 用于效期计算和时间戳

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)


@dataclass
class InventoryItem:  # 库存物品数据模型，包含销售和补货相关信息
    sku: str  # 商品SKU编码
    name: str  # 商品名称
    stock: int  # 当前库存数量
    avg_daily_sales_7d: float  # 近7天日均销量，用于短期趋势判断
    avg_daily_sales_30d: float  # 近30天日均销量，用于滞销判断
    replenishment_days: int = 7  # 补货周期（天），默认7天
    safety_stock: int = 0  # 安全库存，0表示自动计算
    expiry_date: str = None  # 效期截止日期（可选）
    warehouse_id: str = "WH001"  # 仓库编号，默认主仓

    def __post_init__(self):  # dataclass初始化后自动计算安全库存
        if self.safety_stock == 0:  # 未指定安全库存时，按日均销量×补货周期自动计算
            self.safety_stock = int(self.avg_daily_sales_7d * self.replenishment_days)  # 使用7天销量因为更贴近近期趋势


class WarehouseLogisticsEngine:
    """仓储物流执行引擎"""  # 核心引擎：库存预警 + 效期管理 + 出库处理 + 物流追踪

    def __init__(self):
        self._inventory: dict[str, InventoryItem] = {}  # SKU→库存物品映射，O(1)查找
        self._alerts: list[dict] = []  # 预警历史记录
        self._picking_queue: list[dict] = []  # 拣货排队队列
        logger.info("warehouse_logistics_engine_initialized")

    def register_inventory(self, item: InventoryItem):  # 注册库存物品到监控系统
        self._inventory[item.sku] = item

    async def check_all_inventory(self, company_id: int) -> list[dict]:  # 遍历所有库存，逐项检查并生成告警
        alerts = []
        from app.communication.collaboration import collaboration_engine  # 延迟导入避免循环依赖

        for _sku, item in self._inventory.items():  # 使用_sku前缀表示该变量未使用
            alert = self._check_item(item)  # 检查单个物品
            if alert:
                alerts.append(alert)
                self._alerts.append(alert)  # 持久化告警记录

                severity = "critical" if "缺货" in alert["type"] else "warning"  # 缺货用critical，其他用warning
                await collaboration_engine.create_alert(  # 创建协作告警通知
                    company_id=company_id,
                    alert_type="warehouse_inventory",
                    title=f"库存预警 - {item.name}",
                    message=f"{alert['type']}: {alert['message']}",
                    severity=severity,
                    related_agents=["warehouse_logistics", "brand_bd"],  # 通知仓储和品牌BD
                )

        return alerts

    def _check_item(self, item: InventoryItem) -> dict | None:  # 多维度库存检查：缺货→滞销→效期→安全库存，按优先级返回第一个告警
        if item.stock < item.avg_daily_sales_7d * 2:  # 库存不足2天销量，判定为爆款缺货（最高优先级）
            return {
                "sku": item.sku,
                "name": item.name,
                "type": "爆款缺货预警",
                "message": f"{item.name} 库存({item.stock})低于3天销量({item.avg_daily_sales_7d*2:.0f})",
                "severity": "critical",  # 缺货是最严重的告警
                "suggested_replenishment": int(item.safety_stock * 1.5),  # 建议补货量为安全库存的1.5倍
            }

        if item.stock > item.avg_daily_sales_30d * 2:  # 库存超过30天销量2倍，滞销积压风险
            return {
                "sku": item.sku,
                "name": item.name,
                "type": "滞销预警",
                "message": f"{item.name} 库存({item.stock})积压，超出30天销量({item.avg_daily_sales_30d*2:.0f})",
                "severity": "warning",
                "suggestion": "建议促销或清仓",
            }

        if item.expiry_date:  # 检查效期，临期商品需优先出库
            try:
                expiry = datetime.strptime(item.expiry_date, "%Y-%m-%d")  # 解析效期日期
                days_left = (expiry - datetime.now()).days  # 计算剩余天数
                if days_left <= 30:  # 30天内到期，需要预警
                    return {
                        "sku": item.sku,
                        "name": item.name,
                        "type": "效期预警",
                        "message": f"{item.name} 剩余效期{days_left}天，建议优先出库",
                        "severity": "critical" if days_left <= 15 else "warning",  # 15天内更紧急
                    }
            except Exception:  # 日期格式异常静默跳过，不中断检查流程
                pass

        if item.stock <= item.safety_stock:  # 库存触达安全线（最低优先级，因为前面已检查更严重的情况）
            return {
                "sku": item.sku,
                "name": item.name,
                "type": "安全库存预警",
                "message": f"{item.name} 库存({item.stock})低于安全库存线({item.safety_stock})",
                "severity": "warning",
                "suggested_replenishment": int(item.safety_stock * 1.3 - item.stock),  # 补充到安全库存的1.3倍
            }

        return None  # 库存正常，无需告警

    async def process_outbound(self, order_id: str, items: list[dict],  # 处理出库订单：调用WMS系统+记录拣货队列
                                 warehouse_id: str, company_id: int) -> dict:
        from app.integrations.enterprise_systems import wms_integration  # 延迟导入WMS集成模块

        result = wms_integration.create_outbound_order(order_id, warehouse_id, items)  # 调用WMS创建出库单
        self._picking_queue.append({  # 记录到拣货队列用于追踪
            "outbound_id": result["outbound_id"],
            "order_id": order_id,
            "warehouse": warehouse_id,
            "items": len(items),
            "created": datetime.utcnow().isoformat(),  # UTC时间避免时区歧义
        })

        logger.info("warehouse_outbound_created", order=order_id,
                    outbound=result["outbound_id"])
        return result

    async def get_picking_tasks(self, warehouse_id: str = None) -> list[dict]:  # 获取拣货任务列表
        from app.integrations.enterprise_systems import wms_integration  # 延迟导入
        return wms_integration.get_picking_list(warehouse_id)

    async def get_logistics_tracking(self, order_id: str) -> dict:  # 获取物流追踪信息
        try:
            from app.platforms import get_platform_adapter  # 延迟导入平台适配器
            adapter = get_platform_adapter("douyin_shop")  # 默认获取抖音店铺适配器
            if adapter:
                return adapter.get_logistics_info(order_id)  # 通过平台适配器查询物流
        except Exception as e:
            logger.warning("logistics_tracking_failed", order=order_id, error=str(e))
        return {"order_id": order_id, "status": "查询中", "error": "暂时无法获取物流信息"}  # 查询失败时返回友好提示

    def get_inventory_summary(self) -> dict:  # 获取库存汇总信息，用于仪表盘展示
        total_sku = len(self._inventory)  # SKU总数
        total_stock = sum(i.stock for i in self._inventory.values())  # 总库存量
        low_stock = sum(1 for i in self._inventory.values()
                        if i.stock <= i.safety_stock)  # 低库存SKU数量
        active_alerts = len(self._alerts)  # 活跃告警数

        return {
            "total_sku": total_sku,
            "total_stock": total_stock,
            "low_stock_items": low_stock,
            "active_alerts": active_alerts,
            "items": [  # 只返回前10条，避免数据量过大
                {"sku": i.sku, "name": i.name, "stock": i.stock,
                 "safety_stock": i.safety_stock}
                for i in list(self._inventory.values())[:10]  # 截取前10个
            ],
        }

    def get_alerts(self, resolved: bool = False, limit: int = 20) -> list[dict]:  # 获取最近的告警记录
        return self._alerts[-limit:]  # 切片取最新记录


wl_engine = WarehouseLogisticsEngine()  # 全局单例，确保库存状态一致

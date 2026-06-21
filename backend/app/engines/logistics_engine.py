"""
LogisticsEngine - Deterministic warehouse and logistics engine
Zero LLM dependency, pure computation.
"""  # 纯计算物流引擎：库存监控、发货追踪、异常检测、包装推荐，所有逻辑均通过规则/公式完成

from dataclasses import dataclass, field  # 数据模型定义
from datetime import datetime, timedelta  # 时间计算：效期检查、发货超时判断
from enum import StrEnum  # 字符串枚举


class InventoryStatus(StrEnum):  # 库存状态枚举
    NORMAL = "normal"  # 正常
    WARNING = "warning"  # 低于安全库存
    STOCKOUT = "stockout"  # 缺货
    OVERSTOCK = "overstock"  # 滞销积压
    EXPIRING = "expiring"  # 临期


class ShipmentStatus(StrEnum):  # 发货状态枚举，覆盖从待发货到退货的完整生命周期
    PENDING = "pending"  # 待发货
    PICKED = "picked"  # 已拣货
    PACKED = "packed"  # 已打包
    SHIPPED = "shipped"  # 已发出
    IN_TRANSIT = "in_transit"  # 运输中
    DELIVERED = "delivered"  # 已签收
    RETURNED = "returned"  # 已退货
    EXCEPTION = "exception"  # 异常


class AlertSeverity(StrEnum):  # 告警严重程度，四级递进
    INFO = "info"  # 信息
    YELLOW = "yellow"  # 黄色：需关注
    ORANGE = "orange"  # 橙色：较严重
    RED = "red"  # 红色：最严重


@dataclass
class InventoryItem:  # 库存物品数据模型
    sku: str  # SKU编码
    product_name: str  # 商品名称
    current_stock: int  # 当前库存
    safety_stock: int  # 安全库存线
    daily_avg_sales: float  # 日均销量
    replenishment_lead_days: int = 7  # 补货提前期（天）
    expiry_date: str = ""  # 效期日期（可选）
    warehouse_location: str = ""  # 仓库位置


@dataclass
class LogisticsAlert:  # 物流告警数据模型
    alert_type: str  # 告警类型（shipment_timeout/logistics_stalled等）
    severity: AlertSeverity  # 严重程度
    title: str  # 告警标题
    description: str  # 详细描述
    sku_or_order: str  # 关联的SKU或订单号
    suggested_action: str  # 建议操作
    notify_agents: list[str] = field(default_factory=list)  # 需要通知的Agent列表


class LogisticsEngine:
    """Deterministic engine for warehouse logistics operations."""  # 物流引擎：全部静态方法，无状态，线程安全

    EXPRESS_PROVIDERS: dict[str, dict] = {  # 快递公司配置表，包含平均配送天数用于时效估算
        "shunfeng": {"name": "\u987a\u4e30\u901f\u8fd0", "code": "SF", "avg_delivery_days": 1.5},  # 顺丰最快
        "zhongtong": {"name": "\u4e2d\u901a\u5feb\u9012", "code": "ZTO", "avg_delivery_days": 2.5},
        "yuantong": {"name": "\u5706\u901a\u5feb\u9012", "code": "YTO", "avg_delivery_days": 2.5},
        "yunda": {"name": "\u97f5\u8fbe\u5feb\u9012", "code": "YD", "avg_delivery_days": 2.5},
        "shentong": {"name": "\u7533\u901a\u5feb\u9012", "code": "STO", "avg_delivery_days": 2.5},
        "jitu": {"name": "\u6781\u5154\u901f\u9012", "code": "JTO", "avg_delivery_days": 2.0},  # 极兔稍快
        "cainiao": {"name": "\u83dc\u9e1f\u7269\u6d41", "code": "CAINIAO", "avg_delivery_days": 2.0},
    }

    @staticmethod
    def calculate_safety_stock(daily_avg_sales: float, lead_days: int, safety_factor: float = 1.5) -> int:  # 安全库存=日均销量×提前期×安全系数
        return max(1, int(daily_avg_sales * lead_days * safety_factor))  # 至少为1，避免零库存场景

    @staticmethod
    def check_inventory_status(  # 多维度库存状态检查，按优先级：效期→缺货→低库存→滞销
        item: InventoryItem,
        recent_30d_sales: float = 0.0,
    ) -> tuple[InventoryStatus, str, list[str]]:
        notify = []  # 需要通知的Agent列表
        reason = ""

        if item.expiry_date:  # 效期检查优先级最高，临期商品需立即处理
            try:
                expiry = datetime.strptime(item.expiry_date, "%Y-%m-%d").date()  # 解析效期日期
                days_until_expiry = (expiry - datetime.now().date()).days  # 计算剩余天数
                if days_until_expiry <= 30:  # 30天内到期则告警
                    notify.append("warehouse_logistics")
                    notify.append("product_selector")  # 通知选品Agent优先出库
                    return InventoryStatus.EXPIRING, f"\u4e34\u671f{days_until_expiry}\u5929\uff0c\u9700\u4f18\u5148\u51fa\u5e93", notify
            except (ValueError, TypeError):  # 日期格式无效时静默跳过
                pass

        if item.current_stock <= 0:  # 缺货是最紧急的情况
            notify.extend(["warehouse_logistics", "product_selector", "customer_service"])  # 通知仓储+选品+客服
            return InventoryStatus.STOCKOUT, "\u5e93\u5b58\u4e3a0\uff0c\u7acb\u5373\u8865\u8d27", notify

        if item.current_stock < item.safety_stock:  # 低于安全库存线
            notify.append("warehouse_logistics")
            notify.append("product_selector")
            reason = f"\u5e93\u5b58{item.current_stock}\u4f4e\u4e8e\u5b89\u5168\u7ebf{item.safety_stock}"
            return InventoryStatus.WARNING, reason, notify

        if recent_30d_sales > 0 and item.current_stock > recent_30d_sales * 2:  # 库存超过30天销量2倍→滞销
            notify.append("warehouse_logistics")
            notify.append("brand_bd")  # 通知品牌BD考虑促销
            reason = f"\u5e93\u5b58{item.current_stock}\u8d85\u8fc730\u5929\u9500\u91cf{recent_30d_sales}\u7684\u4e24\u500d\uff0c\u6ede\u9500\u98ce\u9669"
            return InventoryStatus.OVERSTOCK, reason, notify

        return InventoryStatus.NORMAL, "\u5e93\u5b58\u6b63\u5e38", []  # 一切正常

    @staticmethod
    def calculate_replenishment_quantity(  # 计算建议补货量：目标库存 = 日均销量 × (提前期 + 订货周期)
        daily_avg_sales: float,
        current_stock: int,
        safety_stock: int,
        lead_days: int,
        order_cycle_days: int = 7,
    ) -> int:
        target_stock = int(daily_avg_sales * (lead_days + order_cycle_days))  # 目标库存覆盖补货期间+下一个订货周期的需求
        shortage = max(0, target_stock + safety_stock - current_stock)  # 缺口 = 目标 + 安全库存 - 当前库存，至少为0
        return shortage

    @staticmethod
    def detect_shipment_exception(  # 检测发货异常：待发货超时→物流中断→签收确认
        order_id: str,
        status: ShipmentStatus,
        status_timestamp: datetime,
        provider: str = "",
    ) -> LogisticsAlert | None:
        now = datetime.now()
        hours_since = (now - status_timestamp).total_seconds() / 3600  # 计算状态持续时长（小时）

        LogisticsEngine.EXPRESS_PROVIDERS.get(provider, {})  # 获取快递商信息（此处仅查询不存储，用于后续扩展）

        if status == ShipmentStatus.PENDING and hours_since > 24:  # 待发货超过24小时→超时告警
            return LogisticsAlert(
                alert_type="shipment_timeout",
                severity=AlertSeverity.ORANGE,  # 橙色：较严重但非紧急
                title="\u53d1\u8d27\u8d85\u65f6\u8b66\u544a",
                description=f"\u8ba2\u5355{order_id}\u5df2\u8d85\u8fc724\u5c0f\u65f6\u672a\u53d1\u8d27",
                sku_or_order=order_id,
                suggested_action="\u5080\u4fc3\u4ed3\u50a8\u7acb\u5373\u53d1\u8d27\uff0c\u901a\u77e5\u5ba2\u670d\u8054\u7cfb\u5ba2\u6237",
                notify_agents=["warehouse_logistics", "customer_service"],
            )

        if status in (ShipmentStatus.SHIPPED, ShipmentStatus.IN_TRANSIT) and hours_since > 48:  # 已发货但48h无更新→物流中断
            return LogisticsAlert(
                alert_type="logistics_stalled",
                severity=AlertSeverity.ORANGE,
                title="\u7269\u6d41\u4e2d\u65ad\u8b66\u544a",
                description=f"\u8ba2\u5355{order_id}\u5feb\u9012\u8d85\u8fc748\u5c0f\u65f6\u672a\u66f4\u65b0",
                sku_or_order=order_id,
                suggested_action="\u8054\u7cfb\u5feb\u9012\u7f51\u70b9\u786e\u8ba4\u72b6\u6001\uff0c\u901a\u77e5\u5ba2\u670d\u4e3b\u52a8\u8054\u7cfb\u5ba2\u6237",
                notify_agents=["warehouse_logistics", "customer_service"],
            )

        if status == ShipmentStatus.DELIVERED and hours_since > 72:  # 已签收72h后确认收货体验
            return LogisticsAlert(
                alert_type="sign_conflict",
                severity=AlertSeverity.YELLOW,  # 黄色：仅提醒
                title="\u7b7e\u6536\u786e\u8ba4\u63d0\u9192",
                description=f"\u8ba2\u5355{order_id}\u5df2\u7b7e\u6536\u8d85\u8fc772\u5c0f\u65f6\uff0c\u5efa\u8bae\u786e\u8ba4\u5ba2\u6237\u662f\u5426\u6536\u5230",
                sku_or_order=order_id,
                suggested_action="\u53d1\u9001\u786e\u8ba4\u6536\u8d27\u6d88\u606f\uff0c\u5f15\u5bfc\u597d\u8bc4",
                notify_agents=["customer_service"],
            )

        return None  # 无异常

    @staticmethod
    def recommend_packaging(  # 根据产品重量和体积推荐合适的包装方案
        product_weight_kg: float,
        product_volume_cm3: float,
        is_fragile: bool = False,
    ) -> dict:
        packages = [  # 预定义包装规格表，按从小到大排列
            {"type": "\u7eb8\u7bb1", "min_weight": 0, "max_weight": 3, "min_volume": 0, "max_volume": 27000,
             "size": "30x20x15cm", "cost_estimate": 1.5},
            {"type": "\u7eb8\u7bb1", "min_weight": 0, "max_weight": 5, "min_volume": 0, "max_volume": 54000,
             "size": "40x30x25cm", "cost_estimate": 2.5},
            {"type": "\u7eb8\u7bb1", "min_weight": 0, "max_weight": 10, "min_volume": 0, "max_volume": 108000,
             "size": "50x40x35cm", "cost_estimate": 3.5},
            {"type": "\u5851\u6599\u888b", "min_weight": 0, "max_weight": 1, "min_volume": 0, "max_volume": 6000,
             "size": "30x20cm", "cost_estimate": 0.5},  # 轻小物品用塑料袋
            {"type": "\u6ce1\u6cab\u7bb1", "min_weight": 0, "max_weight": 5, "min_volume": 0, "max_volume": 36000,
             "size": "35x25x20cm", "cost_estimate": 2.0, "insulated": True},  # 保温泡沫箱
        ]

        for pkg in packages:  # 遍历包装规格找到第一个合适的
            if (pkg["min_weight"] <= product_weight_kg <= pkg["max_weight"]
                    and pkg["min_volume"] <= product_volume_cm3 <= pkg["max_volume"]):
                result = dict(pkg)
                if is_fragile:  # 易碎品增加50%缓冲成本
                    result["cost_estimate"] = round(result["cost_estimate"] * 1.5, 2)
                    result["note"] = "\u5efa\u8bae\u589e\u52a0\u6c14\u6ce1\u819c/\u73cd\u73e0\u68c9\u7f13\u51b2\u5305\u88c5"
                return result

        return {  # 超出所有规格时返回定制方案
            "type": "\u5b9a\u5236\u5305\u88c5",
            "size": "\u9700\u5b9a\u5236",
            "cost_estimate": 5.0,
            "note": "\u4ea7\u54c1\u8d85\u51fa\u6807\u51c6\u5305\u88c5\u89c4\u683c\uff0c\u9700\u5b9a\u5236\u5305\u88c5\u65b9\u6848",
        }

    @staticmethod
    def calculate_delivery_estimate(  # 根据始发地和目的地估算配送时效
        origin_province: str,
        dest_province: str,
        provider: str = "zhongtong",  # 默认中通
    ) -> dict:
        same_province = origin_province == dest_province  # 同省配送
        adjacent_map = {  # 广东省的邻省映射，用于判断相邻区域
            "\u5e7f\u4e1c": ["\u5e7f\u4e1c", "\u5e7f\u4e1c", "\u798f\u5efa", "\u6c5f\u897f", "\u6e56\u5357", "\u6d77\u5357", "\u5e7f\u4e1c"],
        }

        if same_province:  # 同省1天
            base_days = 1
            zone = "same_province"
        elif dest_province in adjacent_map.get(origin_province, []):  # 邻省2天
            base_days = 2
            zone = "adjacent"
        else:  # 跨省3天
            base_days = 3
            zone = "cross_province"

        provider_info = LogisticsEngine.EXPRESS_PROVIDERS.get(provider, LogisticsEngine.EXPRESS_PROVIDERS["zhongtong"])  # 获取快递商信息
        provider_factor = provider_info.get("avg_delivery_days", 2.5) / 2.5  # 快递商速度系数（以中通2.5天为基准）

        estimated_days = round(base_days * provider_factor, 1)  # 最终估算天数

        return {
            "provider": provider_info.get("name", provider),
            "origin": origin_province,
            "destination": dest_province,
            "zone": zone,
            "estimated_days_min": max(1, estimated_days - 0.5),  # 最早到货
            "estimated_days_max": estimated_days + 1,  # 最晚到货
            "estimated_delivery_date": str(datetime.now().date() + timedelta(days=int(estimated_days))),  # 预计送达日期
        }

    @staticmethod
    def generate_inventory_report(items: list[InventoryItem], recent_30d_sales_map: dict[str, float] = None) -> dict:  # 生成库存汇总报告
        if recent_30d_sales_map is None:  # 未提供时使用空字典，避免可变默认参数陷阱
            recent_30d_sales_map = {}

        report = {  # 初始化报告结构
            "generated_at": datetime.now().isoformat(),
            "total_skus": len(items),
            "status_summary": {s.value: 0 for s in InventoryStatus},  # 各状态SKU计数
            "items": [],
            "alerts": [],
            "replenishment_suggestions": [],
        }

        for item in items:  # 遍历所有商品
            recent_sales = recent_30d_sales_map.get(item.sku, 0.0)  # 获取该SKU的30天销量
            status, reason, notify = LogisticsEngine.check_inventory_status(item, recent_sales)  # 检查库存状态
            report["status_summary"][status.value] += 1  # 累加状态计数

            item_report = {
                "sku": item.sku,
                "name": item.product_name,
                "stock": item.current_stock,
                "safety_stock": item.safety_stock,
                "status": status.value,
                "reason": reason,
            }

            if status != InventoryStatus.NORMAL:  # 非正常状态才计算补货建议
                replenish_qty = LogisticsEngine.calculate_replenishment_quantity(
                    item.daily_avg_sales, item.current_stock, item.safety_stock, item.replenishment_lead_days
                )
                item_report["suggested_replenishment"] = replenish_qty

                alert = LogisticsAlert(  # 构建告警对象
                    alert_type=f"inventory_{status.value}",
                    severity=AlertSeverity.RED if status == InventoryStatus.STOCKOUT else AlertSeverity.ORANGE,  # 缺货用红色
                    title=f"\u5e93\u5b58\u5f02\u5e38: {item.product_name}",
                    description=reason,
                    sku_or_order=item.sku,
                    suggested_action=f"\u5efa\u8bae\u91c7\u8d2d{replenish_qty}\u4ef6" if replenish_qty > 0 else "\u8bf7\u624b\u52a8\u5904\u7406",
                    notify_agents=notify,
                )
                report["alerts"].append(alert.__dict__)  # 使用__dict__转为字典

            report["items"].append(item_report)

        return report

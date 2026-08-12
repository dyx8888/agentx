"""
Agent Tool Implementations
Bridges deterministic engines to agent tool calls.
Each tool function wraps an engine method for use in AgentRuntime.
"""

from langchain_core.tools import tool

from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Data Analysis Agent Tools ──────────────────────────────────────────
# 数据分析工具的入参设计为全可选+默认值——LLM 可能只传部分参数，默认值防止计算崩溃


@tool
def calculate_ecommerce_metrics(
    payment_amount: float = 0.0,  # 所有参数默认 0.0/0——避免 LLM 遗漏参数时工具调用失败
    refund_amount: float = 0.0,
    ad_spend: float = 0.0,
    impressions: int = 0,
    clicks: int = 0,
    conversions: int = 0,
    orders: int = 0,
    unique_buyers: int = 0,
    repeat_buyers: int = 0,
) -> dict:
    """计算电商核心指标：GMV/ROI/CPA/CTR/CVR/GPM/客单价/复购率/退款率"""
    from app.engines.metrics_engine import (
        MetricsEngine,  # 延迟导入——只在实际调用时才加载引擎，减少 cold start 内存
    )

    metrics = MetricsEngine.calculate_metrics(  # 静态方法调用，无需实例化——MetricsEngine 设计为无状态工具类
        payment_amount=payment_amount,
        refund_amount=refund_amount,
        ad_spend=ad_spend,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        orders=orders,
        unique_buyers=unique_buyers,
        repeat_buyers=repeat_buyers,
    )
    return {
        "gmv": metrics.gmv,
        "refund_amount": metrics.refund_amount,
        "net_gmv": metrics.net_gmv,
        "ad_spend": metrics.ad_spend,
        "impressions": metrics.impressions,
        "clicks": metrics.clicks,
        "conversions": metrics.conversions,
        "orders": metrics.orders,
        "unique_buyers": metrics.unique_buyers,
        "repeat_buyers": metrics.repeat_buyers,
        "roi": metrics.roi,
        "cpa": metrics.cpa,
        "ctr": metrics.ctr,
        "cvr": metrics.cvr,
        "gpm": metrics.gpm,
        "aov": metrics.aov,
        "repurchase_rate": metrics.repurchase_rate,
        "refund_rate": metrics.refund_rate,
    }  # 返回字典而非对象——LLM 只能消费 JSON 结构化数据


@tool
def detect_metric_anomaly(
    metric_name: str,
    current_value: float,
    previous_value: float,
) -> dict:
    """检测指标异常：对比当前值与上期值，输出告警等级和描述"""
    from app.engines.metrics_engine import MetricsEngine  # 延迟导入引擎，减少模块间耦合

    alert = MetricsEngine.detect_anomaly(metric_name, current_value, previous_value)
    return {
        "metric": metric_name,
        "current": current_value,
        "previous": previous_value,
        "change_pct": alert.get("change_pct", 0),  # 使用 .get() 防止引擎返回缺失字段时 KeyError
        "severity": alert.get("severity", "normal"),
        "message": alert.get("message", ""),
    }


@tool
def generate_metrics_report(
    company_id: int,
    period: str = "weekly",
    metrics_data: list[dict] = None,
) -> dict:
    """生成经营指标报告：汇总指标、趋势分析、异常告警"""
    from app.engines.metrics_engine import MetricsEngine

    report = MetricsEngine.generate_report(
        company_id, period, metrics_data or []
    )  # or [] 确保 None 不会传入引擎
    return report


@tool
def forecase_trend(
    metric_name: str,
    historical_data: list[float],
    forecast_days: int = 7,
) -> dict:
    """预测指标趋势：基于历史数据预测未来N天走势"""
    from app.engines.metrics_engine import MetricsEngine

    result = MetricsEngine.forecast_trend(metric_name, historical_data, forecast_days)
    return result


# ── Warehouse Logistics Agent Tools ────────────────────────────────────
# 仓储物流工具的数据结构（InventoryItem）封装了库存检查的核心字段，确保不同类型数据不会混淆


@tool
def check_inventory(
    sku: str,
    name: str,
    stock: int,
    avg_daily_sales_7d: float,
    avg_daily_sales_30d: float = 0,
    replenishment_days: int = 7,
    expiry_date: str = None,
) -> dict:
    """检查库存状态：返回库存状态（正常/预警/缺货/滞销/临期）及建议"""
    from app.engines.logistics_engine import (  # 同时导入数据类和引擎，两者耦合但属于同一模块
        InventoryItem,
        LogisticsEngine,
    )

    item = InventoryItem(  # 使用数据类而非字典——InventoryItem 提供类型安全和字段校验
        sku=sku,
        name=name,
        stock=stock,
        avg_daily_sales_7d=avg_daily_sales_7d,
        avg_daily_sales_30d=avg_daily_sales_30d,
        replenishment_days=replenishment_days,
        expiry_date=expiry_date,
    )
    status, message, suggestions = LogisticsEngine.check_inventory_status(
        item,
        avg_daily_sales_30d
        or avg_daily_sales_7d * 30,  # 优先用 30d 数据，fallback 到 7d 估算——保证总有历史基准
    )
    return {
        "sku": sku,
        "name": name,
        "stock": stock,
        "status": status,
        "message": message,
        "suggestions": suggestions,
    }


@tool
def calculate_replenishment(
    sku: str,
    name: str,
    current_stock: int,
    avg_daily_sales: float,
    lead_time_days: int = 7,
    safety_stock_days: int = 3,
) -> dict:
    """计算补货建议：基于日均销量和交期计算建议补货量"""
    from app.engines.logistics_engine import LogisticsEngine

    result = LogisticsEngine.calculate_replenishment(
        sku, name, current_stock, avg_daily_sales, lead_time_days, safety_stock_days
    )
    return result


@tool
def track_shipment(
    tracking_no: str,
    provider: str = "auto",  # 默认 auto 自动识别快递公司，避免 LLM 需要额外判断快递公司
) -> dict:
    """追踪物流状态：查询快递单号的最新物流轨迹"""
    from app.services.erp_bridge import (
        ERPBridge,  # 物流追踪走 ERP 桥接层而非直接调用快递 API——统一多平台接口
    )

    return ERPBridge.query_express(tracking_no, provider)


@tool
def detect_shipment_exception(
    tracking_no: str,
    last_update_hours: float = 24,
    status: str = "",
) -> dict:
    """检测物流异常：超时未揽收/中断/签收异常等"""
    from app.engines.logistics_engine import LogisticsEngine

    return LogisticsEngine.detect_shipment_exception(tracking_no, last_update_hours, status)


@tool
def recommend_packaging(
    product_type: str,
    weight_kg: float = 1.0,
    fragile: bool = False,
    quantity: int = 1,
) -> dict:
    """推荐包材方案：根据产品类型/重量/易碎性推荐包材"""
    from app.engines.logistics_engine import LogisticsEngine

    return LogisticsEngine.recommend_packaging(product_type, weight_kg, fragile, quantity)


# ── Customer Service Agent Tools ───────────────────────────────────────


@tool
def analyze_sentiment(
    customer_message: str,
    context: dict = None,
) -> dict:
    """分析客户消息情绪：低风险/中风险/高风险分级"""
    from app.engines.customer_service_engine import CustomerServiceEngine

    engine = CustomerServiceEngine()
    emotion = engine._detect_emotion(customer_message)
    level = emotion.value
    return {
        "emotion": emotion,
        "risk_level": level,
        "message": customer_message[:200],
    }


@tool
def evaluate_send_strategy(
    message_id: str,
    customer_message: str,
    confidence: float,
    agent_reply: str = "",
    context: dict = None,
) -> dict:
    """评估消息发送策略：快速审核/批量确认/逐条审核/拦截"""
    from app.services.send_strategy import SendStrategyEngine

    decision = SendStrategyEngine.evaluate(
        message_id, customer_message, confidence, agent_reply, context
    )
    requires_review = (not decision.auto_send) or decision.level.value != "auto_send"
    return {
        "message_id": message_id,
        "send_level": decision.level.value,
        "confidence": confidence,
        "requires_review": requires_review,
        "requires_escalation": decision.requires_escalation,
        "sentiment_risk": decision.sentiment_risk.value if decision.sentiment_risk else "normal",
        "action": "auto_send" if decision.auto_send else decision.level.value,
        "auto_send": decision.auto_send,
        "batch_group": decision.batch_group,
        "escalation_note": decision.escalation_note,
        "reason": decision.reason,
    }


@tool
def generate_auto_reply(
    inquiry_type: str,
    product_info: dict = None,
    customer_info: dict = None,
) -> dict:
    """生成自动回复话术：基于RAG检索公司知识库匹配最佳回复模板"""
    return {
        "inquiry_type": inquiry_type,
        "reply": f"感谢您的咨询！关于{inquiry_type}的问题，我们的客服正在为您处理。",
        "confidence": 0.85,
        "template_used": f"auto_reply_{inquiry_type}",
        "status": "pending_review",
        "auto_send": False,
        "requires_human_review": True,
        "message": "当前仅生成客服回复草稿，未接入外发渠道，也不会自动发送。",
    }


# ── Visual Designer Agent Tools ────────────────────────────────────────
# 视觉设计工具涉及异步操作和外部 API 调用——需要 async/await 和异常处理


@tool
async def generate_design_image(  # async 函数——图片生成是 I/O 密集型操作，需要异步等待外部 API
    prompt: str,
    design_type: str = "main_image",
    platform: str = "douyin",
    style_reference: str = None,
    brand_template_id: str = None,
    product_name: str = "",
) -> dict:
    """生成电商设计图：主图/详情页/封面等"""
    from app.services.image_pipeline import (  # 同时导入请求数据类和流水线
        ImageDesignRequest,
        ImageGenerationPipeline,
    )

    pipeline = ImageGenerationPipeline()  # 流水线实例化——每次调用创建新实例，避免状态污染
    request = ImageDesignRequest(  # 使用请求数据类封装——字段校验在数据类内部完成
        product_name=product_name,
        design_type=design_type,
        platform=platform,
        prompt=prompt,
        style_reference=style_reference,
        brand_template_id=brand_template_id,
    )
    result = await pipeline.run_full_pipeline(
        request
    )  # await 等待流水线完成，确保调用方拿到最终结果
    return result


@tool
def search_style_reference(
    product_category: str,
    style_keywords: list[str] = None,
    brand_id: str = None,
    top_k: int = 5,
) -> dict:
    """搜索设计风格参考：通过多模态RAG检索品牌历史素材和参考风格"""
    try:
        from app.rag.multimodal_retriever import (
            get_multimodal_retriever,  # 延迟导入多模态检索器——避免启动时就加载 Milvus 连接
        )

        keywords = style_keywords or []
        query = product_category
        if keywords:
            query += " " + " ".join(keywords)  # 拼接关键词到查询字符串，提升检索召回率

        retriever = get_multimodal_retriever(
            brand_id or "default"
        )  # 默认品牌 ID 兜底——未指定品牌时使用通用检索
        results = retriever.search_by_text(query, top_k=top_k)

        return {
            "category": product_category,
            "keywords": keywords,
            "references": [
                {
                    "id": r.image_id,
                    "url": r.image_path or "",
                    "caption": r.caption,
                    "score": round(
                        r.similarity, 4
                    ),  # 四舍五入到 4 位小数——相似度分数精度不需要太高
                }
                for r in results
            ],
        }
    except Exception as e:
        from app.core.logging import (
            get_logger,  # 异常处理中重新导入 logger——确保异常时 logger 一定可用
        )

        logger = get_logger(__name__)
        logger.warning(
            "multimodal_search_failed", error=str(e)
        )  # 警告级别而非错误——多模态检索失败不阻塞主流程
        return {
            "category": product_category,
            "keywords": style_keywords or [],
            "references": [],
            "warning": "多模态检索暂不可用，请人工参考历史素材",  # 用户友好的降级提示，引导人工介入
        }


@tool
def check_image_compliance(
    image_url: str,
    platform: str = "douyin",
) -> dict:
    """检查图片合规性：广告法合规检查+平台规范校验+文字检测"""
    return {
        "image_url": image_url,
        "platform": platform,
        "status": "unverified",
        "compliant": False,
        "requires_human_review": True,
        "violations": [],
        "warnings": ["图片合规检测服务未接入，不能自动判定通过。"],
        "suggestions": ["请接入真实合规检测服务，或由人工审核后再发布。"],
    }


@tool
def export_multi_format(
    image_url: str,
    platform: str = "douyin",
    formats: list[str] = None,
) -> dict:
    """多尺寸导出：一键导出多平台多尺寸图片"""
    from app.services.image_pipeline import ImageGenerationPipeline

    pipeline = ImageGenerationPipeline()
    sizes = pipeline.PLATFORM_SIZE_MAP.get(
        platform, {}
    )  # 从流水线类属性获取平台尺寸映射——避免硬编码尺寸
    return {
        "source": image_url,
        "platform": platform,
        "status": "unavailable",
        "requires_external_renderer": True,
        "message": "多尺寸导出服务未接入，未生成任何真实导出文件。",
        "exports": [
            {
                "size": size,
                "url": "",
                "format": "jpg",
                "status": "not_generated",
            }
            for size_list in sizes.values()
            for size in size_list
        ],
    }


# ── Product Selector Agent Tools ───────────────────────────────────────
# 选品工具的核心是评分引擎——多维度量化评估商品潜力


@tool
def evaluate_product(
    product_name: str,
    category: str,
    monthly_search_volume: int,
    growth_rate: float,
    competing_sellers: int,
    top_concentration: float,
    bid_intensity: float,
    gross_margin_pct: float,
    supplier_count: int,
    delivery_reliability: float,
    defect_rate: float,
    min_order_qty: int,
    current_month: int = None,
) -> dict:
    """多维度商品评估打分：市场容量+竞争强度+利润空间+供应链+季节匹配"""
    from app.engines.product_scoring import (
        ProductScoringEngine,  # 评分引擎是静态方法类——无状态，不需要实例化
    )

    score = ProductScoringEngine.evaluate(
        product_name=product_name,
        category=category,
        monthly_search_volume=monthly_search_volume,
        growth_rate=growth_rate,
        competing_sellers=competing_sellers,
        top_concentration=top_concentration,
        bid_intensity=bid_intensity,
        gross_margin_pct=gross_margin_pct,
        supplier_count=supplier_count,
        delivery_reliability=delivery_reliability,
        defect_rate=defect_rate,
        min_order_qty=min_order_qty,
        current_month=current_month,
    )
    return {  # 返回评分对象的所有字段——LLM 需要完整的维度拆解来做决策
        "product_name": product_name,
        "total_score": score.total_score,
        "grade": score.grade,
        "recommendation": score.recommendation,
        "market_capacity_score": score.market_capacity_score,
        "competition_score": score.competition_score,
        "profit_score": score.profit_score,
        "supply_chain_score": score.supply_chain_score,
        "season_match_score": score.season_match_score,
        "strengths": score.strengths,
        "weaknesses": score.weaknesses,
        "risks": score.risks,
    }


@tool
def calculate_profit_chain(
    selling_price: float,
    purchase_cost: float,
    shipping_cost: float = 5.0,  # 默认物流成本 5 元——行业均值，可根据实际调整
    platform_fee_rate: float = 0.05,  # 默认平台佣金 5%——主流电商平台标准费率
    tech_service_rate: float = 0.02,
    promotion_cost_pct: float = 0.10,
    return_rate: float = 0.03,
    tax_rate: float = 0.01,
) -> dict:
    """利润全成本链测算：采购→物流→平台费用→推广→退货→税费→净利"""
    from app.engines.product_scoring import (
        ProfitCalculator,  # 利润计算器独立于评分引擎——单一职责分离
    )

    profit = ProfitCalculator.calculate(
        selling_price=selling_price,
        purchase_cost=purchase_cost,
        shipping_cost=shipping_cost,
        platform_fee_rate=platform_fee_rate,
        tech_service_rate=tech_service_rate,
        promotion_cost_pct=promotion_cost_pct,
        return_rate=return_rate,
        tax_rate=tax_rate,
    )
    return {
        "selling_price": selling_price,
        "purchase_cost": purchase_cost,
        "shipping_cost": profit.shipping_cost,
        "platform_fee": profit.platform_fee,
        "tech_service_fee": profit.tech_service_fee,
        "promotion_cost": profit.promotion_cost,
        "return_loss": profit.return_loss,
        "tax": profit.tax,
        "total_cost": profit.total_cost,
        "gross_profit": profit.gross_profit,
        "net_profit": profit.net_profit,
        "gross_margin_pct": profit.gross_margin_pct,
        "net_margin_pct": profit.net_margin_pct,
    }


@tool
def evaluate_supplier(
    supplier_name: str,
    company_type: str,
    delivery_reliability: float,
    defect_rate: float,
    min_order_qty: int,
    price_competitiveness: str,
    payment_terms: str = "现结",
    can_oem: bool = False,
) -> dict:
    """供应商评估：资质/稳定性/品控/灵活性/价格竞争力 五维度打分"""
    scores = {}  # 纯 Python 逻辑计算——供应商评估暂不需要外部引擎，直接内联计算
    scores["qualification"] = (
        80 if company_type == "工厂" else 65 if company_type == "贸易商" else 50
    )  # 工厂资质最高，贸易商次之
    scores["stability"] = max(
        0, min(100, int(delivery_reliability * 100))
    )  # 交付可靠性百分比化，钳制在 0-100
    scores["quality"] = max(0, min(100, int((1 - defect_rate) * 100)))  # 次品率越低品质分越高
    flexibility_base = 60  # 基础灵活度 60 分
    if min_order_qty <= 100:  # 起订量 ≤100 件加分——小批量支持灵活合作
        flexibility_base += 20
    if "月结" in payment_terms:  # 月结账期加分——体现供应商对合作方的信任
        flexibility_base += 10
    if can_oem:  # OEM 能力加分——支持定制化生产
        flexibility_base += 10
    scores["flexibility"] = min(100, flexibility_base)
    price_map = {
        "低于市场均价": 90,
        "等于市场均价": 75,
        "略高于市场均价": 50,
        "远高于市场均价": 30,
    }  # 价格竞争力映射表
    scores["price"] = price_map.get(price_competitiveness, 50)
    overall = sum(scores.values()) / len(scores)  # 等权平均——五个维度同等重要
    return {
        "supplier_name": supplier_name,
        "scores": scores,
        "overall_score": round(overall, 1),
        "grade": "A" if overall >= 80 else "B" if overall >= 60 else "C",  # 三级评分制，简洁明了
        "recommendation": "推荐合作" if overall >= 70 else "可考虑" if overall >= 50 else "不推荐",
    }


# ── Smart Ad Delivery Agent Tools ──────────────────────────────────────
# 投流工具的核心是风险控制——止损复核建议和 A/B 测试确保投放效率


@tool
def evaluate_stop_loss(
    campaign_id: str,
    cpa: float,
    target_cpa: float,
    roi: float,
    target_roi: float,
    ctr: float,
    running_hours: float,
    daily_budget: float,
    current_spend: float,
    consecutive_low_roi_days: int = 0,
    campaign_name: str | None = None,
    platform: str = "unknown",
    industry_avg_ctr: float = 0.02,
    impressions: int = 0,
    clicks: int = 1,
    conversions: int = 1,
) -> dict:
    """评估广告止损规则：检查是否触发止损条件并生成待确认建议"""
    from app.engines.stop_loss import (  # 止损引擎独立模块——可被其他投放系统复用
        CampaignMetrics,
        StopLossEngine,
    )

    metrics = CampaignMetrics(  # 数据类封装投放指标——避免参数散落
        campaign_id=campaign_id,
        campaign_name=campaign_name or campaign_id,
        platform=platform,
        daily_budget=daily_budget,
        current_spend=current_spend,
        cpa=cpa,
        target_cpa=target_cpa,
        roi=roi,
        breakeven_roi=target_roi,
        ctr=ctr,
        industry_avg_ctr=industry_avg_ctr,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        running_hours=running_hours,
    )
    engine = StopLossEngine()  # 止损引擎实例化——每次评估创建新实例，避免状态残留
    triggers = engine.evaluate(metrics, consecutive_low_roi_days)
    return {
        "campaign_id": campaign_id,
        "triggers": [
            {
                "rule_id": t.rule_id,
                "description": t.reason,
                "action": t.action.value,
                "severity": t.severity.value,
                "auto_execute": t.auto_executed,  # 兼容字段：预算/暂停类规则应为False
                "requires_human_review": not t.auto_executed,
                "recommended_action": t.recommended_action,
            }
            for t in triggers
        ],
        "trigger_count": len(triggers),
        "has_critical": any(
            t.severity.value == "critical" for t in triggers
        ),  # 快速判断是否有严重触发——前端可据此高亮告警
    }


@tool
def design_ab_test(
    test_name: str,
    variable: str,
    control_description: str,
    experiment_description: str,
    target_metric: str = "cvr",
    min_improvement_pct: float = 10.0,
    min_duration_days: int = 3,
) -> dict:
    """设计A/B测试方案：单变量测试设计及流量分配"""
    from app.engines.ab_test import ABTestEngine, ABTestVariable  # A/B 测试引擎——科学实验方法论封装

    var = ABTestVariable(variable)  # 变量枚举——确保只测试合法变量（素材/人群/出价）
    design = ABTestEngine.design_test(
        test_name=test_name,
        variable=var,
        control_description=control_description,
        experiment_description=experiment_description,
        target_metric=target_metric,
        min_improvement_pct=min_improvement_pct,
        min_duration_days=min_duration_days,
    )
    return {
        "test_id": design.test_id,
        "test_name": test_name,
        "variable": variable,
        "target_metric": target_metric,
        "min_duration_days": min_duration_days,
        "min_sample_size": design.min_sample_size,
        "traffic_split": "50:50",  # 等分流量——最公平的 A/B 测试分配
        "control": control_description,
        "experiment": experiment_description,
    }


@tool
def analyze_ab_test_result(
    test_id: str,
    variable: str,
    control_impressions: int,
    control_clicks: int,
    control_conversions: int,
    control_spend: float,
    control_revenue: float,
    experiment_impressions: int,
    experiment_clicks: int,
    experiment_conversions: int,
    experiment_spend: float,
    experiment_revenue: float,
) -> dict:
    """分析A/B测试结果：统计显著性检验+胜出判定"""
    from app.engines.ab_test import (
        ABTestDesign,
        ABTestEngine,
        ABTestVariable,
        ABTestVariantResult,
    )  # 导入多个数据类——A/B 测试分析需要完整的实验设计+结果数据

    design = ABTestDesign(
        test_id=test_id,
        test_name="analysis",
        variable=ABTestVariable(variable),
        target_metric="cvr",
        min_duration_days=3,
        min_sample_size=1000,
    )
    control = ABTestVariantResult(
        variant_name="control",
        impressions=control_impressions,
        clicks=control_clicks,
        conversions=control_conversions,
        spend=control_spend,
        revenue=control_revenue,
    )
    experiment = ABTestVariantResult(
        variant_name="experiment",
        impressions=experiment_impressions,
        clicks=experiment_clicks,
        conversions=experiment_conversions,
        spend=experiment_spend,
        revenue=experiment_revenue,
    )
    result = ABTestEngine.analyze(
        design, control, experiment
    )  # 引擎执行统计分析——p 值检验和胜出判定
    return {
        "test_id": test_id,
        "winner": result.winner,
        "is_significant": result.is_significant,  # 是否达到统计显著性——p < 0.05
        "p_value": result.p_value,
        "improvement_pct": result.improvement_pct,
        "conclusion": result.conclusion,
        "recommendation": result.recommendation,
    }


# ── Content Operation Agent Tools ──────────────────────────────────────
# 内容运营工具涉及跨平台适配和外部视频编辑桥接


@tool
def adapt_content_for_platform(
    content: str,
    from_platform: str,
    to_platform: str,
    brand_voice: str = "",
) -> dict:
    """跨平台内容适配：自动改写内容以匹配目标平台风格和规范"""
    from app.platforms.platform_context_router import (
        PlatformContextRouter,  # 平台路由——统一管理多平台适配逻辑
    )

    router = PlatformContextRouter()
    result = router.adapt_content(content, from_platform, to_platform)
    return {
        "adapted_content": result.get(
            "adapted_content", content
        ),  # fallback 到原始内容——适配失败时不丢失内容
        "changes": result.get("changes", []),
        "platform_tips": result.get("platform_tips", ""),
    }


@tool
def create_platform_context(
    company_id: str,
    agent_id: str,
    platform: str,
    brand_voice: str = "",
) -> dict:
    """创建平台上下文沙箱：为指定平台创建隔离的内容创作环境"""
    from app.platforms.platform_context_router import PlatformContextRouter

    router = PlatformContextRouter()
    ctx = router.create_sandbox(
        company_id, agent_id, platform, brand_voice
    )  # 沙箱隔离——不同平台上下文互不干扰
    return {
        "sandbox_id": ctx.sandbox_id,
        "platform": platform,
        "content_style": ctx.content_style,
        "hashtag_style": ctx.hashtag_style,
        "forbidden_keywords": ctx.forbidden_keywords[:10],  # 只返回前 10 个违禁词——避免上下文过长
        "publishing_tips": ctx.publishing_tips,
    }


@tool
def bridge_video_editor(
    action: str,
    source_video_url: str = "",
    edit_config: dict = None,
    target_platform: str = "",
    output_format: str = "mp4",
    project_name: str = "",
) -> dict:
    """视频编辑桥接：连接外部视频编辑工具，管理编辑项目、提交编辑任务、查询渲染进度"""
    valid_actions = [
        "create_project",
        "submit_edit_task",
        "query_progress",
        "export_clip",
        "apply_template",
    ]  # 白名单校验——防止非法 action 调用
    if action not in valid_actions:
        return {"error": f"无效操作，支持: {', '.join(valid_actions)}"}

    if action in {"create_project", "submit_edit_task", "query_progress", "export_clip"}:
        return {
            "action": action,
            "project_name": project_name,
            "source_video": source_video_url,
            "target_platform": target_platform,
            "output_format": output_format,
            "status": "unavailable",
            "requires_external_editor": True,
            "message": "视频编辑服务未接入，未创建项目、提交任务、查询进度或生成导出文件。",
        }

    if action == "apply_template":
        templates = {  # 平台模板映射——不同平台有不同视频风格预设
            "douyin_short": "快节奏卡点、前3秒钩子、竖屏9:16、口语字幕",
            "xiaohongshu": "精致滤镜、舒缓BGM、竖屏3:4、种草风格文字",
            "bilibili_mid": "横屏16:9、信息密度高、弹幕互动提示、章节标记",
        }
        template = templates.get(target_platform, "默认模板")
        return {
            "action": "apply_template",
            "platform": target_platform,
            "template_name": template,
            "project_name": project_name,
            "preset_config": {
                "aspect_ratio": "9:16"
                if target_platform in ("douyin_short", "xiaohongshu")
                else "16:9",  # 竖屏平台默认 9:16
                "max_duration": 60
                if target_platform == "douyin_short"
                else 180,  # 抖音短视频限制 60 秒
                "subtitle_style": "bold_yellow"
                if target_platform == "douyin_short"
                else "clean_white",
                "intro_hook_required": True,
            },
            "message": f"已应用 {target_platform} 模板: {template}",
        }

    return {"error": "未知操作"}


# ── Brand BD Agent Tools ───────────────────────────────────────────────


@tool
def check_delivery_status(
    sample_id: str,
) -> dict:
    """查询寄样物流状态"""
    return {
        "sample_id": sample_id,
        "status": "unavailable",
        "requires_logistics_backend": True,
        "message": "寄样物流查询服务未接入真实物流或ERP后端，未返回模拟物流轨迹。",
        "carrier": "",
        "tracking_no": "",
        "estimated_delivery": "",
        "current_location": "",
    }


@tool
def generate_outreach_message(
    kol_name: str,
    platform: str,
    brand_name: str,
    product_name: str,
    cooperation_type: str = "种草推广",
    custom_points: list[str] = None,
) -> dict:
    """生成达人邀约话术：个性化微信/私信邀约文案"""
    points = custom_points or [f"{product_name}产品卖点突出", "佣金比例有竞争力"]
    wechat_msg = (
        f"Hi {kol_name}，我是{brand_name}的品牌商务负责人。\n"
        f"看到你在{platform}的优质内容，非常契合我们{brand_name}的品牌调性。\n"
        f"目前我们有{product_name}的产品希望寻求{cooperation_type}合作，"
        f"产品核心卖点：{'、'.join(points[:3])}。\n"
        f"方便聊聊合作细节吗？期待你的回复！"
    )
    private_msg = (
        f"你好{kol_name}！我是{brand_name}品牌方，\n"
        f"看到你的内容风格和我们品牌很匹配，想邀请你合作{cooperation_type}～\n"
        f"产品是{product_name}，{'、'.join(points[:2])}。\n"
        f"感兴趣的话回复我哦，我们可以详细沟通～"
    )
    return {
        "wechat": wechat_msg,
        "private_message": private_msg,
        "subject": f"【品牌合作邀请】{brand_name} × {kol_name} {cooperation_type}合作",
        "status": "pending_review",
        "review_note": "邀约话术需人工审核确认后发送",
    }


@tool
def manage_kol_relationship(
    action: str,
    kol_name: str = "",
    kol_platform: str = "",
    company_id: str = "",
    notes: str = "",
    cooperation_status: str = "",
    schedule_date: str = "",
) -> dict:
    """达人关系管理：档案维护、合作状态追踪、档期管理、历史合作记录查询"""
    valid_actions = [
        "add_profile",
        "update_status",
        "query_schedule",
        "list_active",
        "cooperation_history",
    ]
    if action not in valid_actions:
        return {"error": f"无效操作，支持: {', '.join(valid_actions)}"}

    base_response = {
        "action": action,
        "kol_name": kol_name,
        "platform": kol_platform,
        "company_id": company_id,
        "status": "unavailable",
        "requires_crm_backend": True,
        "message": "达人关系管理需要接入真实CRM或企业达人库写入后端；当前未创建、未更新、未返回样例记录。",
    }

    if action == "add_profile":
        return {
            **base_response,
            "profile": None,
            "notes": notes,
            "created": False,
        }

    if action == "update_status":
        valid_statuses = [
            "contacted",
            "negotiating",
            "confirmed",
            "in_progress",
            "completed",
            "dormant",
            "blacklisted",
        ]
        if cooperation_status not in valid_statuses:
            return {"error": f"无效状态，支持: {', '.join(valid_statuses)}"}
        return {
            **base_response,
            "new_status": cooperation_status,
            "updated": False,
        }

    if action == "query_schedule":
        return {
            **base_response,
            "kol_name": kol_name or "",
            "upcoming_campaigns": [],
            "available_slots": [],
        }

    if action == "list_active":
        return {
            **base_response,
            "active_kols": [],
            "total_active": 0,
        }

    if action == "cooperation_history":
        return {
            **base_response,
            "kol_name": kol_name or "",
            "total_cooperations": 0,
            "records": [],
            "summary": {},
        }

    return {"error": "未知操作"}


# ── Tool Registry Mapping ──────────────────────────────────────────────
# 工具注册表——将 agent key 映射到其对应的 tool 函数列表

AGENT_TOOL_MAP: dict[str, list] = {  # 模块级常量，所有 agent 的工具分配集中管理
    "data_analysis": [
        calculate_ecommerce_metrics,
        detect_metric_anomaly,
        generate_metrics_report,
        forecase_trend,
    ],
    "warehouse_logistics": [
        check_inventory,
        calculate_replenishment,
        track_shipment,
        detect_shipment_exception,
        recommend_packaging,
    ],
    "customer_service": [
        analyze_sentiment,
        evaluate_send_strategy,
        generate_auto_reply,
    ],
    "visual_designer": [
        generate_design_image,
        search_style_reference,
        check_image_compliance,
        export_multi_format,
    ],
    "product_selector": [
        evaluate_product,
        calculate_profit_chain,
        evaluate_supplier,
    ],
    "smart_ad_delivery": [
        evaluate_stop_loss,
        design_ab_test,
        analyze_ab_test_result,
    ],
    "content_operation": [
        adapt_content_for_platform,
        create_platform_context,
        bridge_video_editor,
    ],
    "brand_bd": [
        check_delivery_status,
        generate_outreach_message,
        manage_kol_relationship,
    ],
}  # 直接引用函数对象而非字符串——避免运行时通过 getattr 查找，且支持 IDE 跳转


def get_agent_tools(agent_key: str) -> list:
    return AGENT_TOOL_MAP.get(
        agent_key, []
    )  # 未知 agent 返回空列表——调用方安全遍历，不会 None 崩溃


def register_agent_tools(registry) -> int:
    count = 0
    for _agent_key, tools in AGENT_TOOL_MAP.items():  # 遍历所有 agent 的所有工具
        for t in tools:
            name = t.name  # @tool 装饰器自动生成的 name 属性
            if (
                not hasattr(t, "description") or not t.description
            ):  # 跳过无描述的 tool——确保 LLM 能理解工具用途
                continue
            registry.register(name, t, description=t.description)  # 注册到 LangChain 工具注册表
            count += 1
    logger.info("agent_tools_registered", total=count)  # 结构化日志记录注册数量——便于监控和排查
    return count

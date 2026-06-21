"""
ProductScoringEngine + ProfitCalculator - Deterministic product evaluation engines
Zero LLM dependency, pure computation.
"""  # 选品评分引擎 + 利润计算器：纯数学计算，无LLM依赖

from dataclasses import dataclass, field  # 数据模型定义


@dataclass
class ProductScore:  # 商品评分结果模型
    product_name: str  # 商品名称
    market_capacity_score: float  # 市场容量得分
    competition_score: float  # 竞争强度得分（越高越不激烈）
    profit_score: float  # 利润空间得分
    supply_chain_score: float  # 供应链稳定性得分
    season_match_score: float  # 季节性匹配得分
    total_score: float  # 加权总分
    grade: str  # 评级：A/B/C/D
    recommendation: str  # 推荐建议
    strengths: list[str] = field(default_factory=list)  # 优势
    weaknesses: list[str] = field(default_factory=list)  # 劣势
    risks: list[str] = field(default_factory=list)  # 风险


@dataclass
class ProfitBreakdown:  # 全链路利润分解模型
    selling_price: float  # 售价
    purchase_cost: float  # 采购成本
    logistics_cost: float  # 物流成本
    platform_fee: float  # 平台费用（佣金+技术费+广告费）
    return_loss: float  # 退货损耗
    tax: float  # 税费
    gross_profit: float  # 毛利 = 售价 - 采购成本
    gross_margin: float  # 毛利率
    net_profit: float  # 净利润 = 售价 - 所有成本
    net_margin: float  # 净利率
    breakeven_volume: int  # 盈亏平衡销量


class ProductScoringEngine:
    """Multi-dimensional product evaluation scoring engine."""  # 五维选品评分引擎：市场+竞争+利润+供应链+季节性

    SCORING_WEIGHTS: dict[str, float] = {  # 五个维度的权重配置，利润和市场各占25%为最高
        "market_capacity": 0.25,  # 市场容量权重25%
        "competition": 0.20,  # 竞争强度权重20%
        "profit_margin": 0.25,  # 利润空间权重25%
        "supply_chain": 0.15,  # 供应链权重15%
        "season_match": 0.15,  # 季节性匹配权重15%
    }

    MARKET_CAPACITY_BENCHMARKS: dict[str, dict] = {  # 各类目的搜索量基准，用于市场容量评分
        "\u670d\u9970\u978b\u5305": {"search_volume_high": 500000, "search_volume_mid": 100000},  # 服饰鞋包：搜索量最大
        "\u7f8e\u5986\u62a4\u80a4": {"search_volume_high": 300000, "search_volume_mid": 80000},
        "\u5bb6\u5c45\u767e\u8d27": {"search_volume_high": 200000, "search_volume_mid": 50000},
        "\u6570\u7801\u7535\u5668": {"search_volume_high": 400000, "search_volume_mid": 100000},
        "\u98df\u54c1\u996e\u6599": {"search_volume_high": 600000, "search_volume_mid": 150000},  # 食品：搜索量最大
        "\u6bcd\u5a74\u7528\u54c1": {"search_volume_high": 200000, "search_volume_mid": 50000},
        "default": {"search_volume_high": 200000, "search_volume_mid": 50000},  # 未知类目用默认值
    }

    @classmethod
    def score_market_capacity(cls, category: str, monthly_search_volume: int, growth_rate: float) -> float:  # 市场容量评分：搜索量×0.6 + 增长率×0.4
        benchmarks = cls.MARKET_CAPACITY_BENCHMARKS.get(category, cls.MARKET_CAPACITY_BENCHMARKS["default"])  # 获取该品类的基准

        if monthly_search_volume >= benchmarks["search_volume_high"]:  # 超过高基准得80分
            volume_score = 80
        elif monthly_search_volume >= benchmarks["search_volume_mid"]:  # 在中高之间线性插值：50~80分
            volume_score = 50 + (monthly_search_volume - benchmarks["search_volume_mid"]) / (
                benchmarks["search_volume_high"] - benchmarks["search_volume_mid"]) * 30
        else:  # 低于中等基准：按比例计算，最低10分
            volume_score = max(10, monthly_search_volume / benchmarks["search_volume_mid"] * 50)

        growth_score = min(100, max(0, growth_rate * 100 + 50))  # 增长率得分：growth_rate=0→50分，growth_rate=0.5→100分

        return round(volume_score * 0.6 + growth_score * 0.4, 1)  # 搜索量占60%，增长率占40%

    @staticmethod
    def score_competition(competing_sellers: int, top_concentration: float, bid_intensity: float) -> float:  # 竞争评分：卖家数+集中度+竞价强度
        seller_score = max(0, 100 - (competing_sellers / 100) * 20)  # 每100个卖家扣20分
        concentration_score = max(0, 100 - top_concentration)  # 集中度越低越好（蓝海）
        bid_score = max(0, 100 - bid_intensity)  # 竞价强度越低越好

        return round(seller_score * 0.3 + concentration_score * 0.35 + bid_score * 0.35, 1)  # 三者权重接近

    @staticmethod
    def score_profit_margin(gross_margin_pct: float) -> float:  # 毛利率评分：分段线性映射
        if gross_margin_pct >= 60:  # 60%以上的暴利品类
            return 95
        elif gross_margin_pct >= 40:  # 40-60%：80-95分
            return 80 + (gross_margin_pct - 40) / 20 * 15
        elif gross_margin_pct >= 25:  # 25-40%：50-80分
            return 50 + (gross_margin_pct - 25) / 15 * 30
        elif gross_margin_pct >= 15:  # 15-25%：20-50分
            return 20 + (gross_margin_pct - 15) / 10 * 30
        else:  # 低于15%微利
            return max(0, gross_margin_pct / 15 * 20)

    @staticmethod
    def score_supply_chain(  # 供应链评分：供应商数+交货可靠性+次品率+起订量
        supplier_count: int,
        delivery_reliability: float,  # 0-100分
        defect_rate: float,  # 次品率（如0.03=3%）
        min_order_qty: int,  # 最小起订量
    ) -> float:
        count_score = min(100, supplier_count * 15)  # 供应商越多越好，每个加15分，最多100
        reliability_score = delivery_reliability  # 交货可靠性直接用作得分
        quality_score = max(0, 100 - defect_rate * 100)  # 次品率每1%扣1分
        flexibility_score = max(0, 100 - min_order_qty / 10)  # 起订量越低越灵活

        return round(count_score * 0.2 + reliability_score * 0.3 + quality_score * 0.3 + flexibility_score * 0.2, 1)  # 质量和可靠性权重最高

    @staticmethod
    def score_season_match(category: str, current_month: int = None) -> float:  # 季节性匹配评分
        from datetime import datetime  # 延迟导入，只在需要时加载
        if current_month is None:  # 默认使用当前月份
            current_month = datetime.now().month

        seasonal_map: dict[str, list[int]] = {  # 各类目的旺季月份
            "\u670d\u9970\u978b\u5305": [3, 4, 5, 9, 10, 11],  # 春秋换季
            "\u7f8e\u5986\u62a4\u80a4": [1, 2, 3, 4, 5, 9, 10, 11, 12],
            "\u5bb6\u5c45\u767e\u8d27": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],  # 全年旺季
            "\u6570\u7801\u7535\u5668": [1, 2, 6, 7, 8, 11, 12],  # 寒暑假和促销季
            "\u98df\u54c1\u996e\u6599": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],  # 全年旺季
            "\u6bcd\u5a74\u7528\u54c1": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        }

        peak_months = seasonal_map.get(category, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])  # 无匹配时默认全年

        if current_month in peak_months:  # 当前月份在旺季
            return 90
        elif (current_month + 1) % 12 + 1 in peak_months or (current_month - 1) % 12 + 1 in peak_months:  # 前后1个月在旺季
            return 70
        elif (current_month + 2) % 12 + 1 in peak_months or (current_month - 2) % 12 + 1 in peak_months:  # 前后2个月
            return 50
        else:  # 淡季
            return 30

    @classmethod
    def evaluate(  # 五维综合评价入口：计算各维度得分→加权求和→评级分类
        cls,
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
    ) -> ProductScore:
        market_score = cls.score_market_capacity(category, monthly_search_volume, growth_rate)  # 市场容量得分
        competition_score = cls.score_competition(competing_sellers, top_concentration, bid_intensity)  # 竞争得分
        profit_score = cls.score_profit_margin(gross_margin_pct)  # 利润得分
        supply_score = cls.score_supply_chain(supplier_count, delivery_reliability, defect_rate, min_order_qty)  # 供应链得分
        season_score = cls.score_season_match(category, current_month)  # 季节性得分

        weights = cls.SCORING_WEIGHTS
        total = (  # 加权总分
            market_score * weights["market_capacity"]
            + competition_score * weights["competition"]
            + profit_score * weights["profit_margin"]
            + supply_score * weights["supply_chain"]
            + season_score * weights["season_match"]
        )

        if total >= 80:  # A级：强烈推荐
            grade = "A"
            recommendation = "\u5f3a\u70c8\u63a8\u8350\uff0c\u4f18\u5148\u5165\u5e93"
        elif total >= 65:  # B级：推荐测款
            grade = "B"
            recommendation = "\u63a8\u8350\uff0c\u53ef\u5c1d\u8bd5\u5c0f\u89c4\u6a21\u6d4b\u6b3e"
        elif total >= 50:  # C级：谨慎
            grade = "C"
            recommendation = "\u8c28\u614e\uff0c\u9700\u89e3\u51b3\u5173\u952e\u95ee\u9898\u540e\u518d\u8bc4\u4f30"
        else:  # D级：不推荐
            grade = "D"
            recommendation = "\u4e0d\u63a8\u8350\uff0c\u98ce\u9669\u8f83\u9ad8"

        strengths = []  # 收集各维度的优势和劣势
        weaknesses = []
        risks = []

        if market_score >= 70:
            strengths.append(f"\u5e02\u573a\u5bb9\u91cf\u5927(\u641c\u7d22\u91cf{monthly_search_volume})")
        if competition_score >= 70:
            strengths.append("\u7ade\u4e89\u5f3a\u5ea6\u8f83\u4f4e\uff0c\u8fdb\u5165\u95e8\u69db\u53ef\u63a7")
        if profit_score >= 75:
            strengths.append(f"\u6bdb\u5229\u7387{gross_margin_pct}%\uff0c\u5229\u6da6\u7a7a\u95f4\u4f18\u79c0")
        if supply_score >= 70:
            strengths.append(f"\u4f9b\u5e94\u94fe\u7a33\u5b9a(\u4f9b\u5e94\u5546{supplier_count}\u5bb6)")

        if market_score < 40:
            weaknesses.append("\u5e02\u573a\u5bb9\u91cf\u6709\u9650")
        if competition_score < 40:
            weaknesses.append("\u7ade\u4e89\u6fc0\u70c8")
        if profit_score < 40:
            weaknesses.append(f"\u6bdb\u5229\u7387\u4ec5{gross_margin_pct}%\uff0c\u76c8\u5229\u538b\u529b\u5927")
        if supply_score < 40:
            weaknesses.append("\u4f9b\u5e94\u94fe\u98ce\u9669\u8f83\u9ad8")

        if defect_rate > 0.05:  # 次品率超过5%是严重风险
            risks.append(f"\u6b21\u54c1\u7387{defect_rate*100:.1f}%\uff0c\u9700\u4e25\u683c\u54c1\u63a7")
        if gross_margin_pct < 20:  # 毛利率低于20%价格战风险高
            risks.append("\u5229\u6da6\u7a7a\u95f4\u8584\uff0c\u4ef7\u683c\u6218\u98ce\u9669\u9ad8")
        if min_order_qty > 500:  # 起订量过大资金压力大
            risks.append(f"\u8d77\u8ba2\u91cf{min_order_qty}\uff0c\u8d44\u91d1\u538b\u529b\u5927")

        return ProductScore(
            product_name=product_name,
            market_capacity_score=market_score,
            competition_score=competition_score,
            profit_score=profit_score,
            supply_chain_score=supply_score,
            season_match_score=season_score,
            total_score=round(total, 1),
            grade=grade,
            recommendation=recommendation,
            strengths=strengths,
            weaknesses=weaknesses,
            risks=risks,
        )


class ProfitCalculator:
    """Full cost chain profit calculation engine."""  # 全链路利润计算引擎：从采购成本到退货损耗，逐层拆解计算净利润

    PLATFORM_COMMISSION_RATES: dict[str, float] = {  # 各平台佣金费率，拼多多仅0.6%远低于其他平台的5%
        "taobao": 0.05,
        "tmall": 0.05,
        "pinduoduo": 0.006,
        "douyin": 0.05,
        "kuaishou": 0.05,
        "xiaohongshu": 0.05,
    }

    PLATFORM_TECH_FEE_RATES: dict[str, float] = {  # 各平台技术服务费率，拼多多同样低至0.6%
        "taobao": 0.02,
        "tmall": 0.02,
        "pinduoduo": 0.006,
        "douyin": 0.02,
        "kuaishou": 0.02,
        "xiaohongshu": 0.02,
    }

    @staticmethod
    def calculate_full_chain(  # 全链路成本计算：物流→平台→退货→税费→净利润，逐层扣减
        selling_price: float,  # 售价
        purchase_cost: float,  # 采购成本
        platform: str,  # 平台标识
        weight_kg: float = 0.5,  # 默认0.5kg
        expected_return_rate: float = 0.03,  # 默认3%退货率
        ad_ratio: float = 0.15,  # 默认广告费用占售价15%
        monthly_units: int = 100,  # 默认月销100件
        tax_rate: float = 0.01,  # 默认1%税率
    ) -> ProfitBreakdown:
        # 物流成本 = 基础运费 + 重量费，3元起步+2元/kg
        logistics_cost = 3.0 + weight_kg * 2.0

        # 仓储分摊 = 月固定200元 / 月销量，最少0.5元/件（避免销量极低时仓储成本趋于无穷）
        warehouse_share = max(0.5, 200.0 / monthly_units) if monthly_units > 0 else 0.5
        # 包装成本 = 基础0.3元 + 重量费0.2元/kg
        packaging_cost = 0.3 + weight_kg * 0.2
        total_logistics = logistics_cost + warehouse_share + packaging_cost  # 物流总成本 = 运费 + 仓储 + 包装

        commission_rate = ProfitCalculator.PLATFORM_COMMISSION_RATES.get(platform, 0.05)  # 获取平台佣金率
        tech_fee_rate = ProfitCalculator.PLATFORM_TECH_FEE_RATES.get(platform, 0.02)  # 获取技术服务费率
        commission = selling_price * commission_rate  # 佣金 = 售价 × 佣金率
        tech_fee = selling_price * tech_fee_rate  # 技术服务费 = 售价 × 费率
        ad_cost = selling_price * ad_ratio  # 广告费 = 售价 × 广告占比
        total_platform = commission + tech_fee + ad_cost  # 平台费用总和

        return_loss = selling_price * expected_return_rate  # 退货损耗 = 售价 × 退货率（退货商品无法二次销售）

        tax = selling_price * tax_rate  # 税费 = 售价 × 税率

        total_cost = purchase_cost + total_logistics + total_platform + return_loss + tax  # 全链路总成本
        net_profit = selling_price - total_cost  # 净利润 = 售价 - 总成本
        gross_profit = selling_price - purchase_cost  # 毛利 = 售价 - 采购成本（仅扣除直接成本）
        gross_margin = round(gross_profit / selling_price * 100, 2) if selling_price > 0 else 0.0  # 毛利率%
        net_margin = round(net_profit / selling_price * 100, 2) if selling_price > 0 else 0.0  # 净利率%

        # 盈亏平衡销量 = 月固定成本 / 单件净利润，月固定成本200元（仓储底薪+系统费）
        fixed_cost_per_month = 200.0
        # 净利润为负时BK销量设为99999（表示无法盈利），+1确保向上取整
        breakeven_volume = int(fixed_cost_per_month / net_profit) + 1 if net_profit > 0 else 99999

        return ProfitBreakdown(
            selling_price=selling_price,
            purchase_cost=purchase_cost,
            logistics_cost=round(total_logistics, 2),
            platform_fee=round(total_platform, 2),
            return_loss=round(return_loss, 2),
            tax=round(tax, 2),
            gross_profit=round(gross_profit, 2),
            gross_margin=gross_margin,
            net_profit=round(net_profit, 2),
            net_margin=net_margin,
            breakeven_volume=breakeven_volume,
        )

    @staticmethod
    def compare_platforms(  # 多平台利润对比：对同一商品在多个平台分别计算利润，按净利润排序
        selling_price: float,
        purchase_cost: float,
        platforms: list[str] = None,  # 默认比较抖音/淘宝/拼多多/小红书四大平台
        **kwargs,  # 透传其他参数（weight_kg/return_rate等）给calculate_full_chain
    ) -> list[dict]:
        if platforms is None:
            platforms = ["douyin", "taobao", "pinduoduo", "xiaohongshu"]  # 默认主流电商平台

        results = []
        for platform in platforms:
            breakdown = ProfitCalculator.calculate_full_chain(
                selling_price=selling_price,
                purchase_cost=purchase_cost,
                platform=platform,
                **kwargs,  # 保持所有平台使用相同的参数基准
            )
            results.append({
                "platform": platform,
                "net_profit": breakdown.net_profit,
                "net_margin": breakdown.net_margin,
                "gross_margin": breakdown.gross_margin,
                "platform_fee": breakdown.platform_fee,
                "recommended": breakdown.net_margin >= 15,  # 净利率≥15%标记为推荐，15%是电商行业合理利润线
            })

        results.sort(key=lambda x: x["net_profit"], reverse=True)  # 按净利润降序排列，最赚钱平台排第一
        return results

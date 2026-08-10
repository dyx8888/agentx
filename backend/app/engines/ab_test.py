"""
ABTestEngine - Deterministic A/B test statistical analysis engine
Zero LLM dependency, pure statistical computation.
"""  # 纯统计A/B测试引擎：不依赖LLM，所有计算通过数学公式完成，确保统计结论的客观性和可复现性

import math  # 用于sqrt、erf等统计计算函数，而非依赖numpy等重量级库，减少依赖和启动时间
import uuid  # 生成全局唯一的测试ID，避免测试标识冲突
from dataclasses import dataclass, field  # 使用dataclass简化数据模型定义，减少样板代码
from datetime import datetime  # 记录测试创建和完成时间，用于追踪测试周期
from enum import StrEnum  # 字符串枚举，便于序列化输出和日志记录


class ABTestVariable(StrEnum):  # 使用StrEnum而非普通Enum，因为A/B测试变量类型需要以字符串形式存储和传输
    CREATIVE = "creative"  # 广告创意素材：图片/视频等视觉元素
    AUDIENCE = "audience"  # 目标受众：不同人群包定位
    BID_STRATEGY = "bid_strategy"  # 出价策略：不同竞价方式
    LANDING_PAGE = "landing_page"  # 落地页：不同页面设计和内容
    COPY = "copy"  # 文案：广告标题和描述文字


class ABTestStatus(StrEnum):  # 测试状态枚举，使用字符串枚举便于前端直接展示
    DESIGNED = "designed"  # 已设计但未开始
    RUNNING = "running"  # 进行中，数据持续收集
    COMPLETED = "completed"  # 已完成，有明确结论
    INCONCLUSIVE = "inconclusive"  # 无结论，样本量不足或无显著差异
    STOPPED = "stopped"  # 手动停止


@dataclass
class ABTestDesign:  # 使用dataclass而非普通类，因为这是纯数据载体，不需要复杂方法
    test_id: str  # 全局唯一测试ID，格式如AB-XXXXXXXX
    test_name: str  # 人类可读的测试名称
    variable: ABTestVariable  # 测试变量类型
    control_description: str  # 对照组描述，记录原始方案是什么
    experiment_description: str  # 实验组描述，记录新方案是什么
    control_allocation: float = 0.5  # 对照组流量分配比例，默认50%，平衡组间样本量
    experiment_allocation: float = 0.5  # 实验组流量分配比例，互补为1
    min_sample_size: int = 1000  # 最小样本量，低于此值统计结论不可靠
    min_duration_days: int = 3  # 最短运行天数，避免单日波动影响结论
    max_duration_days: int = 7  # 最长运行天数，防止过长时间浪费流量
    significance_level: float = 0.05  # 显著性水平α=0.05，行业标准，确保95%置信度
    min_improvement_pct: float = 10.0  # 最小改进百分比阈值，低于此值认为无实际意义（统计显著≠业务显著）
    target_metric: str = "cvr"  # 主要优化指标，默认转化率
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())  # 使用field+factory确保每次创建实例时生成新时间戳


@dataclass
class ABTestVariantResult:  # 单个变体（对照组或实验组）的投放结果数据
    name: str  # 变体名称，如"对照组-原素材"
    impressions: int  # 曝光量：广告展示次数
    clicks: int  # 点击量：用户点击广告次数
    conversions: int  # 转化量：用户完成目标行为（下单/注册等）次数
    spend: float  # 消耗金额：该变体的广告花费
    ctr: float = 0.0  # 点击率：计算得出，默认0避免除零异常
    cvr: float = 0.0  # 转化率：计算得出
    cpa: float = 0.0  # 单次转化成本：计算得出
    roi: float = 0.0  # 投资回报率：计算得出


@dataclass
class ABTestResult:  # A/B测试最终分析结果，汇总对照组和实验组的对比
    test_id: str  # 关联的测试ID
    test_name: str  # 测试名称
    status: ABTestStatus  # 测试最终状态
    variable: ABTestVariable  # 测试变量
    control: ABTestVariantResult  # 对照组结果
    experiment: ABTestVariantResult  # 实验组结果
    cvr_improvement_pct: float = 0.0  # 转化率提升百分比
    cvr_p_value: float = 1.0  # 转化率的p值，默认1.0表示无差异
    cvr_significant: bool = False  # 转化率是否统计显著
    ctr_improvement_pct: float = 0.0  # 点击率提升百分比
    ctr_p_value: float = 1.0  # 点击率的p值
    ctr_significant: bool = False  # 点击率是否统计显著
    winner: str = ""  # 胜出方："control"/"experiment"/"none"
    recommendation: str = ""  # 人工可读的建议文案
    started_at: str = ""  # 测试开始时间
    completed_at: str = ""  # 测试完成时间


class ABTestEngine:
    """Statistical A/B test engine for ad delivery optimization."""  # 纯统计A/B测试引擎，所有方法均为静态方法，无状态，确保线程安全

    @staticmethod
    def design_test(
        test_name: str,
        variable: ABTestVariable,
        control_description: str,
        experiment_description: str,
        target_metric: str = "cvr",
        min_improvement_pct: float = 10.0,
        min_duration_days: int = 3,
    ) -> ABTestDesign:
        test_id = f"AB-{uuid.uuid4().hex[:8].upper()}"  # 生成格式为AB-XXXXXXXX的唯一ID，取hex前8位保证可读性

        return ABTestDesign(  # 使用预设默认值构建测试设计，减少用户配置负担
            test_id=test_id,
            test_name=test_name,
            variable=variable,
            control_description=control_description,
            experiment_description=experiment_description,
            target_metric=target_metric,
            min_improvement_pct=min_improvement_pct,
            min_duration_days=min_duration_days,
        )

    @staticmethod
    def build_variant_result(  # 从原始投放数据构建计算结果，自动计算衍生指标
        name: str,
        impressions: int,
        clicks: int,
        conversions: int,
        spend: float,
    ) -> ABTestVariantResult:
        result = ABTestVariantResult(  # 先创建基础结果对象
            name=name,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            spend=spend,
        )
        if impressions > 0:  # 避免除零异常，只有在有曝光时才计算点击率
            result.ctr = round(clicks / impressions * 100, 2)  # 乘以100转换为百分比，保留2位小数
        if clicks > 0:  # 有点击才计算转化率，因为CVR=转化/点击
            result.cvr = round(conversions / clicks * 100, 2)
        if conversions > 0:  # 有转化才计算CPA，避免无穷大
            result.cpa = round(spend / conversions, 2)
        if spend > 0:  # 有花费才计算ROI
            result.roi = round(conversions * 0, 2)  # ROI=0，此处为占位，实际应由业务层根据收入计算
        return result

    @staticmethod
    def _calculate_p_value(control_conversions: int, control_total: int,  # 使用双样本比例检验计算p值
                           exp_conversions: int, exp_total: int) -> float:
        if control_total == 0 or exp_total == 0:  # 任一组的样本量为0时无法计算，返回1.0表示无差异
            return 1.0

        p1 = control_conversions / control_total  # 对照组转化率
        p2 = exp_conversions / exp_total  # 实验组转化率
        p_pool = (control_conversions + exp_conversions) / (control_total + exp_total)  # 合并后的总转化率，用于计算标准误

        if p_pool == 0 or p_pool == 1:  # 极端情况：全部转化或全部不转化，无法计算标准误
            return 1.0

        se = math.sqrt(p_pool * (1 - p_pool) * (1 / control_total + 1 / exp_total))  # 比例差的标准误公式
        if se == 0:  # 标准误为0说明两组完全一致
            return 1.0

        z_score = (p2 - p1) / se  # Z统计量，衡量两组差异的标准化程度

        return round(2 * (1 - ABTestEngine._norm_cdf(abs(z_score))), 4)  # 双尾检验p值，使用标准正态CDF近似

    @staticmethod
    def _norm_cdf(x: float) -> float:  # 标准正态分布的累积分布函数近似
        """Approximation of standard normal CDF."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))  # 利用math.erf误差函数计算CDF，避免引入scipy依赖

    @classmethod
    def analyze(  # 使用classmethod而非staticmethod，因为需要调用cls._calculate_p_value
        cls,
        design: ABTestDesign,
        control: ABTestVariantResult,
        experiment: ABTestVariantResult,
    ) -> ABTestResult:
        result = ABTestResult(  # 初始化结果对象，默认状态为RUNNING
            test_id=design.test_id,
            test_name=design.test_name,
            status=ABTestStatus.RUNNING,
            variable=design.variable,
            control=control,
            experiment=experiment,
            started_at=design.created_at,
        )

        if control.conversions > 0 and control.clicks > 0:  # 对照组有转化数据时才计算CVR的统计显著性
            cvr_p = cls._calculate_p_value(  # 针对转化率做双样本比例检验
                control.conversions, control.clicks,
                experiment.conversions, experiment.clicks,
            )
            result.cvr_p_value = cvr_p
            result.cvr_significant = cvr_p < design.significance_level  # p值小于显著性水平α=0.05则拒绝原假设

            if control.conversions > 0:
                control_cvr = control.conversions / control.clicks * 100  # 对照组CVR百分比
                experiment_cvr = experiment.conversions / experiment.clicks * 100  # 实验组CVR百分比
                result.cvr_improvement_pct = round(  # 计算相对提升百分比
                    (experiment_cvr - control_cvr) / control_cvr * 100, 2
                )

        if control.clicks > 0 and control.impressions > 0:  # 对照组有点击数据时才计算CTR的统计显著性
            ctr_p = cls._calculate_p_value(  # 针对点击率做双样本比例检验
                control.clicks, control.impressions,
                experiment.clicks, experiment.impressions,
            )
            result.ctr_p_value = ctr_p
            result.ctr_significant = ctr_p < design.significance_level

            if control.clicks > 0:
                control_ctr = control.clicks / control.impressions * 100
                experiment_ctr = experiment.clicks / experiment.impressions * 100
                result.ctr_improvement_pct = round(
                    (experiment_ctr - control_ctr) / control_ctr * 100, 2
                )

        total_conversions = control.conversions + experiment.conversions  # 总计转化量，用于判断是否达到最小样本量
        min_sample_met = total_conversions >= design.min_sample_size  # 样本量是否达标

        if min_sample_met and result.cvr_significant:  # 样本量达标且统计显著，才能做结论
            improvement = result.cvr_improvement_pct if design.target_metric == "cvr" else result.ctr_improvement_pct  # 根据目标指标选择正确的提升值

            if improvement >= design.min_improvement_pct:  # 实验组显著优于对照组，且超过最小业务改进阈值
                result.status = ABTestStatus.COMPLETED
                result.winner = "experiment"
                result.recommendation = (
                    f"实验组胜出，{design.target_metric.upper()}提升{improvement}%"
                    f"（p={result.cvr_p_value}），建议全量切换"
                )
            elif improvement <= -design.min_improvement_pct:  # 实验组显著差于对照组，建议回退
                result.status = ABTestStatus.COMPLETED
                result.winner = "control"
                result.recommendation = (
                    f"对照组表现更好，实验组{design.target_metric.upper()}下降"
                    f"{abs(improvement)}%，建议保持原方案"
                )
            else:  # 统计显著但业务提升不足，无实际意义
                result.status = ABTestStatus.INCONCLUSIVE
                result.winner = "none"
                result.recommendation = (
                    f"两组无显著差异（提升{improvement}% < {design.min_improvement_pct}%最小改进阈值），"
                    f"建议延长测试或更换变量"
                )
        elif not result.cvr_significant and total_conversions >= design.min_sample_size:  # 样本量够了但不显著
            result.status = ABTestStatus.INCONCLUSIVE
            result.winner = "none"
            result.recommendation = "样本量已达标但统计不显著，建议换新变量重新测试"
        else:  # 样本量不足，继续收集数据
            result.status = ABTestStatus.RUNNING
            result.recommendation = (
                f"测试进行中，当前样本{total_conversions}/{design.min_sample_size}，"
                f"继续收集数据"
            )

        if result.status in (ABTestStatus.COMPLETED, ABTestStatus.INCONCLUSIVE):  # 测试结束时记录完成时间
            result.completed_at = datetime.now().isoformat()

        return result

    @staticmethod
    def determine_sample_size(  # 使用功效分析计算所需最小样本量，确保测试有足够的统计功效
        baseline_rate: float,  # 基准转化率（如5% = 0.05）
        expected_improvement_pct: float,  # 预期提升百分比（如10%表示希望检测到10%的相对提升）
        significance_level: float = 0.05,  # 显著性水平α，默认0.05
        power: float = 0.80,  # 统计功效1-β，默认0.80，行业标准
    ) -> int:
        z_alpha = 1.96 if significance_level == 0.05 else 1.64 if significance_level == 0.10 else 1.96  # 根据显著性水平查Z值，简化了查找表
        z_beta = 0.84 if power == 0.80 else 1.28 if power == 0.90 else 0.84  # 根据功效查Z值

        p1 = baseline_rate  # 对照组比例
        p2 = baseline_rate * (1 + expected_improvement_pct / 100)  # 实验组预期比例 = 基准 * (1 + 提升百分比)

        p_pool = (p1 + p2) / 2  # 合并比例用于样本量估计

        if p_pool <= 0 or p_pool >= 1:  # 极端情况，返回保守的大样本量
            return 5000

        numerator = (z_alpha * math.sqrt(2 * p_pool * (1 - p_pool))  # 双样本比例检验的样本量公式分子
                     + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
        denominator = (p2 - p1) ** 2  # 效应量（两组比例差）的平方

        if denominator == 0:  # 预计无差异，无需计算
            return 5000

        return max(100, int(numerator / denominator))  # 至少100个样本，避免过小的样本量导致结论不可靠

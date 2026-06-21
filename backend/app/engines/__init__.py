"""
Deterministic Engines - Zero-LLM computation components
"""  # 确定性引擎包：所有引擎均为纯计算模块，不依赖任何LLM，确保结果可复现、成本可控

# 每个引擎独立处理一个业务领域，通过纯数学/规则计算而非AI推理来保证确定性和低延迟
# 这种设计避免了LLM调用带来的延迟和不确定性，适合高频、实时、成本敏感的业务场景

from app.engines.ab_test import ABTestEngine  # AB测试统计引擎：纯统计显著性检验，不依赖LLM
from app.engines.logistics_engine import LogisticsEngine  # 物流引擎：库存监控、发货追踪、异常检测
from app.engines.metrics_engine import MetricsEngine  # 指标计算引擎：GMV/ROI/CPA等核心电商指标
from app.engines.product_scoring import ProductScoringEngine, ProfitCalculator  # 选品评分+利润计算
from app.engines.stop_loss import StopLossEngine  # 自动止损引擎：规则驱动的广告止损评估

__all__ = [  # 显式声明公开API，防止import *时污染命名空间
    "MetricsEngine",
    "LogisticsEngine",
    "ProductScoringEngine",
    "ProfitCalculator",
    "StopLossEngine",
    "ABTestEngine",
]

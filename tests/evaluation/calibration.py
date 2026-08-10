"""
Calibration Module - 人工校准与回归测试
- 每50次评测抽检5次，校准LLM-as-Judge评分
- golden test set 管理
- 回归测试
- 测试集随业务迭代更新
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class GoldenCase:
    """Golden test case - 人工标注的标准答案"""
    id: str = ""
    agent_name: str = ""
    scenario: str = ""
    message: str = ""
    expected_output_contains: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    human_score: float = 1.0
    human_notes: str = ""
    annotated_by: str = ""
    annotated_at: str = ""
    failure_category: str = ""  # 如果是故障案例


@dataclass
class CalibrationResult:
    """校准结果"""
    sample_size: int
    auto_scores: list[float]
    human_scores: list[float]
    correlation: float = 0.0
    bias: float = 0.0
    needs_retrain: bool = False
    notes: str = ""


class GoldenSetManager:
    """Golden test set 管理器"""

    def __init__(self, golden_path: str = None):
        if golden_path is None:
            golden_path = os.path.join(
                os.path.dirname(__file__), "cases", "golden_set.json"
            )
        self._golden_path = golden_path
        self._cases: list[GoldenCase] = []
        self._loaded = False

    def _load(self) -> list[GoldenCase]:
        if self._loaded:
            return self._cases

        if os.path.exists(self._golden_path):
            try:
                with open(self._golden_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._cases = [
                    GoldenCase(
                        id=c.get("id", ""),
                        agent_name=c.get("agent_name", ""),
                        scenario=c.get("scenario", ""),
                        message=c.get("message", ""),
                        expected_output_contains=c.get("expected_output_contains", []),
                        expected_tools=c.get("expected_tools", []),
                        human_score=c.get("human_score", 1.0),
                        human_notes=c.get("human_notes", ""),
                        annotated_by=c.get("annotated_by", ""),
                        annotated_at=c.get("annotated_at", ""),
                        failure_category=c.get("failure_category", ""),
                    )
                    for c in data.get("cases", [])
                ]
            except Exception as e:
                print(f"Warning: Failed to load golden set: {e}")
                self._cases = []

        self._loaded = True
        return self._cases

    def _save(self):
        os.makedirs(os.path.dirname(self._golden_path), exist_ok=True)
        data = {
            "version": "1.0.0",
            "updated_at": datetime.now().isoformat(),
            "total_cases": len(self._cases),
            "cases": [
                {
                    "id": c.id,
                    "agent_name": c.agent_name,
                    "scenario": c.scenario,
                    "message": c.message,
                    "expected_output_contains": c.expected_output_contains,
                    "expected_tools": c.expected_tools,
                    "human_score": c.human_score,
                    "human_notes": c.human_notes,
                    "annotated_by": c.annotated_by,
                    "annotated_at": c.annotated_at,
                    "failure_category": c.failure_category,
                }
                for c in self._cases
            ],
        }
        with open(self._golden_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_case(self, case: GoldenCase):
        self._load()
        case.id = case.id or f"golden_{len(self._cases) + 1:03d}"
        case.annotated_at = case.annotated_at or datetime.now().isoformat()
        self._cases.append(case)
        self._save()

    def add_from_incident(self, agent_name: str, message: str,
                          expected_output: list[str], failure_category: str,
                          annotated_by: str = "system"):
        """从线上事故自动生成 golden case"""
        case = GoldenCase(
            id=f"incident_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            agent_name=agent_name,
            scenario=f"incident_{failure_category}",
            message=message,
            expected_output_contains=expected_output,
            human_score=1.0,
            failure_category=failure_category,
            annotated_by=annotated_by,
            human_notes=f"从线上 {failure_category} 事故自动生成",
        )
        self.add_case(case)
        return case

    def get_all(self) -> list[GoldenCase]:
        return self._load()

    def get_by_agent(self, agent_name: str) -> list[GoldenCase]:
        return [c for c in self._load() if c.agent_name == agent_name]

    def get_by_category(self, category: str) -> list[GoldenCase]:
        return [c for c in self._load() if c.failure_category == category]


class Calibrator:
    """LLM-as-Judge 校准器 - 每50次评测抽检5次"""

    def __init__(self, golden_manager: GoldenSetManager = None):
        self._golden = golden_manager or GoldenSetManager()
        self._eval_count: int = 0
        self._last_calibration_at: int = 0

    def should_calibrate(self) -> bool:
        """检查是否需要进行校准（每50次评测触发一次）"""
        return (self._eval_count - self._last_calibration_at) >= 50

    def calibrate(self, auto_results: list[dict]) -> CalibrationResult:
        """
        校准LLM-as-Judge评分。
        从最近的评测中抽取5个样本，与golden set中的人工评分对比。

        Args:
            auto_results: 自动评测结果列表

        Returns:
            CalibrationResult
        """
        golden_cases = self._golden.get_all()
        if not golden_cases:
            return CalibrationResult(
                sample_size=0,
                auto_scores=[],
                human_scores=[],
                notes="Golden set为空，请先添加人工标注样本",
            )

        # 抽取5个样本（优先选择有golden标注的）
        sample = []
        for gr in auto_results:
            agent = gr.get("agent", "")
            scenario = gr.get("scenario", "")
            matched = [
                g for g in golden_cases
                if g.agent_name == agent and g.scenario == scenario
            ]
            if matched:
                sample.append((gr, matched[0]))
            if len(sample) >= 5:
                break

        if not sample:
            return CalibrationResult(
                sample_size=0,
                auto_scores=[],
                human_scores=[],
                notes="无法匹配到有golden标注的样本",
            )

        auto_scores = [s[0].get("score", 0) or
                       (1.0 if s[0].get("success") else 0.0)
                       for s in sample]
        human_scores = [s[1].human_score for s in sample]

        # 计算相关性（简化版 Pearson）
        correlation = self._pearson_correlation(auto_scores, human_scores)
        bias = sum(a - h for a, h in zip(auto_scores, human_scores)) / len(sample)

        self._last_calibration_at = self._eval_count

        return CalibrationResult(
            sample_size=len(sample),
            auto_scores=auto_scores,
            human_scores=human_scores,
            correlation=correlation,
            bias=bias,
            needs_retrain=abs(correlation) < 0.7 or abs(bias) > 0.2,
            notes=(
                f"相关系数={correlation:.3f}, 偏差={bias:.3f}"
                + (" → 建议重新校准LLM-as-Judge" if abs(correlation) < 0.7 else "")
            ),
        )

    def record_eval(self):
        """记录一次评测完成"""
        self._eval_count += 1

    @staticmethod
    def _pearson_correlation(x: list[float], y: list[float]) -> float:
        """简化 Pearson 相关系数"""
        if len(x) < 2:
            return 1.0
        n = len(x)
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = (sum((xi - mean_x) ** 2 for xi in x) ** 0.5)
        std_y = (sum((yi - mean_y) ** 2 for yi in y) ** 0.5)
        if std_x == 0 or std_y == 0:
            return 1.0
        return cov / (std_x * std_y)


class RegressionTester:
    """回归测试 - 修改后自动跑评测集，对比上次分数"""

    def __init__(self, baseline_path: str = None):
        if baseline_path is None:
            baseline_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "reports", "evaluation",
                "baseline.json"
            )
        self._baseline_path = baseline_path

    def save_baseline(self, metrics: dict):
        """保存基线指标"""
        os.makedirs(os.path.dirname(self._baseline_path), exist_ok=True)
        data = {
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics,
        }
        with open(self._baseline_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_baseline(self) -> dict | None:
        """加载基线指标"""
        if not os.path.exists(self._baseline_path):
            return None
        try:
            with open(self._baseline_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def compare(self, current_metrics: dict,
                threshold: float = 0.05) -> dict:
        """
        对比当前指标与基线，低于阈值告警

        Returns:
            {
                "regression_detected": bool,
                "deltas": {metric: delta},
                "alerts": [str]
            }
        """
        baseline = self.load_baseline()
        if not baseline:
            return {
                "regression_detected": False,
                "deltas": {},
                "alerts": ["基线数据不存在，跳过回归检测"],
            }

        baseline_metrics = baseline.get("metrics", {})
        deltas = {}
        alerts = []

        for key in ["completion_rate", "tool_accuracy"]:
            current_val = current_metrics.get(key, 0)
            baseline_val = baseline_metrics.get(key, current_val)
            if baseline_val > 0:
                delta = (current_val - baseline_val) / baseline_val
                deltas[key] = round(delta, 4)
                if delta < -threshold:
                    alerts.append(
                        f"{key} 下降 {abs(delta)*100:.1f}%（阈值 {threshold*100}%），"
                        f"当前={current_val:.3f}, 基线={baseline_val:.3f}"
                    )

        return {
            "regression_detected": len(alerts) > 0,
            "deltas": deltas,
            "alerts": alerts,
        }
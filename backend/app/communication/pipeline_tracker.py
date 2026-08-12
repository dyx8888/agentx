"""
Pipeline Tracker - 串行流水线增强
- 流水线上下文传递：前一个Agent输出结构化传递给下一个Agent
- 流水线进度追踪
- 流水线可视化（Mermaid格式）
"""

from dataclasses import dataclass, field  # 数据类减少样板代码
from datetime import datetime  # 精确记录步骤执行时间
from enum import StrEnum  # 字符串枚举，便于序列化和日志输出


class PipelineStepStatus(StrEnum):
    WAITING = "waiting"  # 等待执行：步骤尚未开始
    RUNNING = "running"  # 正在执行：Agent 正在处理
    COMPLETED = "completed"  # 已完成：步骤成功完成
    FAILED = "failed"  # 失败：步骤执行出错
    SKIPPED = "skipped"  # 跳过：条件不满足或上游失败导致跳过


@dataclass
class PipelineContext:
    """流水线上下文 - 在Agent之间传递的结构化数据"""

    task_id: str = ""  # 关联的任务 ID
    upstream_output: dict = field(default_factory=dict)  # 上游 Agent 的原始输出
    key_findings: list[str] = field(default_factory=list)  # 上游提取的关键发现，注入下游 prompt
    recommendations: list[str] = field(default_factory=list)  # 上游给出的建议
    data_snapshots: dict = field(default_factory=dict)  # 上游数据快照，供下游参考
    errors_from_upstream: list[str] = field(default_factory=list)  # 上游警告信息，下游需注意
    shared_variables: dict = field(default_factory=dict)  # 跨步骤共享变量，如目标 URL、关键词等

    def to_dict(self) -> dict:
        return {  # 序列化为字典，便于 JSON 传输
            "task_id": self.task_id,
            "upstream_output": self.upstream_output,
            "key_findings": self.key_findings,
            "recommendations": self.recommendations,
            "data_snapshots": self.data_snapshots,
            "errors_from_upstream": self.errors_from_upstream,
            "shared_variables": self.shared_variables,
        }

    def to_prompt_context(self) -> str:
        """转为自然语言上下文，注入下游Agent"""
        parts = []
        if self.key_findings:
            parts.append("【上游Agent关键发现】\n" + "\n".join(f"- {f}" for f in self.key_findings))
        if self.recommendations:
            parts.append("【上游Agent建议】\n" + "\n".join(f"- {r}" for r in self.recommendations))
        if self.errors_from_upstream:
            parts.append(
                "【上游注意事项】\n" + "\n".join(f"- 警告: {e}" for e in self.errors_from_upstream)
            )  # 用警告前缀突出显示，下游 Agent 不会忽略
        if self.data_snapshots:
            parts.append(
                "【上游数据】\n" + "\n".join(f"- {k}: {v}" for k, v in self.data_snapshots.items())
            )
        return "\n\n".join(parts)  # 双换行分隔各段，确保 LLM 能正确解析


@dataclass
class PipelineStepState:
    """流水线步骤状态"""

    agent_name: str  # 执行的 Agent 名称
    step_index: int  # 步骤索引，从 0 开始
    status: PipelineStepStatus = PipelineStepStatus.WAITING  # 默认等待状态
    started_at: str = ""  # 开始时间戳
    completed_at: str = ""  # 完成时间戳
    duration_ms: float = 0.0  # 步骤耗时（毫秒），用于性能分析
    output_context: PipelineContext = field(default_factory=PipelineContext)  # 步骤产出，传递给下游
    error: str = ""  # 失败时的错误信息


@dataclass
class PipelineState:
    """流水线整体状态"""

    pipeline_id: str = ""  # 流水线唯一标识
    pipeline_name: str = ""  # 流水线名称
    steps: list[PipelineStepState] = field(default_factory=list)  # 所有步骤状态
    created_at: str = ""  # 流水线创建时间
    completed_at: str = ""  # 流水线完成时间
    total_duration_ms: float = 0.0  # 流水线总耗时（毫秒）


class PipelineTracker:
    """流水线进度追踪器"""

    def __init__(self):
        self._active_pipelines: dict[str, PipelineState] = {}  # 内存中追踪活跃流水线

    def create(self, pipeline_name: str, agents: list[str]) -> PipelineState:
        """创建流水线"""
        pipeline_id = f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"  # 时间戳生成唯一 ID
        state = PipelineState(
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
            steps=[
                PipelineStepState(
                    agent_name=name, step_index=i
                )  # 按顺序初始化步骤，每个 Agent 一个步骤
                for i, name in enumerate(agents)
            ],
            created_at=datetime.now().isoformat(),
        )
        self._active_pipelines[pipeline_id] = state  # 注册到活跃流水线
        return state

    def step_start(self, pipeline_id: str, step_index: int):
        """标记步骤开始"""
        state = self._active_pipelines.get(pipeline_id)
        if state and step_index < len(state.steps):  # 边界检查
            state.steps[step_index].status = PipelineStepStatus.RUNNING
            state.steps[step_index].started_at = datetime.now().isoformat()  # 记录开始时间

    def step_complete(self, pipeline_id: str, step_index: int, context: PipelineContext = None):
        """标记步骤完成"""
        state = self._active_pipelines.get(pipeline_id)
        if state and step_index < len(state.steps):
            step = state.steps[step_index]
            step.status = PipelineStepStatus.COMPLETED
            step.completed_at = datetime.now().isoformat()
            if step.started_at:  # 有开始时间才计算耗时，防御无效状态
                start = datetime.fromisoformat(step.started_at)
                step.duration_ms = (datetime.now() - start).total_seconds() * 1000  # 转为毫秒
            if context:
                step.output_context = context  # 保存步骤产出，供下游步骤获取

    def step_fail(self, pipeline_id: str, step_index: int, error: str):
        """标记步骤失败"""
        state = self._active_pipelines.get(pipeline_id)
        if state and step_index < len(state.steps):
            step = state.steps[step_index]
            step.status = PipelineStepStatus.FAILED
            step.error = error  # 记录错误信息，便于排查
            step.completed_at = datetime.now().isoformat()

    def get_status(self, pipeline_id: str) -> dict:
        """获取流水线进度状态"""
        state = self._active_pipelines.get(pipeline_id)
        if not state:
            return {"error": "Pipeline not found"}  # 流水线不存在时返回错误信息

        return {
            "pipeline_id": state.pipeline_id,
            "pipeline_name": state.pipeline_name,
            "created_at": state.created_at,
            "steps": [
                {
                    "agent": s.agent_name,
                    "index": s.step_index,
                    "status": s.status.value,  # 使用 .value 获取字符串值，而非枚举对象
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                }
                for s in state.steps
            ],
        }

    def generate_mermaid(self, pipeline_id: str) -> str:
        """生成Mermaid格式的流水线执行图（含耗时和状态）"""
        state = self._active_pipelines.get(pipeline_id)
        if not state or not state.steps:
            return "graph TD\n  A[Empty Pipeline]"  # 空流水线返回占位图

        lines = ["graph LR"]  # 从左到右的流程图，适合水平展示流水线
        status_icons = {  # 用 emoji 直观展示状态，Mermaid 渲染后可见
            PipelineStepStatus.COMPLETED: "✅",
            PipelineStepStatus.RUNNING: "🔄",
            PipelineStepStatus.FAILED: "❌",
            PipelineStepStatus.WAITING: "⏳",
            PipelineStepStatus.SKIPPED: "⛔",
        }

        for i, step in enumerate(state.steps):
            icon = status_icons.get(step.status, "❓")  # 未知状态使用问号
            duration = (
                f"<br/>{step.duration_ms:.0f}ms" if step.duration_ms else ""
            )  # 耗时显示在节点内
            node_id = f"S{i}"
            label = f"{icon} {step.agent_name}{duration}"
            style = ""
            if step.status == PipelineStepStatus.FAILED:
                style = ":::failed"  # 失败节点红色样式
            elif step.status == PipelineStepStatus.RUNNING:
                style = ":::running"  # 运行中节点黄色样式
            lines.append(f"    {node_id}[{label}]{style}")

        for i in range(len(state.steps) - 1):
            lines.append(f"    S{i} --> S{i + 1}")  # 串行连接各步骤

        lines.append("    classDef failed fill:#ffcccc,stroke:#dc3545")  # 定义失败节点样式
        lines.append("    classDef running fill:#fff3cd,stroke:#ffc107")  # 定义运行中节点样式

        return "\n".join(lines)


class MixedModeDispatcher:
    """混合模式分派器 - 支持主流程并行+子任务串行的混合编排
    9C.2: 实现混合模式支持
    """

    def __init__(self):
        self._pipeline_tracker = PipelineTracker()  # 复用流水线追踪器

    async def execute_hybrid(self, plan: dict[str, list[dict]]) -> dict:
        """
        执行混合模式：主流程并行 + 子任务串行

        Args:
            plan: {
                "parallel_groups": [
                    [{"agent": "A", "task": "..."}, {"agent": "B", "task": "..."}],
                    [{"agent": "C", "task": "..."}],
                ]
            }

        Returns:
            汇总结果
        """
        from app.communication.parallel import ParallelTask, get_parallel_dispatcher  # 延迟导入

        results = []
        parallel_groups = plan.get("parallel_groups", [])

        for _group_idx, group in enumerate(parallel_groups):
            if len(group) == 1:
                # 单个任务 → 串行执行：无需并行开销
                task = group[0]
                result = await self._execute_single(task)
                results.append(result)
            else:
                # 多个任务 → 并行执行：利用 asyncio.gather 加速
                parallel_tasks = [
                    ParallelTask(
                        target_agent=t.get("agent", ""),
                        task_description=t.get("task", ""),
                        task_type=t.get("type", "general"),
                    )
                    for t in group
                ]
                dispatcher = get_parallel_dispatcher()
                parallel_result = await dispatcher.dispatch(parallel_tasks)
                for r in parallel_result.tasks:
                    results.append(
                        {
                            "agent": r.task.target_agent,
                            "success": r.success,
                            "result": r.result,
                            "error": r.error,
                        }
                    )

        return {
            "total_groups": len(parallel_groups),
            "total_tasks": len(results),
            "completed": sum(1 for r in results if r.get("success")),
            "results": results,
        }

    async def execute_nested(self, plan: dict) -> dict:
        """
        执行嵌套模式：主Agent串行调用多个并行组

        Args:
            plan: {
                "master_agent": "orchestrator",
                "stages": [
                    {"type": "parallel", "tasks": [...]},
                    {"type": "serial", "task": {...}},
                ]
            }
        """
        results = []
        stages = plan.get("stages", [])

        for stage_idx, stage in enumerate(stages):
            stage_type = stage.get("type", "serial")
            if stage_type == "parallel":
                from app.communication.parallel import ParallelTask, get_parallel_dispatcher

                tasks = [
                    ParallelTask(
                        target_agent=t.get("agent", ""),
                        task_description=t.get("task", ""),
                    )
                    for t in stage.get("tasks", [])
                ]
                dispatcher = get_parallel_dispatcher()
                stage_result = await dispatcher.dispatch(tasks)
                results.append(
                    {
                        "stage": stage_idx,
                        "type": "parallel",
                        "completed": stage_result.completed,
                        "failed": stage_result.failed,
                        "tasks": [
                            {"agent": r.task.target_agent, "success": r.success}
                            for r in stage_result.tasks
                        ],
                    }
                )
            else:
                task = stage.get("task", {})
                result = await self._execute_single(task)
                results.append(
                    {  # 串行阶段结果
                        "stage": stage_idx,
                        "type": "serial",
                        "success": result.get("success"),
                        "result": result,
                    }
                )

        return {
            "master_agent": plan.get("master_agent"),
            "total_stages": len(stages),
            "results": results,
        }

    async def _execute_single(self, task: dict) -> dict:
        """执行单个任务"""
        try:
            from app.communication.a2a_adapter import get_a2a_adapter  # 延迟导入

            adapter = get_a2a_adapter()
            return adapter.send_task(
                target_agent_name=task.get("agent", ""),
                task_description=task.get("task", ""),
                task_type=task.get("type", "general"),
            )
        except Exception as e:
            return {"success": False, "error": str(e)}  # 失败时返回错误信息而非抛异常

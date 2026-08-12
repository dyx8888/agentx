"""
Parallel Agent Execution - 并行Agent分派与结果汇总
支持 asyncio.gather 并行分派、全局超时、部分失败容错
"""

import asyncio  # 并行执行的核心：asyncio.gather 并发调度多个协程
import json  # 冲突检测时序列化结果进行文本比对
from dataclasses import dataclass, field  # 数据类减少样板代码
from datetime import datetime  # 精确记录任务执行时间，计算耗时

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PARALLEL_TIMEOUT = 60  # 默认全局超时秒数，并行任务应在 60 秒内全部完成


@dataclass
class ParallelTask:
    """并行任务定义"""

    target_agent: str  # 目标 Agent 名称
    task_description: str  # 任务描述
    task_type: str = "general"  # 任务类型，用于路由
    priority: int = 0  # 优先级，数值越大越优先（预留接口）
    context: dict = field(default_factory=dict)  # 上下文数据，传递给 Agent


@dataclass
class ParallelTaskResult:
    """并行任务执行结果"""

    task: ParallelTask  # 关联原始任务
    task_id: str = ""  # A2A 任务 ID
    success: bool = False  # 执行是否成功
    result: dict = field(default_factory=dict)  # Agent 返回的原始结果
    error: str = ""  # 错误信息
    started_at: str = ""  # 开始时间
    completed_at: str = ""  # 完成时间
    duration_ms: float = 0.0  # 执行耗时（毫秒），用于性能分析


@dataclass
class ParallelExecutionResult:
    """并行执行汇总结果"""

    tasks: list[ParallelTaskResult]  # 所有任务结果
    total_tasks: int = 0  # 总任务数
    completed: int = 0  # 成功数
    failed: int = 0  # 失败数
    timed_out: int = 0  # 超时数
    total_duration_ms: float = 0.0  # 总耗时（毫秒）
    partial_failure: bool = False  # 是否有部分任务失败，便于调用方决定是否继续


class ParallelAgentDispatcher:
    """并行Agent分派器 - 使用 asyncio.gather 并行执行多个任务"""

    def __init__(self, a2a_adapter=None, global_timeout: float = DEFAULT_PARALLEL_TIMEOUT):
        self._a2a = a2a_adapter  # A2A 适配器，用于 Agent 间通信
        self._global_timeout = global_timeout  # 全局超时，防止某个慢任务拖垮整体

    async def dispatch(self, tasks: list[ParallelTask]) -> ParallelExecutionResult:
        """
        并行分派任务到多个Agent

        Args:
            tasks: 并行任务列表

        Returns:
            ParallelExecutionResult 汇总结果
        """
        if not tasks:
            return ParallelExecutionResult(tasks=[], total_tasks=0)  # 空任务列表直接返回空结果

        start_time = datetime.utcnow()

        logger.info(
            "parallel_dispatch_start",
            task_count=len(tasks),
            agents=[t.target_agent for t in tasks],
        )

        try:
            # 使用 asyncio.gather 并行执行，return_exceptions=True 实现部分失败容错
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[self._execute_single_task(t) for t in tasks],  # 所有任务同时启动
                    return_exceptions=True,  # 单个任务异常不中断其他任务
                ),
                timeout=self._global_timeout,  # 全局超时保护
            )
        except TimeoutError:
            logger.warning("parallel_dispatch_timeout", task_count=len(tasks))
            # 超时后返回已完成的任务结果
            return ParallelExecutionResult(
                tasks=[],  # asyncio.wait_for 超时后无法获取部分结果
                total_tasks=len(tasks),
                failed=0,
                timed_out=len(tasks),  # 所有任务均标记为超时
                total_duration_ms=self._global_timeout * 1000,
                partial_failure=True,
            )

        # 处理结果
        task_results: list[ParallelTaskResult] = []
        for i, result in enumerate(results):
            task = tasks[i]
            if isinstance(result, Exception):  # return_exceptions=True 时异常不抛出，需要手动检查
                task_results.append(
                    ParallelTaskResult(
                        task=task,
                        success=False,
                        error=str(result),
                        partial_failure=True,
                    )
                )
            else:
                task_results.append(result)

        completed = sum(1 for r in task_results if r.success)
        failed = sum(1 for r in task_results if not r.success)

        total_duration = (datetime.utcnow() - start_time).total_seconds() * 1000  # 精确到毫秒

        logger.info(
            "parallel_dispatch_complete",
            total=len(task_results),
            completed=completed,
            failed=failed,
            duration_ms=total_duration,
        )

        return ParallelExecutionResult(
            tasks=task_results,
            total_tasks=len(task_results),
            completed=completed,
            failed=failed,
            timed_out=0,  # 非超时路径，超时数由 TimeoutError 分支处理
            total_duration_ms=total_duration,
            partial_failure=failed > 0,  # 有失败即标记为部分失败
        )

    async def _execute_single_task(self, task: ParallelTask) -> ParallelTaskResult:
        """执行单个任务"""
        started_at = datetime.utcnow()

        try:
            if self._a2a:  # 有 A2A 适配器时通过 A2A 协议发送任务
                result = self._a2a.send_task(
                    target_agent_name=task.target_agent,
                    task_description=task.task_description,
                    task_type=task.task_type,
                )

                if result.get("success"):
                    task_id = result.get("task_id", "")
                    completed_at = datetime.utcnow()
                    return ParallelTaskResult(
                        task=task,
                        task_id=task_id,
                        success=True,
                        result=result,
                        started_at=started_at.isoformat(),
                        completed_at=completed_at.isoformat(),
                        duration_ms=(completed_at - started_at).total_seconds()
                        * 1000,  # 精确计算单个任务耗时
                    )
                else:
                    return ParallelTaskResult(
                        task=task,
                        success=False,
                        error=result.get("error", "Unknown error"),
                        started_at=started_at.isoformat(),
                    )
            else:
                return ParallelTaskResult(
                    task=task,
                    success=False,
                    error="A2A adapter not available",  # 无 A2A 适配器时无法执行
                    started_at=started_at.isoformat(),
                )

        except Exception as e:
            logger.error("parallel_single_task_error", agent=task.target_agent, error=str(e))
            return ParallelTaskResult(
                task=task,
                success=False,
                error=str(e),
                started_at=started_at.isoformat(),
            )

    def deduplicate_results(self, results: list[ParallelTaskResult]) -> list[dict]:
        """结果去重：合并相同目标Agent的多个结果"""
        agent_results: dict[str, list[ParallelTaskResult]] = {}
        for r in results:
            agent_results.setdefault(r.task.target_agent, []).append(r)  # 按 Agent 分组

        merged = []
        for agent_name, agent_tasks in agent_results.items():
            successes = [r for r in agent_tasks if r.success]
            failures = [r for r in agent_tasks if not r.success]
            merged.append(
                {  # 汇总每个 Agent 的执行情况
                    "agent": agent_name,
                    "total_tasks": len(agent_tasks),
                    "completed": len(successes),
                    "failed": len(failures),
                    "results": [r.result for r in successes],
                    "errors": [r.error for r in failures if r.error],
                }
            )
        return merged

    def detect_conflicts(self, results: list[ParallelTaskResult]) -> list[dict]:
        """冲突检测：检查并行任务结果之间是否存在冲突"""
        conflicts = []

        # 检查是否有多个Agent返回了冲突的结论
        success_results = [r for r in results if r.success]  # 仅检查成功的结果，失败的结果无意义
        for i in range(len(success_results)):
            for j in range(i + 1, len(success_results)):  # 两两比较，避免重复检查
                r1, r2 = success_results[i], success_results[j]
                conflict = self._check_pair_conflict(r1, r2)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    def _check_pair_conflict(self, r1: ParallelTaskResult, r2: ParallelTaskResult) -> dict | None:
        """检查两个任务结果之间是否存在冲突"""
        result1 = r1.result
        result2 = r2.result

        # 简单冲突检测：检查是否有相互矛盾的关键词
        conflicting_keywords = {  # 预设的矛盾关键词对，用于快速判断
            ("approved", "rejected"),  # 一个说通过，一个说拒绝
            ("increase", "decrease"),  # 一个说增加，一个说减少
            ("buy", "sell"),  # 一个说买，一个说卖
            ("over", "under"),  # 一个说超过，一个说低于
        }

        text1 = json.dumps(result1, ensure_ascii=False).lower()  # 转小写后比较，避免大小写差异
        text2 = json.dumps(result2, ensure_ascii=False).lower()

        for kw1, kw2 in conflicting_keywords:
            if kw1 in text1 and kw2 in text2:  # Agent1 包含 kw1 且 Agent2 包含 kw2
                return {
                    "type": "conflicting_conclusion",
                    "agent1": r1.task.target_agent,
                    "agent2": r2.task.target_agent,
                    "keyword1": kw1,
                    "keyword2": kw2,
                    "description": f"Agent {r1.task.target_agent} 和 {r2.task.target_agent} 返回了矛盾结论",
                }

        return None  # 无冲突


# ── 全局实例 ──────────────────────────────────────

_parallel_dispatcher: ParallelAgentDispatcher | None = None  # 模块级单例，延迟初始化


def get_parallel_dispatcher(a2a_adapter=None) -> ParallelAgentDispatcher:
    """获取全局并行分派器实例"""
    global _parallel_dispatcher
    if _parallel_dispatcher is None:
        _parallel_dispatcher = ParallelAgentDispatcher(a2a_adapter=a2a_adapter)  # 首次调用时创建
    return _parallel_dispatcher


def a2a_delegate_parallel(tasks: list[dict]) -> list[dict]:
    """
    并行委派工具函数 - 供Agent调用

    Args:
        tasks: 任务列表，每个任务包含 target_agent, task_description, task_type

    Returns:
        并行执行结果列表

    Example:
        >>> a2a_delegate_parallel([
        ...     {"target_agent": "brand_bd", "task_description": "分析竞品"},
        ...     {"target_agent": "product_selector", "task_description": "推荐产品"},
        ... ])
    """
    try:
        parallel_tasks = [
            ParallelTask(
                target_agent=t.get("target_agent", ""),
                task_description=t.get("task_description", ""),
                task_type=t.get("task_type", "general"),
                priority=t.get("priority", 0),
                context=t.get("context", {}),
            )
            for t in tasks
        ]

        from app.communication.a2a_adapter import get_a2a_adapter  # 延迟导入避免循环依赖

        adapter = get_a2a_adapter()
        dispatcher = get_parallel_dispatcher(a2a_adapter=adapter)

        loop = asyncio.get_event_loop()
        if loop.is_running():  # 已在事件循环中（如 FastAPI 请求处理），通过线程安全方式调度
            future = asyncio.run_coroutine_threadsafe(  # 线程安全地将协程提交到运行中的事件循环
                dispatcher.dispatch(parallel_tasks), loop
            )
            result = future.result(timeout=DEFAULT_PARALLEL_TIMEOUT)  # 阻塞等待结果，带超时
        else:
            result = asyncio.run(dispatcher.dispatch(parallel_tasks))  # 无事件循环时直接运行

        return [
            {
                "agent": r.task.target_agent,
                "task_id": r.task_id,
                "success": r.success,
                "result": r.result,
                "error": r.error,
                "duration_ms": r.duration_ms,
            }
            for r in result.tasks
        ]

    except Exception as e:
        logger.error("a2a_delegate_parallel_failed", error=str(e))
        return [{"error": str(e)}]  # 返回错误信息而非抛出异常，供 Agent 优雅处理

"""
HierarchicalOrchestrator - 分层Agent编排（金字塔模式）
支持多层嵌套：总指挥→组长→组员，最大3层
"""

import asyncio  # 分层编排中每层内部任务并行执行，需要 asyncio 协程管理
import json  # 层间传递结构化数据（摘要）使用 JSON 格式
from dataclasses import (  # dataclass 减少样板代码，SubTask/SubTaskResult 是纯数据结构
    dataclass,
    field,
)
from datetime import datetime  # 记录任务执行时间戳，用于耗时统计
from enum import StrEnum  # 字符串枚举，便于序列化和日志输出
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_HIERARCHY_DEPTH = 3  # 限制最大 3 层，防止任务无限嵌套导致系统资源耗尽
DEFAULT_LAYER_TIMEOUT = 30  # 每层默认超时秒数，平衡响应速度和复杂任务完成时间


@dataclass
class SubTask:
    """子任务定义"""

    id: str = ""  # 子任务唯一标识，用于结果匹配
    description: str = ""  # 任务描述，传递给执行 Agent
    assigned_agent: str = ""  # 目标 Agent 名称
    context: dict = field(default_factory=dict)  # 上下文数据，层间传递的关键信息
    parent_task_id: str = ""  # 父任务 ID，用于构建任务树
    depth: int = 0  # 当前深度，用于防止无限嵌套


@dataclass
class SubTaskResult:
    """子任务执行结果"""

    task: SubTask  # 关联原始任务，便于回溯
    status: str = "pending"  # 执行状态：pending/completed/failed
    output: dict = field(default_factory=dict)  # Agent 返回的原始输出
    summary: str = ""  # 结构化摘要，供上层 Agent 消费
    error: str = ""  # 错误信息，失败时填充
    started_at: str = ""  # 开始时间戳
    completed_at: str = ""  # 完成时间戳
    agent_name: str = ""  # 实际执行的 Agent 名称


class HierarchicalOrchestrator:
    """分层编排器 - 支持多层嵌套的Agent协作"""

    def __init__(self, a2a_adapter=None, max_depth: int = MAX_HIERARCHY_DEPTH):
        self._a2a = a2a_adapter  # A2A 适配器用于 Agent 间通信，可选注入便于测试
        self._max_depth = max_depth  # 最大嵌套深度，从全局常量获取
        self._layer_timeouts: dict[int, float] = {}  # 每层可独立配置超时，深层次可设更短超时

    def set_layer_timeout(self, depth: int, timeout: float):
        """设置指定层的超时时间"""
        self._layer_timeouts[depth] = timeout  # 浅层任务通常更简单，可设更短超时

    def get_layer_timeout(self, depth: int) -> float:
        """获取指定层的超时时间"""
        return self._layer_timeouts.get(depth, DEFAULT_LAYER_TIMEOUT)  # 未配置时使用默认值

    async def execute(
        self,
        tasks: list[SubTask],
        current_depth: int = 0,
    ) -> dict[str, Any]:
        """
        分层执行任务

        Args:
            tasks: 子任务列表
            current_depth: 当前层级深度

        Returns:
            执行结果汇总
        """
        if current_depth >= self._max_depth:  # 达到最大深度时不再递归，直接合并任务
            logger.warning(
                "hierarchical_max_depth_reached",
                depth=current_depth,
                max_depth=self._max_depth,
            )
            return self._merge_at_depth(tasks)  # 合并后返回，避免无限递归

        logger.info(
            "hierarchical_layer_start",
            depth=current_depth,
            task_count=len(tasks),
        )

        layer_timeout = self.get_layer_timeout(current_depth)

        try:
            results = await asyncio.wait_for(  # 整层统一超时，防止单个任务卡死整层
                asyncio.gather(
                    *[self._execute_subtask(t, current_depth) for t in tasks],  # 层内任务并行执行
                    return_exceptions=True,  # 单个任务失败不影响其他任务
                ),
                timeout=layer_timeout,
            )
        except TimeoutError:
            logger.warning("hierarchical_layer_timeout", depth=current_depth)
            return {  # 超时时返回部分结果，不抛异常
                "status": "timeout",
                "depth": current_depth,
                "completed_tasks": 0,
                "total_tasks": len(tasks),
                "results": [],
            }

        task_results = []
        for i, result in enumerate(results):
            task = tasks[i]
            if isinstance(result, Exception):  # return_exceptions=True 时异常作为结果返回
                task_results.append(
                    SubTaskResult(
                        task=task,
                        status="failed",
                        error=str(result),
                    )
                )
            else:
                task_results.append(result)

        completed = sum(1 for r in task_results if r.status == "completed")
        failed = sum(1 for r in task_results if r.status == "failed")

        logger.info(
            "hierarchical_layer_complete",
            depth=current_depth,
            completed=completed,
            failed=failed,
        )

        return {
            "status": "completed"
            if failed == 0
            else "partial",  # 部分失败也返回 partial，不丢弃成功结果
            "depth": current_depth,
            "completed_tasks": completed,
            "total_tasks": len(tasks),
            "results": [
                {
                    "task_id": r.task.id,
                    "agent": r.agent_name,
                    "status": r.status,
                    "summary": r.summary,
                    "error": r.error,
                }
                for r in task_results
            ],
        }

    async def _execute_subtask(self, task: SubTask, depth: int) -> SubTaskResult:
        """执行单个子任务"""
        result = SubTaskResult(
            task=task,
            agent_name=task.assigned_agent,
            started_at=datetime.utcnow().isoformat(),
        )

        if task.depth > depth:  # 防御性检查：子任务深度不应超过当前层深度
            logger.warning(
                "hierarchical_depth_mismatch",
                task_depth=task.depth,
                current_depth=depth,
            )
            result.status = "failed"
            result.error = f"Task depth {task.depth} exceeds current layer {depth}"
            return result

        try:
            if self._a2a:  # 有 A2A 适配器时通过 A2A 协议发送任务给 Agent
                a2a_result = self._a2a.send_task(
                    target_agent_name=task.assigned_agent,
                    task_description=task.description,
                    task_type="subtask",  # 标记为子任务类型，便于 Agent 区分处理
                )

                if a2a_result.get("success"):
                    result.status = "completed"
                    result.output = a2a_result
                    result.summary = self._generate_summary(
                        task, a2a_result
                    )  # 生成结构化摘要供上层消费
                else:
                    result.status = "failed"
                    result.error = a2a_result.get("error", "Unknown error")
            else:
                result.status = "failed"
                result.error = "A2A adapter not available"  # 无 A2A 适配器时无法执行

        except Exception as e:
            result.status = "failed"
            result.error = str(e)

        result.completed_at = datetime.utcnow().isoformat()
        return result

    def _generate_summary(self, task: SubTask, result: dict) -> str:
        """生成结构化摘要（JSON格式，供上层Agent消费）"""
        summary = {
            "task_id": task.id,
            "agent": task.assigned_agent,
            "description": task.description[:100],  # 截断至 100 字符，摘要不宜过长
            "status": "completed",
            "key_findings": result.get("response", "")[:200],  # 只保留前 200 字符的关键发现
            "timestamp": datetime.utcnow().isoformat(),
        }
        return json.dumps(summary, ensure_ascii=False)  # 返回 JSON 字符串，便于上层解析

    def _merge_at_depth(self, tasks: list[SubTask]) -> dict:
        """达到最大深度时，自动合并子任务"""
        logger.info("hierarchical_auto_merge", task_count=len(tasks))
        merged_description = "; ".join(t.description for t in tasks)  # 所有子任务描述拼接
        return {
            "status": "merged",
            "merged_description": merged_description,
            "original_tasks": len(tasks),
            "suggestion": "任务已自动合并，建议由单一Agent处理",  # 提示调用方需要降级处理
        }

    def build_subtask_tree(self, task_description: str, agents: list[str]) -> list[SubTask]:
        """构建子任务树：根据任务描述和可用Agent列表自动生成子任务"""
        subtasks = []
        for i, agent in enumerate(agents):  # 每个 Agent 分配一个子任务
            subtasks.append(
                SubTask(
                    id=f"subtask_{i + 1}",
                    description=f"[{agent}] {task_description}",  # 描述中带上 Agent 名，便于追踪
                    assigned_agent=agent,
                    depth=1,  # 初始深度为 1，根任务深度为 0
                    parent_task_id="root",  # 根节点标记
                )
            )
        return subtasks


# ── Collaboration Mode Selector ──────────────────────


# 字符串枚举确保协作模式值可以直接序列化到 JSON 响应中
class CollaborationMode(StrEnum):
    SERIAL = "serial"  # 串行：任务依次执行，适合有依赖关系的步骤
    PARALLEL = "parallel"  # 并行：独立任务同时执行，加快总耗时
    MASTER_SLAVE = "master_slave"  # 主从：主 Agent 调度多个从 Agent
    HIERARCHICAL = "hierarchical"  # 分层：金字塔式多层嵌套编排


@dataclass
class TaskCharacteristics:
    """任务特征分析结果"""

    complexity: float = 0.0  # 1-10 复杂度评分，LLM 评估得出
    independent_subtasks: int = 0  # 可独立并行执行的子任务数量
    requires_dynamic_scheduling: bool = False  # 是否需要根据中间结果动态调整计划
    cross_domain: bool = False  # 是否跨领域，跨领域任务适合分层模式
    estimated_steps: int = 0  # 预估完成步骤数


class CollaborationModeSelector:
    """协作模式选择器 - 基于任务特征自动推荐协作模式"""

    def select(self, characteristics: TaskCharacteristics) -> CollaborationMode:
        """
        基于任务特征自动选择协作模式

        Args:
            characteristics: 任务特征

        Returns:
            推荐的协作模式
        """
        # 超大工程 + 跨领域 → 分层模式：需要多个专业团队协调
        if characteristics.complexity > 7 and characteristics.cross_domain:
            return CollaborationMode.HIERARCHICAL

        # 动态调度需求 → 主从模式：主 Agent 根据中间结果动态分配
        if characteristics.requires_dynamic_scheduling:
            return CollaborationMode.MASTER_SLAVE

        # 独立子任务多 → 并行模式：互不依赖的任务可以同时执行
        if characteristics.independent_subtasks >= 3:
            return CollaborationMode.PARALLEL

        # 复杂度低、步骤固定 → 串行模式：简单任务串行更可控
        if characteristics.complexity < 4 and characteristics.estimated_steps <= 5:
            return CollaborationMode.SERIAL

        # 默认：主从模式，最通用的协作方式
        return CollaborationMode.MASTER_SLAVE

    def analyze_task(self, task_description: str) -> TaskCharacteristics:
        """
        分析任务特征（基于LLM评分）

        Args:
            task_description: 任务描述

        Returns:
            TaskCharacteristics
        """
        try:
            from langchain_core.messages import (  # 使用 LangChain 消息格式
                HumanMessage,
                SystemMessage,
            )

            from app.services.model_gateway import get_global_model_gateway

            model_gateway = get_global_model_gateway()
            llm = model_gateway.get_llm()

            system_prompt = """你是一个任务分析专家。请分析以下任务的特征，返回JSON格式：

{
  "complexity": 1-10的复杂度评分,
  "independent_subtasks": 可独立执行的子任务数量,
  "requires_dynamic_scheduling": true/false,
  "cross_domain": true/false,
  "estimated_steps": 预估需要多少步骤完成
}

评分标准：
- complexity: 1-3简单查询，4-6中等分析，7-10复杂任务
- cross_domain: 是否需要多个不同领域的专业知识
- requires_dynamic_scheduling: 是否需要根据中间结果动态调整计划"""

            response = llm.invoke(
                [  # 调用 LLM 进行任务特征分析
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=task_description),
                ]
            )

            content = (
                response.content if hasattr(response, "content") else str(response)
            )  # 兼容不同 LLM 返回格式

            import re

            json_match = re.search(r"\{[\s\S]*\}", content)  # 从 LLM 输出中提取 JSON，容错处理
            if json_match:
                data = json.loads(json_match.group(0))
                return TaskCharacteristics(
                    complexity=float(data.get("complexity", 5)),  # 默认中等复杂度 5
                    independent_subtasks=int(data.get("independent_subtasks", 1)),
                    requires_dynamic_scheduling=bool(
                        data.get("requires_dynamic_scheduling", False)
                    ),
                    cross_domain=bool(data.get("cross_domain", False)),
                    estimated_steps=int(data.get("estimated_steps", 3)),
                )
        except Exception as e:
            logger.warning("task_analysis_failed", error=str(e))  # LLM 分析失败时使用默认值

        return TaskCharacteristics()  # 返回全默认值，不阻塞主流程

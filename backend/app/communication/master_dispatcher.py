"""
MasterDispatcher — master 委派调度器

变更② T2.4：master 编排重构的委派核心。

职责（对应 02-主Agent编排重构.md 第 4.4 节）：
  1. decompose — 用 master 的 system_prompt 把用户意图拆解为子任务，
     并判定每个子任务是 master 自己做还是委派给某个专业子 Agent
  2. dispatch  — 按 depends_on 拓扑调度：无依赖子任务并行（asyncio.gather），
     有依赖子任务等待前序完成；委派走 A2A，master 自己的走 ReAct
  3. review    — 格式校验 + LLM 验收（对比原始意图），不合格标记重试（最多 2 次）

设计约束：
  - 所有重依赖（ModelGateway / AgentRuntime / A2A adapter / 子 Agent 模块）延迟获取，
    模块导入不触发任何网络/DB/模型加载，保证 `from ... import MasterDispatcher` 可用
  - 任一依赖不可用都优雅降级，不抛异常阻断主流程
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.core.logging import get_logger
from app.perception.context_package import ContextPackage

logger = get_logger(__name__)

# 审查不合格时的最大重试次数
MAX_REVIEW_RETRIES = 2
# A2A 委派任务类型标记，便于目标 Agent 区分子任务调用
DELEGATION_TASK_TYPE = "subtask"


class SubTaskStatus(StrEnum):
    """子任务执行状态。"""

    PENDING = "pending"  # 已创建，等待调度
    RUNNING = "running"  # 执行中
    COMPLETED = "completed"  # 成功完成
    FAILED = "failed"  # 执行失败
    SKIPPED = "skipped"  # 前序依赖失败被跳过


@dataclass
class SubTask:
    """master 拆解出的子任务定义。

    agent_name 为 None（或 "master"）表示 master 自己执行，不委派。
    depends_on 引用其它 SubTask.task_id，构成 DAG。
    """

    task_id: str
    description: str
    agent_name: str | None = None  # None → master 自己做
    priority: int = 0  # 数值越大越优先（同一就绪批次内排序）
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SubTaskResult:
    """子任务执行结果。"""

    task_id: str
    agent_name: str | None = None
    status: str = SubTaskStatus.PENDING
    success: bool = False
    output: dict = field(default_factory=dict)  # 原始返回（A2A/Runtime）
    summary: str = ""  # 供汇总/上层消费的摘要
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0.0


@dataclass
class ReviewResult:
    """审查结论。"""

    passed: bool = False
    needs_retry: bool = False
    retry_count: int = 0
    final_output: str = ""  # 合格时综合输出
    issues: list[str] = field(default_factory=list)
    failed_task_ids: list[str] = field(default_factory=list)


class MasterDispatcher:
    """master 委派调度器。

    使用方式（T2.5 chat 入口 / MasterAgentRouter 调用）:
        dispatcher = MasterDispatcher()
        subtasks = await dispatcher.decompose(context)
        results = await dispatcher.dispatch(subtasks)
        review = await dispatcher.review(results)
        # 或一步到位（含重试循环）:
        outcome = await dispatcher.orchestrate(context)
    """

    def __init__(self, model_gateway=None, a2a_adapter=None, agent_runtime=None):
        """构造函数，所有依赖可注入（便于测试），默认延迟获取。"""
        self._model_gateway = model_gateway
        self._a2a_adapter = a2a_adapter
        self._agent_runtime = agent_runtime
        # decompose 时缓存 context，供 dispatch（company_id）与 review（原始意图）使用，
        # 因为 dispatch/review 的签名按规格只接收 subtasks/results
        self._context: ContextPackage | None = None
        self._review_attempts = 0

    # ==================== 1. 任务拆解 ====================

    async def decompose(self, context: ContextPackage) -> list[SubTask]:
        """将用户意图拆解为子任务，并判定委派目标。

        优先用 LLM（master system_prompt）拆解；LLM 不可用时退化为关键词路由。
        """
        self._context = context
        self._review_attempts = 0  # 重置审查计数，避免实例复用时串状态

        query = (context.rewritten_query or context.raw_input or "").strip()
        if not query:
            return []

        # available_agents 为空时回退到全量注册表
        available_agents = context.available_agents or self._all_agent_keys()

        subtasks = await self._llm_decompose(query, available_agents)
        if subtasks:
            logger.info("master_decompose_llm", count=len(subtasks))
            return subtasks

        # 降级：关键词路由
        subtasks = self._fallback_decompose(query)
        logger.info("master_decompose_fallback", count=len(subtasks))
        return subtasks

    async def _llm_decompose(self, query: str, available_agents: list[str]) -> list[SubTask]:
        """用 master 的 system_prompt 让 LLM 输出 JSON 子任务列表。"""
        try:
            from app.agents.master import MASTER_SYSTEM_PROMPT

            base_prompt = MASTER_SYSTEM_PROMPT
        except Exception:
            base_prompt = "你是 AgentX 主协调器，负责拆解用户任务并决定委派给哪个子 Agent。"

        agents_desc = self._format_available_agents(available_agents)
        system_prompt = (
            base_prompt
            + f"""

## 任务拆解输出要求
请将用户请求拆解为子任务，并仅以 JSON 返回（不要输出多余文字）：
{{
  "subtasks": [
    {{"task_id": "t1", "description": "子任务描述", "agent_name": "子Agent键名或null", "priority": 1, "depends_on": []}}
  ]
}}

可委派的子 Agent（agent_name 必须取自下列键名；简单任务用 null 表示由你自己完成）：
{agents_desc}

拆解原则：
- 简单单步任务：仅 1 个子任务，agent_name=null
- 需要专业能力：委派给对应子 Agent
- 有依赖的子任务用 depends_on 引用前序 task_id
- 无依赖的子任务 depends_on 为空数组（将并行执行）
"""
        )
        content = await self._llm_complete(system_prompt, f"用户请求：{query}")
        data = self._extract_json(content)
        if not data:
            return []
        return self._parse_subtasks(data.get("subtasks", []), available_agents)

    def _parse_subtasks(self, raw: Any, available_agents: list[str]) -> list[SubTask]:
        """校验并规整 LLM 输出的子任务列表。"""
        if not isinstance(raw, list):
            return []

        valid_agents = set(available_agents) & set(self._all_agent_keys())
        subtasks: list[SubTask] = []
        seen_ids: set[str] = set()

        for i, item in enumerate(raw, 1):
            if not isinstance(item, dict):
                continue
            desc = str(item.get("description", "")).strip()
            if not desc:
                continue

            tid = str(item.get("task_id") or f"t{i}")
            if tid in seen_ids:
                tid = f"{tid}_{i}"
            seen_ids.add(tid)

            # 非法/未知 agent 一律降级为 master 自己做，避免委派给不存在的 Agent
            agent = item.get("agent_name")
            if agent not in valid_agents:
                agent = None

            depends = [str(d) for d in (item.get("depends_on") or []) if d]

            try:
                priority = int(item.get("priority", 0))
            except (TypeError, ValueError):
                priority = 0

            subtasks.append(
                SubTask(
                    task_id=tid,
                    description=desc,
                    agent_name=agent,
                    priority=priority,
                    depends_on=depends,
                )
            )

        # 清洗 depends_on：剔除指向不存在任务或自引用的依赖，防止调度死锁
        valid_ids = {t.task_id for t in subtasks}
        for t in subtasks:
            t.depends_on = [d for d in t.depends_on if d in valid_ids and d != t.task_id]

        return subtasks

    def _fallback_decompose(self, query: str) -> list[SubTask]:
        """LLM 不可用时的降级拆解：复用 master 的关键词意图识别。"""
        try:
            from app.agents.master import decompose_task, recognize_intent
        except Exception:
            return [SubTask(task_id="t1", description=query, agent_name=None, priority=1)]

        intent = recognize_intent(query)
        if intent == "master":
            return [SubTask(task_id="t1", description=query, agent_name=None, priority=1)]

        agent_names = intent if isinstance(intent, list) else [intent]
        raw_subtasks = decompose_task(query, agent_names)

        subtasks: list[SubTask] = []
        total = len(raw_subtasks)
        # 关键词路由无法可靠判断依赖关系，统一设为无依赖（并行），按出现顺序赋优先级
        for i, st in enumerate(raw_subtasks, 1):
            subtasks.append(
                SubTask(
                    task_id=f"t{i}",
                    description=st.get("description", query),
                    agent_name=st.get("agent"),
                    priority=total - i + 1,
                    depends_on=[],
                )
            )
        return subtasks

    # ==================== 2. 调度执行 ====================

    async def dispatch(self, subtasks: list[SubTask]) -> dict[str, SubTaskResult]:
        """按依赖拓扑调度子任务。

        每一轮挑出"所有依赖均已成功完成"的就绪任务并行执行；
        依赖已解析但前序失败的任务标记 SKIPPED；
        无就绪也无可跳过任务则判定为循环依赖，安全退出。
        """
        if not subtasks:
            return {}

        task_map: dict[str, SubTask] = {t.task_id: t for t in subtasks}
        results: dict[str, SubTaskResult] = {}
        remaining: set[str] = set(task_map.keys())

        while remaining:
            ready = [
                tid
                for tid in remaining
                if all(dep in results and results[dep].success for dep in task_map[tid].depends_on)
            ]

            if not ready:
                # 依赖已全部出结果但存在失败 → 这些任务无法执行，跳过
                blocked = [
                    tid
                    for tid in remaining
                    if all(dep in results for dep in task_map[tid].depends_on)
                ]
                if blocked:
                    for tid in blocked:
                        results[tid] = SubTaskResult(
                            task_id=tid,
                            agent_name=task_map[tid].agent_name,
                            status=SubTaskStatus.SKIPPED,
                            error="前序依赖失败，子任务跳过",
                        )
                        remaining.discard(tid)
                    continue
                # 既无就绪也无可跳过 → 循环依赖或悬空依赖，避免死循环
                for tid in remaining:
                    results[tid] = SubTaskResult(
                        task_id=tid,
                        agent_name=task_map[tid].agent_name,
                        status=SubTaskStatus.FAILED,
                        error="依赖无法满足（可能存在循环依赖）",
                    )
                logger.warning("master_dispatch_deadlock", remaining=list(remaining))
                break

            # 同一就绪批次内按优先级降序，再并行执行
            ready.sort(key=lambda tid: task_map[tid].priority, reverse=True)
            batch = await asyncio.gather(
                *[self._execute_subtask(task_map[tid], results) for tid in ready],
                return_exceptions=True,
            )

            for tid, res in zip(ready, batch, strict=False):
                if isinstance(res, Exception):
                    results[tid] = SubTaskResult(
                        task_id=tid,
                        agent_name=task_map[tid].agent_name,
                        status=SubTaskStatus.FAILED,
                        error=str(res),
                    )
                else:
                    results[tid] = res
                remaining.discard(tid)

        return results

    async def _execute_subtask(
        self,
        task: SubTask,
        results: dict[str, SubTaskResult],
    ) -> SubTaskResult:
        """执行单个子任务：委派走 A2A，master 自己的走 ReAct。"""
        started = datetime.utcnow()
        res = SubTaskResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status=SubTaskStatus.RUNNING,
            started_at=started.isoformat(),
        )

        try:
            if task.agent_name and task.agent_name != "master":
                out = await self._delegate(task, results)
            else:
                out = await self._master_execute(task, results)

            res.output = out if isinstance(out, dict) else {"result": str(out)}
            has_error = bool(res.output.get("error"))
            res.success = bool(res.output.get("success", True)) and not has_error
            res.summary = (
                res.output.get("summary")
                or res.output.get("response")
                or res.output.get("result")
                or ""
            )
            if res.success:
                res.status = SubTaskStatus.COMPLETED
            else:
                res.status = SubTaskStatus.FAILED
                res.error = res.output.get("error", "执行未成功")
        except Exception as e:
            res.status = SubTaskStatus.FAILED
            res.error = str(e)
            logger.warning("master_subtask_failed", task_id=task.task_id, error=str(e))

        completed = datetime.utcnow()
        res.completed_at = completed.isoformat()
        res.duration_ms = (completed - started).total_seconds() * 1000
        return res

    async def _delegate(self, task: SubTask, results: dict[str, SubTaskResult]) -> dict:
        """通过 A2A 协议把子任务委派给目标 Agent。"""
        adapter = self._get_a2a_adapter()
        if adapter is None:
            return {"success": False, "error": "A2A adapter 不可用"}

        send = getattr(adapter, "send_task", None)
        if send is None:
            return {"success": False, "error": "A2A adapter 不支持 send_task"}

        description = self._augment_description(task, results)
        try:
            # send_task 为同步调用且可能含网络 IO，放到线程池避免阻塞事件循环
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: send(
                    target_agent_name=task.agent_name,
                    task_message=description,
                    task_type=DELEGATION_TASK_TYPE,
                ),
            )
            if isinstance(result, dict):
                return result
            return {"success": True, "result": str(result)}
        except Exception as e:
            logger.warning("master_delegate_failed", agent=task.agent_name, error=str(e))
            return {"success": False, "error": str(e)}

    async def _master_execute(self, task: SubTask, results: dict[str, SubTaskResult]) -> dict:
        """master 自己执行子任务（ReAct）。AgentRuntime 不可用时降级返回任务描述。"""
        runtime = self._get_agent_runtime()
        if runtime is None:
            return {"success": True, "summary": task.description, "degraded": True}

        description = self._augment_description(task, results)
        company_id = ""
        if self._context:
            company_id = self._context.intent_entities.get("company_id", "")

        try:
            out = await runtime.run(
                message=description,
                agent_name="master",
                company_id=company_id,
            )
            return {
                "success": bool(out.get("success", True)),
                "response": out.get("response", ""),
                "summary": out.get("response", ""),
            }
        except Exception as e:
            logger.warning("master_execute_failed", task_id=task.task_id, error=str(e))
            return {"success": False, "error": str(e)}

    def _augment_description(self, task: SubTask, results: dict[str, SubTaskResult]) -> str:
        """把前序依赖的结果摘要拼进任务描述，给执行方上下文。"""
        if not task.depends_on:
            return task.description
        ctx_parts = []
        for dep in task.depends_on:
            r = results.get(dep)
            if r and r.summary:
                ctx_parts.append(f"[{dep}] {r.summary}")
        if ctx_parts:
            return task.description + "\n\n## 前序任务结果\n" + "\n".join(ctx_parts)
        return task.description

    # ==================== 3. 审查验收 ====================

    async def review(self, results: dict[str, SubTaskResult]) -> ReviewResult:
        """审查子任务结果：格式校验 + LLM 验收 + 重试判定。"""
        self._review_attempts += 1
        review = ReviewResult(retry_count=self._review_attempts)

        # ── 格式校验 ──
        if not results:
            review.issues.append("无任何子任务结果")
            review.needs_retry = self._review_attempts <= MAX_REVIEW_RETRIES
            return review

        review.failed_task_ids = [tid for tid, r in results.items() if not r.success]
        review.final_output = self._synthesize(results)

        if not any(r.success for r in results.values()):
            review.issues.append("所有子任务均失败")
            review.needs_retry = self._review_attempts <= MAX_REVIEW_RETRIES
            return review

        # ── LLM 验收（对比原始意图）──
        accepted, issues = await self._llm_accept(review.final_output)
        review.issues.extend(issues)

        if accepted and not review.failed_task_ids:
            review.passed = True
            review.needs_retry = False
        else:
            review.passed = False
            review.needs_retry = self._review_attempts <= MAX_REVIEW_RETRIES

        return review

    def _synthesize(self, results: dict[str, SubTaskResult]) -> str:
        """综合成功子任务的结果为最终输出。"""
        try:
            from app.agents.master import aggregate_results

            original = self._context.raw_input if self._context else ""
            agg_input = [
                {"agent": r.agent_name or "master", "result": r.summary or r.error}
                for r in results.values()
                if r.success
            ]
            if agg_input:
                return aggregate_results(original, agg_input)
        except Exception as e:
            logger.warning("master_synthesize_failed", error=str(e))

        parts = [
            f"- [{r.agent_name or 'master'}] {r.summary}"
            for r in results.values()
            if r.success and r.summary
        ]
        return "\n".join(parts) if parts else "无有效结果"

    async def _llm_accept(self, final_output: str) -> tuple[bool, list[str]]:
        """LLM 验收：判断综合结果是否满足原始意图。

        无原始意图 / 无输出 / LLM 不可用 → 默认放行，避免空转阻塞。
        """
        original = self._context.raw_input if self._context else ""
        if not original or not final_output:
            return True, []

        system_prompt = (
            "你是质量审查员。请判断【执行结果】是否满足【用户意图】。\n"
            '仅以 JSON 返回：{"passed": true/false, "issues": ["问题1"]}。\n'
            "若结果完整、相关、无明显错误，passed=true。"
        )
        user_prompt = f"【用户意图】\n{original}\n\n【执行结果】\n{final_output}"

        content = await self._llm_complete(system_prompt, user_prompt)
        data = self._extract_json(content)
        if not data:
            return True, []  # LLM 不可用或解析失败 → 默认放行

        passed = bool(data.get("passed", True))
        issues = [str(x) for x in (data.get("issues") or [])]
        return passed, issues

    # ==================== 编排（含重试循环）====================

    async def orchestrate(self, context: ContextPackage) -> dict:
        """一步到位：拆解 → 调度 → 审查 → 不合格重试（最多 MAX_REVIEW_RETRIES 次）。

        供 T2.5 chat 入口 / MasterAgentRouter 复用。
        """
        subtasks = await self.decompose(context)
        if not subtasks:
            return {
                "passed": False,
                "final_output": "",
                "results": {},
                "subtasks": [],
                "issues": ["任务拆解为空"],
                "retry_count": 0,
            }

        results = await self.dispatch(subtasks)
        review = await self.review(results)

        # 不合格则只重跑失败的子任务并合并结果
        while review.needs_retry and not review.passed:
            retry_tasks = [t for t in subtasks if t.task_id in review.failed_task_ids]
            if not retry_tasks:
                break
            logger.info(
                "master_orchestrate_retry", attempt=review.retry_count, retry_count=len(retry_tasks)
            )
            retry_results = await self.dispatch(retry_tasks)
            results.update(retry_results)
            review = await self.review(results)

        return {
            "passed": review.passed,
            "final_output": review.final_output,
            "results": results,
            "subtasks": subtasks,
            "issues": review.issues,
            "retry_count": review.retry_count,
        }

    # ==================== 流式编排（供 T2.5 SSE 委派事件）====================

    async def orchestrate_stream(self, context: ContextPackage, workflow_def: dict = None):
        """流式编排：与 orchestrate() 逻辑一致，但 yield SSE 事件字典。

        供 MasterAgentRouter._run_plan_execute_reflect / _run_workflow 调用，
        让 chat.py 能把委派过程实时推给前端。

        Args:
            context: 感知层产出的综合上下文包
            workflow_def: 可选 workflow 模板定义。提供时走 workflow 模式
                （节点级并行 + 依赖结果注入），否则走 LLM 拆解模式
                （PLAN_EXECUTE_REFLECT）。

        Yields:
            {"type": "plan", ...}
            {"type": "delegation", "agent_name", "agent_display", "status": "started"}
            {"type": "delegation", "agent_name", "status": "completed"|"failed"}
            {"type": "action", "data": ...}       # workflow 模式
            {"type": "observation", "data": ...}   # workflow 模式
            {"type": "reflection", ...}
            {"type": "result", "data": final_output}
            {"type": "done"}
        """
        # workflow 模式：基于预定义 SOP 模板的节点级并行执行
        if workflow_def is not None:
            async for event in self._orchestrate_workflow_stream(context, workflow_def):
                yield event
            return

        subtasks = await self.decompose(context)
        if not subtasks:
            yield {"type": "error", "data": "任务拆解为空"}
            yield {"type": "done"}
            return

        yield {"type": "plan", "data": f"拆解为 {len(subtasks)} 个子任务"}

        # 流式调度：_dispatch_stream 是 async generator，
        # yield 委派事件的同时通过可变 results dict 积累结果
        results: dict[str, SubTaskResult] = {}
        async for event in self._dispatch_stream(subtasks, results):
            yield event

        review = await self.review(results)

        # 不合格则重试失败的子任务
        while review.needs_retry and not review.passed:
            retry_tasks = [t for t in subtasks if t.task_id in review.failed_task_ids]
            if not retry_tasks:
                break
            logger.info(
                "master_orchestrate_stream_retry",
                attempt=review.retry_count,
                retry_count=len(retry_tasks),
            )
            yield {"type": "reflection", "data": f"审查未通过，重试 {len(retry_tasks)} 个子任务"}
            async for event in self._dispatch_stream(retry_tasks, results):
                yield event
            review = await self.review(results)

        if review.passed:
            yield {"type": "reflection", "data": "审查通过"}
        else:
            issues_str = "; ".join(review.issues) if review.issues else "未知问题"
            yield {"type": "reflection", "data": f"审查未通过: {issues_str}"}

        yield {"type": "result", "data": review.final_output}
        yield {"type": "done"}

    async def _dispatch_stream(
        self,
        subtasks: list[SubTask],
        results: dict[str, SubTaskResult],
    ):
        """流式调度：yield 委派事件，同时把结果写入可变 results dict。

        与 dispatch() 逻辑一致，但在批次执行前后 yield delegation 事件，
        让调用方能实时推送委派过程。
        """
        if not subtasks:
            return

        task_map: dict[str, SubTask] = {t.task_id: t for t in subtasks}
        remaining: set[str] = set(task_map.keys())

        while remaining:
            ready = [
                tid
                for tid in remaining
                if all(dep in results and results[dep].success for dep in task_map[tid].depends_on)
            ]

            if not ready:
                blocked = [
                    tid
                    for tid in remaining
                    if all(dep in results for dep in task_map[tid].depends_on)
                ]
                if blocked:
                    for tid in blocked:
                        results[tid] = SubTaskResult(
                            task_id=tid,
                            agent_name=task_map[tid].agent_name,
                            status=SubTaskStatus.SKIPPED,
                            error="前序依赖失败，子任务跳过",
                        )
                        remaining.discard(tid)
                    continue
                for tid in remaining:
                    results[tid] = SubTaskResult(
                        task_id=tid,
                        agent_name=task_map[tid].agent_name,
                        status=SubTaskStatus.FAILED,
                        error="依赖无法满足（可能存在循环依赖）",
                    )
                logger.warning("master_dispatch_deadlock", remaining=list(remaining))
                break

            ready.sort(key=lambda tid: task_map[tid].priority, reverse=True)

            # 委派子任务：发 started 事件（master 自己的不发 delegation 事件）
            for tid in ready:
                task = task_map[tid]
                if task.agent_name and task.agent_name != "master":
                    yield {
                        "type": "delegation",
                        "agent_name": task.agent_name,
                        "agent_display": self._get_agent_display(task.agent_name),
                        "status": "started",
                    }

            batch = await asyncio.gather(
                *[self._execute_subtask(task_map[tid], results) for tid in ready],
                return_exceptions=True,
            )

            for tid, res in zip(ready, batch, strict=False):
                if isinstance(res, Exception):
                    results[tid] = SubTaskResult(
                        task_id=tid,
                        agent_name=task_map[tid].agent_name,
                        status=SubTaskStatus.FAILED,
                        error=str(res),
                    )
                else:
                    results[tid] = res
                remaining.discard(tid)

                # 委派子任务：发 completed/failed 事件
                task = task_map[tid]
                if task.agent_name and task.agent_name != "master":
                    status = "completed" if results[tid].success else "failed"
                    yield {
                        "type": "delegation",
                        "agent_name": task.agent_name,
                        "status": status,
                    }

    # ==================== workflow 模板流式编排 ====================

    async def _orchestrate_workflow_stream(
        self,
        context: ContextPackage,
        workflow_def: dict,
    ):
        """workflow 模板流式执行：节点级并行 + 依赖结果注入。

        与 orchestrate_stream 的 PLAN_EXECUTE_REFLECT 模式不同，workflow 模式
        基于预定义 SOP 模板（JSON/YAML）的 nodes 定义执行，无需 LLM 拆解。

        执行策略：
        1. 将 workflow nodes 转换为 SubTask
        2. 按 depends_on 拓扑排序，无依赖节点用 asyncio.gather 并行执行
        3. depends_on 的节点结果通过 _augment_description 注入到任务描述
        4. yield action/observation 事件（兼容 WORKFLOW 路径既有事件类型）

        Yields:
            {"type": "plan", "data": ...}
            {"type": "action", "data": "[agent] description"}
            {"type": "observation", "data": "[node_id] summary"}
            {"type": "result", "data": final_summary}
            {"type": "done"}
        """
        self._context = context
        self._review_attempts = 0  # 重置审查计数，避免实例复用时串状态

        nodes = workflow_def.get("nodes", [])
        if not nodes:
            yield {"type": "error", "data": "workflow 模板无节点定义"}
            yield {"type": "done"}
            return

        workflow_name = workflow_def.get("name", "")
        yield {"type": "plan", "data": f"workflow {workflow_name} 共 {len(nodes)} 个节点"}

        # 转换 workflow nodes 为 SubTask
        subtasks = self._workflow_nodes_to_subtasks(nodes)
        if not subtasks:
            yield {"type": "error", "data": "workflow 节点转换为空"}
            yield {"type": "done"}
            return

        logger.info(
            "master_workflow_stream_start",
            workflow=workflow_name,
            node_count=len(subtasks),
        )

        # 流式调度：复用 _workflow_dispatch_stream 的并行 + 依赖注入逻辑
        results: dict[str, SubTaskResult] = {}
        async for event in self._workflow_dispatch_stream(subtasks, results):
            yield event

        # 汇总结果
        final_summary = self._summarize_workflow(workflow_name, results)
        yield {"type": "result", "data": final_summary}
        yield {"type": "done"}

    def _workflow_nodes_to_subtasks(self, nodes: list[dict]) -> list[SubTask]:
        """将 workflow 节点列表转换为 SubTask 列表。

        解析每个节点的 agent 字段为 AGENT_REGISTRY 中的 agent_key，
        兼容 "BrandBD" / "data_analysis" / "数据分析" 等形式。
        """
        try:
            from app.agents import AGENT_REGISTRY

            registry = AGENT_REGISTRY
        except Exception:
            registry = {}

        subtasks: list[SubTask] = []
        seen_ids: set[str] = set()
        for i, node in enumerate(nodes, 1):
            node_id = str(node.get("id") or f"node_{i}")
            if node_id in seen_ids:
                node_id = f"{node_id}_{i}"
            seen_ids.add(node_id)

            agent = node.get("agent", "")
            action = node.get("action", "")
            desc = node.get("description", action)
            depends = [str(d) for d in (node.get("depends_on") or []) if d]

            agent_key = self._resolve_agent_key(agent, registry) if agent else None

            description = f"{action}: {desc}" if desc and desc != action else action

            subtasks.append(
                SubTask(
                    task_id=node_id,
                    description=description,
                    agent_name=agent_key if agent_key else None,
                    priority=0,
                    depends_on=depends,
                )
            )

        # 清洗 depends_on：剔除指向不存在任务或自引用的依赖，防止调度死锁
        valid_ids = {t.task_id for t in subtasks}
        for t in subtasks:
            t.depends_on = [d for d in t.depends_on if d in valid_ids and d != t.task_id]

        return subtasks

    async def _workflow_dispatch_stream(
        self,
        subtasks: list[SubTask],
        results: dict[str, SubTaskResult],
    ):
        """workflow 流式调度：yield action/observation 事件，并行执行无依赖节点。

        与 _dispatch_stream 逻辑一致（拓扑排序 + asyncio.gather 并行），
        但 yield action/observation 事件而非 delegation 事件，保持与
        WORKFLOW 路径既有事件类型兼容。
        """
        if not subtasks:
            return

        task_map: dict[str, SubTask] = {t.task_id: t for t in subtasks}
        remaining: set[str] = set(task_map.keys())

        while remaining:
            ready = [
                tid
                for tid in remaining
                if all(dep in results and results[dep].success for dep in task_map[tid].depends_on)
            ]

            if not ready:
                # 依赖已全部出结果但存在失败 → 这些任务无法执行，跳过
                blocked = [
                    tid
                    for tid in remaining
                    if all(dep in results for dep in task_map[tid].depends_on)
                ]
                if blocked:
                    for tid in blocked:
                        results[tid] = SubTaskResult(
                            task_id=tid,
                            agent_name=task_map[tid].agent_name,
                            status=SubTaskStatus.SKIPPED,
                            error="前序依赖失败，节点跳过",
                        )
                        remaining.discard(tid)
                        yield {"type": "observation", "data": f"节点 {tid} 跳过: 前序依赖失败"}
                    continue
                # 既无就绪也无可跳过 → 循环依赖或悬空依赖，避免死循环
                for tid in remaining:
                    results[tid] = SubTaskResult(
                        task_id=tid,
                        agent_name=task_map[tid].agent_name,
                        status=SubTaskStatus.FAILED,
                        error="依赖无法满足（可能存在循环依赖）",
                    )
                logger.warning("workflow_dispatch_deadlock", remaining=list(remaining))
                break

            # yield action 事件（每个就绪节点）
            for tid in ready:
                task = task_map[tid]
                agent_display = task.agent_name or "master"
                yield {"type": "action", "data": f"[{agent_display}] {task.description}"}

            # 并行执行就绪批次：_execute_subtask 内部会通过 _augment_description
            # 把 depends_on 的结果摘要注入到任务描述，实现依赖结果注入
            batch = await asyncio.gather(
                *[self._execute_subtask(task_map[tid], results) for tid in ready],
                return_exceptions=True,
            )

            for tid, res in zip(ready, batch, strict=False):
                if isinstance(res, Exception):
                    results[tid] = SubTaskResult(
                        task_id=tid,
                        agent_name=task_map[tid].agent_name,
                        status=SubTaskStatus.FAILED,
                        error=str(res),
                    )
                else:
                    results[tid] = res
                remaining.discard(tid)

                # yield observation 事件
                r = results[tid]
                summary = r.summary or r.error or "节点执行完成"
                yield {"type": "observation", "data": f"[{tid}] {summary}"}

    @staticmethod
    def _resolve_agent_key(agent_name: str, registry: dict) -> str:
        """从 AGENT_REGISTRY 解析 agent_key，兼容 registry key 与显示名。

        匹配顺序：
        1. 精确 key 匹配（如 "data_analysis"）
        2. 规范化匹配：去除非字母数字字符并小写（如 "BrandBD" ↔ "brand_bd"）
        3. 显示名匹配（如 "数据分析" → "data_analysis"）
        """
        if not agent_name:
            return ""
        if agent_name in registry:
            return agent_name
        norm = re.sub(r"[^a-z0-9]", "", agent_name.lower())
        for key in registry:
            if re.sub(r"[^a-z0-9]", "", key.lower()) == norm:
                return key
        for key, info in registry.items():
            if info.get("name_display") == agent_name:
                return key
        return ""

    @staticmethod
    def _summarize_workflow(workflow_name: str, results: dict[str, SubTaskResult]) -> str:
        """汇总 workflow 所有节点的执行结果。"""
        if not results:
            return f"workflow {workflow_name} 无执行结果"

        parts = [f"workflow {workflow_name} 执行完成，共 {len(results)} 个节点:"]
        for node_id, result in results.items():
            status = result.status if hasattr(result, "status") else "unknown"
            summary = result.summary or result.error or ""
            parts.append(f"  - [{node_id}] {status}: {summary}")

        return "\n".join(parts)

    @staticmethod
    def _get_agent_display(agent_name: str) -> str:
        """获取 Agent 的显示名称（用于 SSE delegation 事件）。"""
        try:
            from app.agents import AGENT_REGISTRY

            info = AGENT_REGISTRY.get(agent_name, {})
            display = info.get("name_display", agent_name)
            return f"{display} {agent_name}"
        except Exception:
            return agent_name

    # ==================== 工具方法 ====================

    async def _llm_complete(self, system_prompt: str, user_prompt: str) -> str:
        """统一的 LLM 调用封装，优先 async ainvoke，否则线程池跑同步 invoke。"""
        gateway = self._get_model_gateway()
        if gateway is None:
            return ""
        try:
            llm = gateway.get_llm()
        except Exception as e:
            logger.warning("master_dispatcher_llm_unavailable", error=str(e))
            return ""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            ainvoke = getattr(llm, "ainvoke", None)
            if ainvoke is not None:
                resp = await ainvoke(messages)
            else:
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(None, lambda: llm.invoke(messages))
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.warning("master_dispatcher_llm_failed", error=str(e))
            return ""

    @staticmethod
    def _extract_json(content: str) -> dict | None:
        """从 LLM 文本输出中提取首个 JSON 对象。"""
        if not content:
            return None
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    def _format_available_agents(self, available_agents: list[str]) -> str:
        """格式化可委派 Agent 清单为 "key: 中文名" 文本。"""
        try:
            from app.agents import AGENT_REGISTRY
        except Exception:
            return "\n".join(f"- {a}" for a in available_agents)

        lines = []
        for key in available_agents:
            if key == "master":
                continue  # master 是自己，不作为委派目标
            info = AGENT_REGISTRY.get(key)
            if info:
                lines.append(f"- {key}: {info.get('name_display', key)}")
        return "\n".join(lines) if lines else "（暂无可委派子 Agent）"

    @staticmethod
    def _all_agent_keys() -> list[str]:
        """获取全量子 Agent 键名（master 注册表），失败返回空列表。"""
        try:
            from app.agents import get_all_agent_keys

            return get_all_agent_keys()
        except Exception:
            return []

    # ── 延迟依赖获取 ──

    def _get_model_gateway(self):
        if self._model_gateway is not None:
            return self._model_gateway
        try:
            from app.services.model_gateway import get_global_model_gateway

            self._model_gateway = get_global_model_gateway()
        except Exception as e:
            logger.warning("master_dispatcher_model_gateway_unavailable", error=str(e))
            self._model_gateway = None
        return self._model_gateway

    def _get_agent_runtime(self):
        if self._agent_runtime is not None:
            return self._agent_runtime
        try:
            from app.runtime.orchestrator import AgentRuntime

            self._agent_runtime = AgentRuntime()
        except Exception as e:
            logger.warning("master_dispatcher_agent_runtime_unavailable", error=str(e))
            self._agent_runtime = None
        return self._agent_runtime

    def _get_a2a_adapter(self):
        if self._a2a_adapter is not None:
            return self._a2a_adapter
        try:
            from app.communication.a2a_adapter import get_a2a_adapter

            self._a2a_adapter = get_a2a_adapter()
        except Exception as e:
            logger.warning("master_dispatcher_a2a_unavailable", error=str(e))
            self._a2a_adapter = None
        return self._a2a_adapter


__all__ = [
    "MasterDispatcher",
    "SubTask",
    "SubTaskResult",
    "ReviewResult",
    "SubTaskStatus",
]

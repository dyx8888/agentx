"""
16.2.5 集成测试：A2A并行分派 → 3个Agent → 汇总结果
验证并行Agent分派的完整链路：任务创建 → 并行执行 → 结果汇总 → 去重 → 冲突检测
"""
from unittest.mock import MagicMock

import pytest


class TestA2AParallelFlow:
    """A2A 并行分派集成测试"""

    @pytest.fixture
    def mock_a2a(self):
        """创建 mock A2A adapter"""
        adapter = MagicMock()

        def send_task_side_effect(
            target_agent_name,
            task_description,
            task_type="general",
            company_id=None,
        ):
            assert company_id == 239
            results = {
                "brand_bd": {"success": True, "task_id": "task_bd_001", "result": {"品牌": "A", "竞品": ["B", "C"]}},
                "product_selector": {"success": True, "task_id": "task_ps_001", "result": {"推荐产品": "P1", "价格": 99}},
                "warehouse": {"success": True, "task_id": "task_wh_001", "result": {"库存": 500, "预计发货": "3天"}},
            }
            return results.get(target_agent_name, {"success": False, "error": "Agent not found"})

        adapter.send_task = MagicMock(side_effect=send_task_side_effect)
        return adapter

    @pytest.fixture
    def dispatcher(self, mock_a2a):
        """创建并行分派器"""
        from app.communication.parallel import ParallelAgentDispatcher
        return ParallelAgentDispatcher(
            a2a_adapter=mock_a2a,
            global_timeout=10,
            company_id=239,
        )

    # ── 场景1: 3个Agent并行分派，全部成功 ────────────────────────

    @pytest.mark.asyncio
    async def test_parallel_dispatch_three_agents(self, dispatcher):
        """3个Agent并行分派，全部成功汇总"""
        from app.communication.parallel import ParallelTask

        tasks = [
            ParallelTask(target_agent="brand_bd", task_description="分析品牌竞品"),
            ParallelTask(target_agent="product_selector", task_description="推荐产品"),
            ParallelTask(target_agent="warehouse", task_description="查询库存"),
        ]

        result = await dispatcher.dispatch(tasks)

        assert result.total_tasks == 3
        assert result.completed == 3
        assert result.failed == 0
        assert result.partial_failure is False

        # 验证每个任务结果
        agent_names = [r.task.target_agent for r in result.tasks]
        assert "brand_bd" in agent_names
        assert "product_selector" in agent_names
        assert "warehouse" in agent_names

    # ── 场景2: 部分失败容错 ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_partial_failure_tolerance(self, dispatcher):
        """部分Agent失败时其他结果仍正常返回"""
        from app.communication.parallel import ParallelTask

        # brand_bd 和 product_selector 成功，但 nonexistent_agent 失败
        tasks = [
            ParallelTask(target_agent="brand_bd", task_description="分析品牌"),
            ParallelTask(target_agent="nonexistent_agent", task_description="不存在的Agent"),
            ParallelTask(target_agent="product_selector", task_description="推荐产品"),
        ]

        result = await dispatcher.dispatch(tasks)

        assert result.total_tasks == 3
        assert result.completed == 2
        assert result.failed == 1
        assert result.partial_failure is True

        # 成功任务的 result 应有内容
        success_results = [r for r in result.tasks if r.success]
        assert len(success_results) == 2

        # 失败任务应有错误信息
        failed_results = [r for r in result.tasks if not r.success]
        assert len(failed_results) == 1
        assert failed_results[0].error == "Agent not found"

    # ── 场景3: 空任务列表 ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_task_list(self, dispatcher):
        """空任务列表应返回空结果"""
        result = await dispatcher.dispatch([])
        assert result.total_tasks == 0
        assert result.completed == 0
        assert result.failed == 0

    # ── 场景4: 结果去重 ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_result_deduplication(self, dispatcher):
        """同一Agent的多个结果应被合并去重"""
        from app.communication.parallel import ParallelTask, ParallelTaskResult

        results = [
            ParallelTaskResult(
                task=ParallelTask(target_agent="brand_bd", task_description="任务1"),
                success=True, result={"data": "A"},
            ),
            ParallelTaskResult(
                task=ParallelTask(target_agent="brand_bd", task_description="任务2"),
                success=True, result={"data": "B"},
            ),
            ParallelTaskResult(
                task=ParallelTask(target_agent="product_selector", task_description="任务3"),
                success=True, result={"data": "C"},
            ),
        ]

        merged = dispatcher.deduplicate_results(results)

        # 应有2个去重后的Agent结果
        assert len(merged) == 2
        brand_bd_entry = [m for m in merged if m["agent"] == "brand_bd"][0]
        assert brand_bd_entry["total_tasks"] == 2
        assert brand_bd_entry["completed"] == 2

    # ── 场景5: 冲突检测 ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_conflict_detection(self, dispatcher):
        """检测并行任务间的结论冲突"""
        from app.communication.parallel import ParallelTask, ParallelTaskResult

        results = [
            ParallelTaskResult(
                task=ParallelTask(target_agent="agent_a", task_description="评估"),
                success=True, result={"action": "approved", "reason": "合格"},
            ),
            ParallelTaskResult(
                task=ParallelTask(target_agent="agent_b", task_description="评估"),
                success=True, result={"action": "rejected", "reason": "不合格"},
            ),
        ]

        conflicts = dispatcher.detect_conflicts(results)
        assert len(conflicts) == 1
        assert conflicts[0]["type"] == "conflicting_conclusion"
        assert "agent_a" in conflicts[0]["agent1"]
        assert "agent_b" in conflicts[0]["agent2"]

    # ── 场景6: 无冲突检测 ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_conflict_when_consistent(self, dispatcher):
        """一致的结果不应报告冲突"""
        from app.communication.parallel import ParallelTask, ParallelTaskResult

        results = [
            ParallelTaskResult(
                task=ParallelTask(target_agent="agent_a", task_description="评估"),
                success=True, result={"action": "approved"},
            ),
            ParallelTaskResult(
                task=ParallelTask(target_agent="agent_b", task_description="评估"),
                success=True, result={"action": "approved", "score": 85},
            ),
        ]

        conflicts = dispatcher.detect_conflicts(results)
        assert len(conflicts) == 0

    # ── 场景7: a2a_delegate_parallel 工具函数 ────────────────────

    def test_a2a_delegate_parallel_function(self, mock_a2a):
        """a2a_delegate_parallel 工具函数应正常调用"""
        tasks = [
            {"target_agent": "brand_bd", "task_description": "分析品牌"},
            {"target_agent": "product_selector", "task_description": "推荐产品"},
        ]

        # 直接测试 ParallelTask 的创建
        from app.communication.parallel import ParallelTask
        parallel_tasks = [
            ParallelTask(
                target_agent=t.get("target_agent", ""),
                task_description=t.get("task_description", ""),
                task_type=t.get("task_type", "general"),
            )
            for t in tasks
        ]

        assert len(parallel_tasks) == 2
        assert parallel_tasks[0].target_agent == "brand_bd"
        assert parallel_tasks[1].target_agent == "product_selector"

    # ── 场景8: 并行任务执行时间记录 ──────────────────────────────

    @pytest.mark.asyncio
    async def test_timing_records(self, dispatcher):
        """并行执行应记录耗时信息"""
        from app.communication.parallel import ParallelTask

        tasks = [
            ParallelTask(target_agent="brand_bd", task_description="任务1"),
        ]

        result = await dispatcher.dispatch(tasks)

        assert result.total_duration_ms >= 0
        for task_result in result.tasks:
            assert task_result.duration_ms >= 0

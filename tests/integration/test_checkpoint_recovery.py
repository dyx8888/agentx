"""
16.2.2 集成测试：Agent执行中断 → checkpoint恢复 → 继续执行
验证完整的 checkpoint 保存/恢复链路
"""

from unittest.mock import patch

import pytest


class TestCheckpointRecoveryFlow:
    """Checkpoint 恢复集成测试"""

    @pytest.fixture
    def saver(self):
        """创建隔离的 RedisSaver（仅内存模式）"""
        import app.core.checkpoint as cp_mod
        from collections import defaultdict

        with patch.object(
            cp_mod.RedisSaver, "__init__", lambda self, *args, **kwargs: None
        ):
            s = cp_mod.RedisSaver.__new__(cp_mod.RedisSaver)
            s._connected = False
            s._redis_client = None
            s._storage = defaultdict(lambda: defaultdict(dict))
            s._writes = defaultdict(dict)
            s._blobs = {}
            s._ttl = 3600
            s.serde = None
        return s

    # ── 场景1: 保存 → 恢复完整 workflow ──────────────────────────

    def test_save_and_restore_workflow(self, saver):
        """保存 checkpoint 后能完整恢复"""
        thread_id = "thread_recovery_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Step 1: 保存第一个 checkpoint
        checkpoint1 = {
            "id": "ckpt_001",
            "channel_versions": {"messages": "1"},
            "messages": [{"role": "user", "content": "帮我查一下数据"}],
            "plan": {"steps": [{"name": "查询数据", "status": "in_progress"}]},
        }
        new_versions1 = {"messages": "1"}
        saver.put(config, checkpoint1, {"step": 1}, new_versions1)

        # Step 2: 保存第二个 checkpoint（模拟继续执行）
        checkpoint2 = {
            "id": "ckpt_002",
            "channel_versions": {"messages": "2"},
            "messages": [
                {"role": "user", "content": "帮我查一下数据"},
                {"role": "assistant", "content": "正在查询..."},
            ],
            "plan": {"steps": [{"name": "查询数据", "status": "completed"}]},
        }
        new_versions2 = {"messages": "2"}
        saver.put(config, checkpoint2, {"step": 2}, new_versions2)

        # 恢复最新的 checkpoint
        restored = saver.get_tuple(config)
        assert restored is not None
        assert restored.checkpoint["id"] == "ckpt_002"
        assert len(restored.checkpoint["messages"]) == 2

    # ── 场景2: 中断后从 checkpoint 恢复 ──────────────────────────

    def test_recover_after_interruption(self, saver):
        """模拟中断后从 checkpoint 恢复"""
        thread_id = "thread_interrupted_001"
        config = {"configurable": {"thread_id": thread_id}}

        # 执行到一半时保存 checkpoint
        mid_checkpoint = {
            "id": "ckpt_mid",
            "channel_versions": {"messages": "1", "plan": "1"},
            "messages": [
                {"role": "user", "content": "生成周报"},
                {
                    "role": "assistant",
                    "tool_calls": [{"name": "query_data", "args": {}}],
                },
            ],
            "plan": {
                "steps": [
                    {"name": "查询数据", "status": "completed"},
                    {"name": "生成图表", "status": "in_progress"},
                    {"name": "导出报告", "status": "pending"},
                ]
            },
        }
        saver.put(config, mid_checkpoint, {"step": 2}, {"messages": "1", "plan": "1"})

        # 中断后恢复
        restored = saver.get_tuple(config)
        assert restored is not None
        assert restored.checkpoint["id"] == "ckpt_mid"

        # 验证中间状态
        plan = restored.checkpoint["plan"]
        steps = plan["steps"]
        assert steps[0]["status"] == "completed"
        assert steps[1]["status"] == "in_progress"
        assert steps[2]["status"] == "pending"

        # 继续执行：从中断点恢复后保存新 checkpoint
        continue_checkpoint = {
            "id": "ckpt_continue",
            "channel_versions": {"messages": "2", "plan": "2"},
            "messages": [
                {"role": "user", "content": "生成周报"},
                {"role": "assistant", "content": "图表已生成"},
            ],
            "plan": {
                "steps": [
                    {"name": "查询数据", "status": "completed"},
                    {"name": "生成图表", "status": "completed"},
                    {"name": "导出报告", "status": "completed"},
                ]
            },
        }
        config_with_parent = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": "ckpt_mid",
            }
        }
        saver.put(
            config_with_parent,
            continue_checkpoint,
            {"step": 3},
            {"messages": "2", "plan": "2"},
        )

        # 最终恢复：使用完整 config 指定 checkpoint_id
        final_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": "ckpt_continue",
            }
        }
        final = saver.get_tuple(final_config)
        assert final is not None
        assert final.checkpoint["id"] == "ckpt_continue"
        assert all(
            s["status"] == "completed" for s in final.checkpoint["plan"]["steps"]
        )

    # ── 场景3: 部分写入（pending writes）恢复 ────────────────────

    def test_pending_writes_recovery(self, saver):
        """验证 pending writes 的正确存储和恢复"""
        thread_id = "thread_writes_001"
        config = {"configurable": {"thread_id": thread_id}}

        checkpoint = {
            "id": "ckpt_writes",
            "channel_versions": {"messages": "1"},
            "messages": [],
            "plan": {},
        }
        saver.put(config, checkpoint, {}, {"messages": "1"})

        # 写入 pending writes
        config_with_id = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": "ckpt_writes",
            }
        }
        writes = [
            ("messages", {"role": "assistant", "content": "pending output"}),
            ("plan", {"next_step": "tool_call"}),
        ]
        saver.put_writes(config_with_id, writes, task_id="task_001")

        # 恢复时验证 pending writes
        restored = saver.get_tuple(config_with_id)
        assert restored is not None
        assert len(restored.pending_writes) > 0

    # ── 场景4: 多个 checkpoint 链式恢复 ──────────────────────────

    def test_checkpoint_chain(self, saver):
        """验证 checkpoint 链式结构"""
        thread_id = "thread_chain_001"
        config = {"configurable": {"thread_id": thread_id}}

        # 创建 3 个连续的 checkpoint
        for i in range(3):
            ckpt = {
                "id": f"ckpt_{i}",
                "channel_versions": {"messages": str(i)},
                "messages": [{"content": f"step_{i}"}],
                "plan": {"step": i},
            }
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": f"ckpt_{i - 1}" if i > 0 else None,
                }
            }
            saver.put(parent_config, ckpt, {"step": i}, {"messages": str(i)})

        # 恢复最新 checkpoint
        latest = saver.get_tuple(config)
        assert latest is not None
        assert latest.checkpoint["id"] == "ckpt_2"

    # ── 场景5: 中断恢复后上下文连续性 ────────────────────────────

    def test_context_continuity_after_recovery(self, saver):
        """恢复后上下文应保持连续性"""
        thread_id = "thread_context_001"
        config = {"configurable": {"thread_id": thread_id}}

        # 模拟对话上下文
        conversation = [
            ("user", "我想了解产品A"),
            ("assistant", "产品A是我们的旗舰产品，有以下特点..."),
            ("user", "价格是多少？"),
        ]

        ckpt = {
            "id": "ckpt_context",
            "channel_versions": {"messages": "1"},
            "messages": [
                {"role": role, "content": content} for role, content in conversation
            ],
            "plan": {"current_step": "answer_pricing"},
        }
        saver.put(config, ckpt, {"step": 1}, {"messages": "1"})

        # 恢复
        restored = saver.get_tuple(config)
        assert restored is not None
        messages = restored.checkpoint["messages"]
        assert len(messages) == 3
        assert messages[-1]["role"] == "user"
        assert "价格" in messages[-1]["content"]

    # ── 场景6: 中断恢复后执行原有 plan ───────────────────────────

    def test_plan_recovery_and_continuation(self, saver):
        """恢复后应继续执行原有 plan"""
        thread_id = "thread_plan_001"
        config = {"configurable": {"thread_id": thread_id}}

        original_plan = {
            "steps": [
                {"id": "1", "name": "收集数据", "status": "completed"},
                {"id": "2", "name": "分析数据", "status": "in_progress"},
                {"id": "3", "name": "生成报告", "status": "pending"},
                {"id": "4", "name": "发送通知", "status": "pending"},
            ],
            "completed_steps": 1,
            "total_steps": 4,
        }

        ckpt = {
            "id": "ckpt_plan",
            "channel_versions": {"plan": "1"},
            "messages": [],
            "plan": original_plan,
        }
        saver.put(config, ckpt, {"step": 2}, {"plan": "1"})

        # 恢复
        restored = saver.get_tuple(config)
        assert restored is not None
        plan = restored.checkpoint["plan"]
        assert plan["completed_steps"] == 1
        assert plan["total_steps"] == 4

        # 验证应继续执行 step 2
        in_progress = [s for s in plan["steps"] if s["status"] == "in_progress"]
        assert len(in_progress) == 1
        assert in_progress[0]["name"] == "分析数据"

    # ── 场景7: 删除 thread 后无法恢复 ────────────────────────────

    def test_delete_thread_clears_all(self, saver):
        """删除 thread 后所有 checkpoint 应被清除"""
        thread_id = "thread_to_delete"
        config = {"configurable": {"thread_id": thread_id}}

        ckpt = {
            "id": "ckpt_del",
            "channel_versions": {"messages": "1"},
            "messages": [{"content": "test"}],
            "plan": {},
        }
        saver.put(config, ckpt, {}, {"messages": "1"})

        # 验证存在
        assert saver.get_tuple(config) is not None

        # 删除
        saver.delete_thread(thread_id)

        # 验证已清除
        assert saver.get_tuple(config) is None

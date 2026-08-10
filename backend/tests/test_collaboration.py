"""
跨职位协作测试
验证协作引擎的任务转发和规则匹配功能
"""

import os

# 添加项目根目录到 Python 路径
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.communication.collaboration import CollaborationEngine


class TestCollaboration:
    """跨职位协作测试类"""

    def test_1_register_agent_capabilities(self):
        """正常场景1：注册 Agent 能力和推荐接力对象"""
        # 创建协作引擎实例
        engine = CollaborationEngine()

        # 注册 BrandBD Agent 的能力
        engine.register_agent_capabilities(
            agent_name="BrandBD",
            capabilities=["search_kols", "analyze_performance", "generate_report"],
            next_agent="CC"
        )

        # 验证注册
        capabilities = engine.get_agent_capabilities("BrandBD")
        assert "search_kols" in capabilities
        assert "analyze_performance" in capabilities
        assert "generate_report" in capabilities

        # 验证推荐接力对象
        next_agent = engine.get_next_agent("BrandBD")
        assert next_agent == "CC"

    def test_2_brandbd_to_cc_collaboration(self):
        """正常场景2：BrandBD 完成后自动为 CC 创建接力任务"""
        # 创建协作引擎实例
        engine = CollaborationEngine()

        # 注册 Agent 和能力
        engine.register_agent_capabilities(
            agent_name="BrandBD",
            capabilities=["generate_script"],
            next_agent="CC"
        )

        # Mock 数据库操作
        with patch('app.database.db') as mock_db:
            mock_db.get_agents_by_company.return_value = [
                MagicMock(name="BrandBD", tools_json='["generate_script"]'),
                MagicMock(name="CC", tools_json='["edit_content"]')
            ]

            mock_db.create_task.return_value = 12345

            # 触发协作
            new_task_id = engine.trigger_collaboration(
                task_id=1001,
                completed_agent_name="BrandBD",
                company_id=1
            )

            # 验证任务创建
            assert new_task_id == 12345
            mock_db.create_task.assert_called_once_with(
                company_id=1,
                source_agent_id=None,
                target_agent_name="CC",
                task_description="协作任务：承接来自 BrandBD 的工作，请继续执行后续流程。"
            )

    def test_3_no_next_agent_no_task_creation(self):
        """正常场景3：当不存在接力规则时，不创建无关任务"""
        # 创建协作引擎实例
        engine = CollaborationEngine()

        # 注册 Amy Agent（无接力规则）
        engine.register_agent_capabilities(
            agent_name="Amy",
            capabilities=["search_data"],
            next_agent=None
        )

        # Mock 数据库操作
        with patch('app.database.db') as mock_db:
            mock_db.get_agents_by_company.return_value = [
                MagicMock(name="Amy", tools_json='["search_data"]')
            ]

            mock_db.create_task.return_value = 12346

            # 触发协作
            new_task_id = engine.trigger_collaboration(
                task_id=1002,
                completed_agent_name="Amy",
                company_id=1
            )

            # 验证没有创建任务
            assert new_task_id is None
            mock_db.create_task.assert_not_called()

    def test_4_database_failure_handling(self):
        """异常场景1：数据库创建任务失败时不抛异常"""
        # 创建协作引擎实例
        engine = CollaborationEngine()

        # 注册 Agent 和能力
        engine.register_agent_capabilities(
            agent_name="BrandBD",
            capabilities=["generate_script"],
            next_agent="CC"
        )

        # Mock 数据库操作
        with patch('app.database.db') as mock_db:
            mock_db.get_agents_by_company.return_value = [
                MagicMock(name="BrandBD", tools_json='["generate_script"]'),
                MagicMock(name="CC", tools_json='["edit_content"]')
            ]

            # Mock 数据库创建失败
            mock_db.create_task.side_effect = Exception("Database connection failed")

            # 触发协作
            new_task_id = engine.trigger_collaboration(
                task_id=1003,
                completed_agent_name="BrandBD",
                company_id=1
            )

            # 验证返回 None 而不是异常
            assert new_task_id is None
            # 验证异常被正确处理
            assert mock_db.create_task.called

    def test_5_no_suitable_agent_found(self):
        """异常场景2：当公司内没有合适的接力对象时，不会死循环或崩溃"""
        # 创建协作引擎实例
        engine = CollaborationEngine()

        # 注册 BrandBD Agent（无 CC Agent）
        engine.register_agent_capabilities(
            agent_name="BrandBD",
            capabilities=["generate_script"],
            next_agent="CC"
        )

        # Mock 数据库操作
        with patch('app.database.db') as mock_db:
            mock_db.get_agents_by_company.return_value = [
                MagicMock(name="BrandBD", tools_json='["generate_script"]')
            ]

            # 移除 CC Agent
            mock_db.create_task.return_value = 12347

            # 触发协作
            new_task_id = engine.trigger_collaboration(
                task_id=1004,
                completed_agent_name="BrandBD",
                company_id=1
            )

            # 验证没有创建任务
            assert new_task_id is None
            assert mock_db.create_task.called
            assert mock_db.get_agents_by_company.called

    def test_6_singleton_behavior(self):
        """正常场景4：单例模式验证"""
        # 创建两个实例
        engine1 = CollaborationEngine()
        engine2 = CollaborationEngine()

        # 在第一个实例注册能力
        engine1.register_agent_capabilities(
            agent_name="TestAgent",
            capabilities=["test_capability"],
            next_agent="NextAgent"
        )

        # 验证第二个实例也能访问到相同的注册信息
        capabilities = engine2.get_agent_capabilities("TestAgent")
        assert "test_capability" in capabilities
        assert engine2.get_next_agent("TestAgent") == "NextAgent"

        # 验证确实是同一个实例
        assert engine1 is engine2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

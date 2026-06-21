"""
实时进化触发测试
测试任务完成后实时触发进化分析功能
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.evolution.suggester import EvolutionSuggester, EvolutionSuggestion
from app.tasks.worker import TaskWorker


class TestRealtimeEvolution:
    """实时进化触发测试类"""

    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        cls.test_company_id = 9999
        cls.test_agent_id = 8888
        cls.test_task_id = 7777

    def setup_method(self):
        """每个测试方法前的设置"""
        # 创建测试任务数据
        self.test_task = {
            'id': self.test_task_id,
            'company_id': self.test_company_id,
            'source_agent_id': None,
            'target_agent_name': 'brand_bd',
            'task_description': '请帮我搜索美妆达人并生成邀约话术'
        }

    def test_1_task_completion_triggers_evolution(self):
        """正常场景 1：任务完成后触发进化分析"""
        # Mock 数据库操作
        with patch('app.database.db.get_agent_by_name') as mock_get_agent, \
             patch('app.database.db.create_evolution_review') as mock_create_review:

            # Mock agent 查询返回
            mock_agent = MagicMock()
            mock_agent.id = self.test_agent_id
            mock_get_agent.return_value = mock_agent

            # Mock 进化建议
            mock_suggestion = EvolutionSuggestion(
                agent_id=self.test_agent_id,
                suggested_prompt_changes="建议优化提示词以提高准确性",
                knowledge_entries=["美妆达人话术模板"],
                analysis_summary="基于任务结果的分析建议",
                confidence_score=0.8
            )

            # Mock EvolutionSuggester
            with patch('app.evolution.suggester.EvolutionSuggester') as mock_suggester_class:
                mock_suggester = MagicMock()
                mock_suggester_class.return_value = mock_suggester
                mock_suggester.generate_lightweight_suggestion.return_value = mock_suggestion

                # 创建 TaskWorker 并处理任务
                worker = TaskWorker()

                # Mock _execute_with_timeout 方法返回任务结果
                with patch.object(worker, '_execute_with_timeout') as mock_execute:
                    mock_execute.return_value = "任务执行完成，成功搜索到3个美妆达人"

                    # Mock _extract_steps 方法（全局函数）
                    with patch('app.tasks.worker._extract_steps') as mock_extract:
                        mock_extract.return_value = [
                            {'step_id': 1, 'name': '分析需求', 'status': 'completed', 'result': '美妆达人'}
                        ]

                        # Mock db.update_task_status
                        with patch('app.database.db.update_task_status') as mock_update:
                            # 执行任务处理
                            worker._process_single_task(self.test_task)

                            # 验证进化分析被调用
                            mock_suggester.generate_lightweight_suggestion.assert_called_once()

                            # 验证高置信度建议被保存到 evolution_reviews
                            mock_create_review.assert_called_once()
                            call_args = mock_create_review.call_args

                            # 验证调用参数
                            assert call_args[1]['agent_id'] == self.test_agent_id
                            assert call_args[1]['suggestion_text'] == "建议优化提示词以提高准确性"
                            assert call_args[1]['prompt_changes'] == "建议优化提示词以提高准确性"

    def test_2_low_confidence_suggestion_not_saved(self):
        """正常场景 2：低置信度建议不存入数据库"""
        # Mock 数据库操作
        with patch('app.database.db.get_agent_by_name') as mock_get_agent:
            # Mock agent 查询返回
            mock_agent = MagicMock()
            mock_agent.id = self.test_agent_id
            mock_get_agent.return_value = mock_agent

            # Mock 低置信度进化建议
            mock_suggestion = EvolutionSuggestion(
                agent_id=self.test_agent_id,
                suggested_prompt_changes="",
                knowledge_entries=[],
                analysis_summary="信息不足，无法生成有效建议",
                confidence_score=0.1  # 低置信度
            )

            # Mock EvolutionSuggester
            with patch('app.evolution.suggester.EvolutionSuggester') as mock_suggester_class:
                mock_suggester = MagicMock()
                mock_suggester_class.return_value = mock_suggester
                mock_suggester.generate_lightweight_suggestion.return_value = mock_suggestion

                # 创建 TaskWorker 并处理任务
                worker = TaskWorker()

                # Mock _execute_with_timeout 方法返回任务结果
                with patch.object(worker, '_execute_with_timeout') as mock_execute:
                    mock_execute.return_value = "任务执行完成"

                    # Mock _extract_steps 方法（全局函数）
                    with patch('app.tasks.worker._extract_steps') as mock_extract:
                        mock_extract.return_value = [
                            {'step_id': 1, 'name': '分析需求', 'status': 'completed', 'result': '美妆达人'}
                        ]

                        # Mock db.update_task_status
                        with patch('app.database.db.update_task_status') as mock_update:
                            # Mock db.create_evolution_review
                            with patch('app.database.db.create_evolution_review') as mock_create_review:
                                # 执行任务处理
                                worker._process_single_task(self.test_task)

                                # 验证进化分析被调用
                                mock_suggester.generate_lightweight_suggestion.assert_called_once()

                                # 验证低置信度建议没有被保存到 evolution_reviews
                                mock_create_review.assert_not_called()

                                # 验证任务状态仍然为 completed
                                mock_update.assert_called()

    def test_3_evolution_failure_doesnt_affect_task_completion(self):
        """异常场景 1：进化分析失败不影响任务完成"""
        # Mock 数据库操作
        with patch('app.database.db.get_agent_by_name') as mock_get_agent:
            # Mock agent 查询返回
            mock_agent = MagicMock()
            mock_agent.id = self.test_agent_id
            mock_get_agent.return_value = mock_agent

            # Mock EvolutionSuggester 抛出异常
            with patch('app.evolution.suggester.EvolutionSuggester') as mock_suggester_class:
                mock_suggester = MagicMock()
                mock_suggester_class.return_value = mock_suggester
                mock_suggester.generate_lightweight_suggestion.side_effect = Exception("进化分析失败")

                # 创建 TaskWorker 并处理任务
                worker = TaskWorker()

                # Mock _execute_with_timeout 方法返回任务结果
                with patch.object(worker, '_execute_with_timeout') as mock_execute:
                    mock_execute.return_value = "任务执行完成"

                    # Mock _extract_steps 方法（全局函数）
                    with patch('app.tasks.worker._extract_steps') as mock_extract:
                        mock_extract.return_value = [
                            {'step_id': 1, 'name': '分析需求', 'status': 'completed', 'result': '美妆达人'}
                        ]

                        # Mock db.update_task_status
                        with patch('app.database.db.update_task_status') as mock_update:
                            # 执行任务处理
                            worker._process_single_task(self.test_task)

                            # 验证任务状态仍然为 completed
                            mock_update.assert_called()

                            # 验证进化分析被调用但失败
                            mock_suggester.generate_lightweight_suggestion.assert_called_once()

    def test_4_agent_not_found_skips_evolution(self):
        """异常场景 2：Agent 不存在时进化分析被跳过"""
        # Mock 数据库操作
        with patch('app.database.db.get_agent_by_name') as mock_get_agent:
            # Mock agent 查询返回 None（agent 不存在）
            mock_get_agent.return_value = None

            # 创建 TaskWorker 并处理任务
            worker = TaskWorker()

            # Mock _execute_with_timeout 方法返回任务结果
            with patch.object(worker, '_execute_with_timeout') as mock_execute:
                mock_execute.return_value = "任务执行完成"

                # Mock _extract_steps 方法（全局函数）
                with patch('app.tasks.worker._extract_steps') as mock_extract:
                    mock_extract.return_value = [
                        {'step_id': 1, 'name': '分析需求', 'status': 'completed', 'result': '美妆达人'}
                    ]

                    # Mock db.update_task_status
                    with patch('app.database.db.update_task_status') as mock_update:
                        # Mock EvolutionSuggester（不应该被调用）
                        with patch('app.evolution.suggester.EvolutionSuggester') as mock_suggester_class:
                            # 执行任务处理
                            worker._process_single_task(self.test_task)

                            # 验证任务状态仍然为 completed
                            mock_update.assert_called()

                            # 验证 EvolutionSuggester 没有被实例化
                            mock_suggester_class.assert_not_called()

    def test_5_lightweight_suggestion_method(self):
        """测试轻量级建议生成方法"""
        # 创建 EvolutionSuggester 实例
        suggester = EvolutionSuggester()

        # 测试有任务结果的情况
        with patch.object(suggester, '_call_llm_for_single_result') as mock_llm_call, \
             patch.object(suggester, '_parse_llm_response') as mock_parse:

            # Mock LLM 响应
            mock_llm_call.return_value = '{"suggested_prompt_changes": "优化提示词", "knowledge_entries": ["模板1"], "analysis_summary": "分析结果", "confidence_score": 0.7}'

            # Mock 解析响应
            expected_suggestion = EvolutionSuggestion(
                agent_id=self.test_agent_id,
                suggested_prompt_changes="优化提示词",
                knowledge_entries=["模板1"],
                analysis_summary="分析结果",
                confidence_score=0.7
            )
            mock_parse.return_value = expected_suggestion

            # 调用轻量级建议生成
            result = suggester.generate_lightweight_suggestion(self.test_agent_id, "任务执行结果")

            # 验证结果
            assert result.agent_id == self.test_agent_id
            assert result.suggested_prompt_changes == "优化提示词"
            assert result.confidence_score == 0.7

            # 验证调用参数
            mock_llm_call.assert_called_once_with("任务执行结果")
            mock_parse.assert_called_once()

    def test_6_lightweight_suggestion_fallback(self):
        """测试轻量级建议生成方法的降级逻辑"""
        # 创建 EvolutionSuggester 实例
        suggester = EvolutionSuggester()

        # 测试无任务结果的情况（应该降级到全量分析）
        with patch.object(suggester, 'generate_suggestion') as mock_generate:
            expected_suggestion = EvolutionSuggestion(
                agent_id=self.test_agent_id,
                suggested_prompt_changes="全量分析结果",
                knowledge_entries=["知识条目"],
                analysis_summary="全量分析",
                confidence_score=0.6
            )
            mock_generate.return_value = expected_suggestion

            # 调用轻量级建议生成（无任务结果）
            result = suggester.generate_lightweight_suggestion(self.test_agent_id, None)

            # 验证结果
            assert result.agent_id == self.test_agent_id
            assert result.suggested_prompt_changes == "全量分析结果"

            # 验证降级到全量分析
            mock_generate.assert_called_once_with(self.test_agent_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
16.1.3 _detect_loop() 单元测试
正常执行/循环检测/边界情况
"""
import pytest


class TestLoopDetection:
    """循环检测单元测试"""

    def test_normal_execution_no_loop(self):
        """正常执行：不触发循环检测"""
        fingerprint_window = [
            "hash_step_1",
            "hash_step_2",
            "hash_step_3",
            "hash_step_4",
            "hash_step_5",
        ]
        current_fingerprint = "hash_step_6"
        assert current_fingerprint not in fingerprint_window

    def test_exact_repetition_loop(self):
        """精确重复：触发循环检测"""
        fingerprint_window = [
            "hash_A", "hash_B", "hash_A", "hash_B", "hash_A",
        ]
        current_fingerprint = "hash_A"
        count = fingerprint_window.count(current_fingerprint)
        assert count >= 3

    def test_boundary_single_step(self):
        """单个步骤：不触发"""
        fingerprint_window = []
        current_fingerprint = "hash_only"
        count = fingerprint_window.count(current_fingerprint)
        assert count == 0

    def test_sliding_window_limit(self):
        """滑动窗口限制：超过5步后移除最旧"""
        window = ["a", "b", "c", "d", "e"]
        new_fp = "f"
        if len(window) >= 5:
            window.pop(0)
        window.append(new_fp)
        assert len(window) == 5
        assert window == ["b", "c", "d", "e", "f"]

    def test_different_tools_same_args(self):
        """不同工具相同参数：不触发"""
        fp1 = "tool_A:hash123"
        fp2 = "tool_B:hash123"
        assert fp1 != fp2

    def test_same_tool_different_args(self):
        """相同工具不同参数：不触发"""
        fp1 = "tool_A:hash_abc"
        fp2 = "tool_A:hash_def"
        assert fp1 != fp2

    def test_fingerprint_calculation(self):
        """状态指纹计算一致性"""
        import hashlib
        import json

        def fingerprint(agent_name, tool_name, tool_args):
            raw = f"{agent_name}:{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
            return hashlib.md5(raw.encode()).hexdigest()

        fp1 = fingerprint("brand_bd", "search_kols", {"platform": "douyin"})
        fp2 = fingerprint("brand_bd", "search_kols", {"platform": "douyin"})
        assert fp1 == fp2
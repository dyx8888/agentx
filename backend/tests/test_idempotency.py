"""
IdempotencyManager 单元测试

重点验证引入"可选幂等令牌（idempotency_key / request_id）"后：
  - 同一逻辑请求的意外重试（相同令牌） => 幂等键相同 => 命中缓存、去重生效（保留现有保护）
  - 不同真实操作（不同令牌） => 幂等键不同 => 两次都真正执行（修复"相同参数被误拦"）
  - 未提供令牌（None / 空字符串） => 退回原有 params-hash 逻辑，行为与改动前完全一致（向后兼容）

场景类比：用户同一天两次充值 100 元，参数完全相同。
  - 改动前：第二次被幂等误拦，无法充值。
  - 改动后：调用方为两次充值各带一个不同的 idempotency_key，两次都能执行；
            而系统抖动导致的"同一请求意外重试"携带相同令牌，仍会被去重。
"""

import hashlib
import json
import os
import sys
from unittest.mock import patch

# 将 backend 目录加入 sys.path，保证可独立运行（与其它测试保持一致）
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


from app.core.idempotency import IdempotencyManager

# ── 测试常量：模拟"同一天两次充值 100 元，参数完全相同"的场景 ──────────────
COMPANY_ID = "company_A"
AGENT_NAME = "recharge_agent"
TOOL_NAME = "recharge"
BASE_PARAMS = {"amount": 100, "currency": "CNY", "user_id": "u_123"}


# ── 测试辅助 ──────────────────────────────────────────────────────────────
def _make_local_manager() -> IdempotencyManager:
    """构造一个仅使用本地内存缓存的 IdempotencyManager（绕过 Redis），保证测试隔离、可重复。

    通过 patch _connect 避免 __init__ 中真实连接 Redis（即便本机有 Redis 也不受影响），
    使 is_available 恒为 False，check_only / store 仅走本地 _local_cache。
    """
    with patch.object(IdempotencyManager, "_connect", return_value=False):
        return IdempotencyManager()


def _key(idempotency_key=None) -> str:
    """快捷生成幂等键的包装函数，省去重复参数。"""
    kwargs = {}
    if idempotency_key is not None:
        kwargs["idempotency_key"] = idempotency_key
    return IdempotencyManager.generate_key(COMPANY_ID, AGENT_NAME, TOOL_NAME, BASE_PARAMS, **kwargs)


# ── generate_key 层：令牌如何影响幂等键的计算 ──────────────────────────────
class TestGenerateKeyWithToken:
    def test_same_params_same_token_produces_same_key(self):
        """相同参数 + 相同令牌 => 幂等键完全相同（去重生效的基础）。"""
        k1 = _key("req-001")
        k2 = _key("req-001")
        assert k1 == k2

    def test_same_params_different_token_produces_different_key(self):
        """相同参数 + 不同令牌 => 幂等键不同（修复"误拦"的核心）。"""
        k1 = _key("req-001")
        k2 = _key("req-002")
        assert k1 != k2

    def test_no_token_matches_original_algorithm(self):
        """不传令牌 => 幂等键与改动前完全一致（仍等于纯 params-hash，向后兼容）。"""
        key_no_token = _key()
        # 按改动前的"原有算法"手工复算，确认未被破坏
        params_str = json.dumps(BASE_PARAMS, sort_keys=True, ensure_ascii=False, default=str)
        expected_hash = hashlib.sha256(params_str.encode()).hexdigest()[:16]
        expected_key = f"idem:{COMPANY_ID}:{AGENT_NAME}:{TOOL_NAME}:{expected_hash}"
        assert key_no_token == expected_key

    def test_none_or_empty_token_equals_no_token(self):
        """None / 空字符串令牌 => 与不传令牌完全等价（约束条件）。"""
        key_none = IdempotencyManager.generate_key(
            COMPANY_ID, AGENT_NAME, TOOL_NAME, BASE_PARAMS, idempotency_key=None
        )
        key_empty = IdempotencyManager.generate_key(
            COMPANY_ID, AGENT_NAME, TOOL_NAME, BASE_PARAMS, idempotency_key=""
        )
        key_omitted = _key()
        assert key_none == key_omitted
        assert key_empty == key_omitted

    def test_token_changes_key_even_with_same_params(self):
        """有令牌 vs 无令牌（参数相同）=> 幂等键不同，证明令牌确实参与计算。"""
        assert _key("req-001") != _key()


# ── manager 层（check_only + store）：验证三种验收场景的缓存命中/未命中 ───────
class TestIdempotencyCacheBehavior:
    def test_acceptance_1_same_token_second_call_hits_cache(self):
        """验收1：相同参数 + 相同 idempotency_key => 第二次命中缓存（去重生效）。"""
        mgr = _make_local_manager()
        key = _key("req-001")

        # 第一次：预检未命中 -> 真正执行 -> 存储成功结果
        assert mgr.check_only(key) is None
        mgr.store(key, {"order_id": "ord-1", "status": "ok"})

        # 第二次（相同令牌 => 相同 key）：预检命中缓存，跳过真正执行
        cached = mgr.check_only(key)
        assert cached is not None
        assert cached["order_id"] == "ord-1"

    def test_acceptance_2_different_token_both_calls_execute(self):
        """验收2：相同参数 + 不同 idempotency_key => 两次都真正执行（误拦被修复）。"""
        mgr = _make_local_manager()
        key1 = _key("req-001")
        key2 = _key("req-002")
        assert key1 != key2  # 前提：不同令牌产生不同键

        # 第一次充值：预检未命中 -> 真正执行 -> 存储
        assert mgr.check_only(key1) is None
        mgr.store(key1, {"order_id": "ord-1"})

        # 第二次充值（不同令牌）：预检仍未命中 -> 允许真正执行，不被误拦
        assert mgr.check_only(key2) is None
        mgr.store(key2, {"order_id": "ord-2"})

        # 两次结果各自独立保留，互不覆盖
        assert mgr.check_only(key1)["order_id"] == "ord-1"
        assert mgr.check_only(key2)["order_id"] == "ord-2"

    def test_acceptance_3_no_token_cache_hit_backward_compatible(self):
        """验收3：相同参数 + 都不传 idempotency_key => 行为与改动前一致（命中缓存）。"""
        mgr = _make_local_manager()
        key = _key()  # 不传令牌，退回原有 params-hash 逻辑

        assert mgr.check_only(key) is None
        mgr.store(key, {"order_id": "ord-1"})

        # 第二次（同样不传令牌 => 相同 key）：命中缓存，与改动前行为一致
        cached = mgr.check_only(key)
        assert cached is not None
        assert cached["order_id"] == "ord-1"
